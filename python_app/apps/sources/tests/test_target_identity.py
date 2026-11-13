import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, SimpleTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import (CanonicalIdentifier, DataSource, EvidenceRelation, KnowledgeEntity,
    SourceRelease, TargetMaster, TargetIdentityMapping)
from apps.core.services.network_pharmacology import build_network_pharmacology
from apps.core.services.target_identity import compare_target_identities
from apps.sources.connectors.ncbi_gene_reference import (EXPECTED_COLUMNS,
    parse_reference as parse_ncbi_reference, select_matching_rows)
from apps.sources.connectors.target_reference import FIELDS, HEADER, QUERY, load_reference, parse_reference
from apps.sources.target_identity import ReferenceIndex, build_target_identities, current_release, input_profiles

RAW = ('\t'.join(HEADER)+'\nP05231\t9606\tIL6\t3569;\tInterleukin-6 (IL-6)\n'
       'P01375\t9606\tTNF\t7124;\tTumor necrosis factor\n'
       'P04637\t9606\tTP53\t7157;\tCellular tumor antigen p53\n').encode()


def profile(kind='gene', taxon='unknown', label='IL6', ids=None):
    return {'id': 1, 'kind': kind, 'taxon': taxon, 'label': label, 'metadata': {}, 'ids': ids or []}


class ReferenceResolutionTests(SimpleTestCase):
    def setUp(self): self.index = ReferenceIndex(parse_reference(RAW))
    def test_unknown_species_names_are_candidates_not_verified(self):
        for record in [profile(), profile(kind='protein', label='Interleukin-6'), profile(taxon='9606')]:
            result = self.index.resolve(record)
            self.assertEqual(result['status'], 'candidate'); self.assertIsNone(result['master'])
            self.assertIsNone(result['gene']); self.assertEqual(result['candidates'][0]['geneKey'], 'entrez:9606:3569')
            self.assertEqual(record['taxon'], result['evidence']['originalTaxon'])
    def test_exact_gene_and_protein_ids_have_separate_master_keys(self):
        gene=self.index.resolve(profile(ids=[['entrez','3569']]))
        protein=self.index.resolve(profile(kind='protein', ids=[['uniprot','P05231']]))
        self.assertEqual(gene['status'], 'verified'); self.assertEqual(protein['status'], 'verified')
        self.assertNotEqual(gene['master'], protein['master']); self.assertEqual(gene['gene'], protein['gene'])
    def test_conflicting_ids_and_species_never_verify(self):
        for record in [profile(ids=[['entrez','3569'],['uniprot','P01375']]),
                       profile(taxon='10090', ids=[['entrez','3569']])]:
            self.assertEqual(self.index.resolve(record)['status'],'conflict')
    def test_multiple_genes_do_not_force_one_gene_identity(self):
        row = parse_reference(RAW)[0]; row['geneIds'] = ['3569','12345']
        index=ReferenceIndex([row])
        result=index.resolve(profile(ids=[['uniprot','P05231']]))
        self.assertEqual(result['status'],'ambiguous');self.assertIsNone(result['gene'])
        protein=index.resolve(profile(kind='protein',ids=[['uniprot','P05231']]))
        self.assertEqual(protein['status'],'verified'); self.assertIsNone(protein['gene'])
    def test_missing_old_or_nonhuman_ids_stay_unresolved(self):
        result=self.index.resolve(profile(label='not-a-gene',ids=[['entrez','999999999']]))
        self.assertEqual(result['status'],'unmapped'); self.assertIsNone(result['gene'])
    def test_invalid_reference_rows_fail_closed(self):
        for raw in [RAW.replace(b'9606',b'10090',1), RAW + RAW.split(b'\n')[1]+b'\n', b'Wrong\tHeader\n',
                    RAW.replace(b'3569;',b'BAD;')]:
            with self.subTest(raw=raw[:35]), self.assertRaises(ValueError): parse_reference(raw)
    def test_ncbi_official_names_and_aliases_resolve_to_gene_id_but_unknown_taxon_stays_candidate(self):
        ncbi_rows=[{'geneId':'3569','symbol':'IL6','synonyms':['Interleukin-6 alias'],
            'description':'interleukin 6', 'geneType':'protein-coding', 'officialSymbol':'IL6',
            'officialName':'interleukin 6', 'otherDesignations':['interleukin-6']}]
        index=ReferenceIndex([], ncbi_rows)
        for name in ['IL6','Interleukin-6 alias','interleukin 6']:
            result=index.resolve(profile(kind='protein',label=name))
            self.assertEqual(result['status'],'candidate')
            self.assertIsNone(result['master'])
            self.assertEqual(result['candidates'][0]['geneKey'],'entrez:9606:3569')
            self.assertIn('NCBI Gene human nomenclature',result['candidates'][0]['referenceSources'])
    def test_ncbi_duplicate_name_remains_ambiguous(self):
        ncbi_rows=[{'geneId':str(gene),'symbol':f'G{gene}','synonyms':['shared alias'],
            'description':f'gene {gene}', 'geneType':'protein-coding', 'officialSymbol':f'G{gene}',
            'officialName':f'gene {gene}', 'otherDesignations':[]} for gene in [101,202]]
        result=ReferenceIndex([], ncbi_rows).resolve(profile(kind='protein',label='shared alias'))
        self.assertEqual(result['status'],'ambiguous')
        self.assertEqual(result['candidateCount'],2)
    def test_punctuation_normalized_ncbi_name_is_still_only_a_candidate(self):
        ncbi_rows=[{'geneId':'3569','symbol':'IL6','synonyms':[], 'description':'interleukin-6',
            'geneType':'protein-coding','officialSymbol':'IL6','officialName':'interleukin-6',
            'otherDesignations':[]}]
        result=ReferenceIndex([],ncbi_rows).resolve(profile(kind='protein',label='Interleukin 6'))
        self.assertEqual(result['status'],'candidate')
        self.assertEqual(result['method'],'normalized_ncbi_official_name_candidate')
        self.assertEqual(result['candidates'][0]['geneKey'],'entrez:9606:3569')
    def test_multiple_protein_accessions_for_one_gene_resolve_only_gene_level_candidate(self):
        rows=parse_reference(RAW)
        rows[0]['proteinName']='Shared protein name'
        rows[1]['proteinName']='Shared protein name'
        rows[1]['geneIds']=['3569']
        result=ReferenceIndex(rows).resolve(profile(kind='protein',label='Shared protein name'))
        self.assertEqual(result['status'],'candidate')
        self.assertEqual(result['method'],'unique_gene_from_protein_candidates')
        self.assertEqual(result['candidates'][0]['key'],'entrez:9606:3569')


class NcbiGeneReferenceTests(SimpleTestCase):
    def test_ncbi_human_reference_parser_checks_species_and_gene_ids(self):
        rows=[['9606',str(i),'GENE'+str(i), '-', 'ALIAS'+str(i), '-', '-', '-', 'description '+str(i),
            'protein-coding', 'GENE'+str(i), 'official description '+str(i), 'Official', '-', '20260101', '-']
            for i in range(1,10001)]
        raw=('\t'.join(EXPECTED_COLUMNS)+'\n'+'\n'.join('\t'.join(row) for row in rows)+'\n').encode()
        import gzip
        parsed=parse_ncbi_reference(gzip.compress(raw))
        self.assertEqual(len(parsed),10000)
        self.assertEqual(parsed[0]['geneId'],'1')
        self.assertIn('ALIAS1',parsed[0]['synonyms'])
        self.assertEqual(parsed[0]['officialName'],'official description 1')
        with self.assertRaises(ValueError): parse_ncbi_reference(gzip.compress(raw.replace(b'9606\t1\t',b'10090\t1\t',1)))
    def test_reference_prefilter_keeps_punctuation_equivalent_names(self):
        row={'geneId':'1588','symbol':'CYP1A1','synonyms':[], 'description':'cytochrome P450 family 1 subfamily A member 1',
            'officialSymbol':'CYP1A1','officialName':'cytochrome P450 family 1 subfamily A member 1','otherDesignations':[]}
        self.assertEqual(select_matching_rows([row],{'Cytochrome P450-family 1, subfamily A member 1'}),[row])


class TargetIdentityIntegrationTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        path=Path(self.tmp.name);(path/'reference.tsv').write_bytes(RAW)
        self.manifest=path/'reference.manifest.json'
        self.manifest.write_text(json.dumps({'schemaVersion':'target-reference-v1','query':QUERY,'fields':FIELDS,
            'url':'https://rest.uniprot.org/uniprotkb/stream?fixture=1','file':'reference.tsv','version':'test_1',
            'recordCount':3,'sha256':hashlib.sha256(RAW).hexdigest()}),encoding='utf-8')
        self.source=DataSource.objects.create(slug='identity-local',name='Local',access_mode='download')
        self.release=SourceRelease.objects.create(source=self.source,version='v1')
        self.user=get_user_model().objects.create_user(username='identity-user')
        self.gene=self.entity('gene','il6-gene','IL6')
        self.protein=self.entity('protein','il6-protein','Interleukin-6')
        self.pending=self.entity('protein','il6-name','Interleukin-6')
        self.identifier(self.gene,'entrez','3569');self.identifier(self.protein,'uniprot','P05231')
    def entity(self,kind,stable,label,**kwargs):
        return KnowledgeEntity.objects.create(entity_type=kind,stable_id=stable,label=label,source_release=self.release,**kwargs)
    def identifier(self,entity,namespace,identifier):
        return CanonicalIdentifier.objects.create(entity=entity,entity_type=entity.entity_type,namespace=namespace,
            identifier=identifier,scope=self.source.slug,source=self.source,taxon_key=entity.taxon_key,match_method='fixture')
    def apply(self): return build_target_identities(self.manifest,apply=True)
    def test_preview_writes_nothing_and_apply_is_idempotent(self):
        original=list(KnowledgeEntity.objects.values_list('pk','stable_id','canonical_id','taxon_key'))
        preview=build_target_identities(self.manifest);self.assertFalse(preview['applied'])
        self.assertEqual(TargetMaster.objects.count(),0)
        first=self.apply();second=self.apply();self.assertEqual(first['releaseId'],second['releaseId'])
        self.assertEqual(TargetIdentityMapping.objects.count(),3);self.assertEqual(TargetMaster.objects.count(),6)
        self.assertEqual(original,list(KnowledgeEntity.objects.values_list('pk','stable_id','canonical_id','taxon_key')))
    def test_verified_gene_and_protein_comparison_and_pending_separation(self):
        self.apply()
        result=compare_target_identities({self.gene.pk},{self.protein.pk,self.pending.pk})
        self.assertEqual(result['verifiedGeneIntersectionCount'],1)
        self.assertEqual(result['verifiedProteinIntersectionCount'],0)
        self.assertEqual(result['disease']['verifiedRecords'],1);self.assertEqual(result['disease']['pendingRecords'],1)
        self.assertEqual(result['disease']['records'],sum(result['disease']['statuses'].values()))
        self.assertEqual(result['disease']['pendingRecords'],sum(
            count for status,count in result['disease']['statuses'].items() if status!='verified'))
        pending_only=compare_target_identities({self.gene.pk},{self.pending.pk})
        self.assertEqual(pending_only['verifiedGeneIntersectionCount'],0)
        self.assertEqual(pending_only['pendingGeneOverlapCount'],1)
    def test_changed_input_rejected_until_a_new_version_is_built(self):
        first=self.apply(); self.gene.label='changed';self.gene.save(update_fields=['label'])
        result=compare_target_identities({self.gene.pk},{self.protein.pk})
        self.assertEqual(result['verifiedGeneIntersectionCount'],0)
        self.assertEqual(result['herb']['statuses'],{'unmapped':1})
        second=self.apply();self.assertNotEqual(first['releaseId'],second['releaseId'])
        self.assertEqual(TargetIdentityMapping.objects.filter(reference_release_id=first['releaseId']).count(),3)
    def test_ambiguous_functional_name_is_not_counted_as_a_unique_common_candidate(self):
        raw=RAW.replace(b'Interleukin-6 (IL-6)',b'Interleukin-6 (Shared function)').replace(b'Tumor necrosis factor',b'Tumor necrosis factor (Shared function)')
        (Path(self.tmp.name)/'reference.tsv').write_bytes(raw)
        manifest=json.loads(self.manifest.read_text());manifest['sha256']=hashlib.sha256(raw).hexdigest()
        self.manifest.write_text(json.dumps(manifest))
        self.pending.label='Shared function';self.pending.save();self.apply()
        self.assertEqual(TargetIdentityMapping.objects.get(entity=self.pending).status,'ambiguous')
        result=compare_target_identities({self.gene.pk},{self.pending.pk})
        self.assertEqual(result['verifiedGeneIntersectionCount'],0)
        self.assertEqual(result['pendingGeneOverlapCount'],0)
        self.assertEqual(result['disease']['statuses'],{'ambiguous':1})
    def test_disabled_reference_or_original_source_excluded(self):
        self.apply(); release=current_release();release.source.enabled=False;release.source.save()
        self.assertFalse(compare_target_identities({self.gene.pk},{self.protein.pk})['available'])
        release.source.enabled=True;release.source.save();self.source.enabled=False;self.source.save()
        self.assertEqual(input_profiles({self.gene.pk}),{})
        self.assertEqual(compare_target_identities({self.gene.pk},{self.protein.pk})['verifiedGeneIntersectionCount'],0)
    def test_failure_during_write_does_not_publish_partial_reference(self):
        with patch.object(TargetIdentityMapping.objects,'bulk_create',side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError): self.apply()
        self.assertIsNone(current_release()); self.assertEqual(TargetMaster.objects.count(),0)
    def test_reference_checksum_and_count_verified_before_write(self):
        data=json.loads(self.manifest.read_text());data['sha256']='0'*64
        self.manifest.write_text(json.dumps(data))
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(TargetMaster.objects.count(),0)
    def test_nonverified_record_cannot_point_to_confirmed_master(self):
        self.apply()
        with self.assertRaises(IntegrityError), transaction.atomic():
            TargetIdentityMapping.objects.filter(entity=self.pending).update(master_id='uniprot:9606:P05231')
    def test_admin_endpoint_permissions_filtering_and_validation(self):
        self.apply();client=APIClient();url=reverse('target-identity-list')
        self.assertEqual(client.get(url).status_code,401);client.force_authenticate(self.user)
        self.assertEqual(client.get(url).status_code,403)
        self.user.is_staff=True;self.user.is_superuser=True;self.user.save();client.force_authenticate(self.user)
        response=client.get(url,{'status':'candidate','search':'Interleukin'})
        self.assertEqual(response.status_code,200);self.assertEqual(response.data['count'],1)
        self.assertEqual(client.get(url,{'status':'invented'}).status_code,400)
        self.assertEqual(client.get(url,{'page':'abc'}).status_code,400)
    def test_standard_comparison_includes_later_sources_beyond_raw_row_limit(self):
        self.apply()
        herb=self.entity('herb','all-herb','all-herb');compound=self.entity('compound','all-compound','all-compound')
        disease=self.entity('disease','all-disease','all-disease')
        for idx,(subject,obj,relation) in enumerate([(herb,compound,'contains'),(compound,self.gene,'targets'),
                (disease,self.pending,'disease_target'),(disease,self.protein,'disease_target')]):
            EvidenceRelation.objects.create(source_release=self.release,source_record_id=f'all{idx}',subject=subject,
                object=obj,relation_type=relation,evidence_type='fixture')
        result=build_network_pharmacology(user=self.user,herb_query='all-herb',disease_query='all-disease',row_limit=1,persist=False)
        self.assertTrue(result['rawLimits']['inputRelationsTruncated']['diseaseTargets'])
        self.assertEqual(result['targetIdentity']['verifiedGeneIntersectionCount'],1)
        self.assertEqual(result['targetIdentity']['disease']['records'],2)
        self.assertFalse(result['targetIdentity']['coverage']['rawRowLimitsApplied'])

    def test_network_exposes_both_levels_preserves_raw_edges_and_snapshots(self):
        self.apply(); herb=self.entity('herb','herb','test-herb');compound=self.entity('compound','compound','test-compound')
        disease=self.entity('disease','disease','test-disease')
        for idx,(subject,obj,relation) in enumerate([(herb,compound,'contains'),(compound,self.gene,'targets'),(disease,self.protein,'disease_target')]):
            EvidenceRelation.objects.create(source_release=self.release,source_record_id=f'row{idx}',subject=subject,object=obj,relation_type=relation,evidence_type='fixture')
        result=build_network_pharmacology(user=self.user,herb_query='test-herb',disease_query='test-disease',row_limit=100,persist=True)
        self.assertEqual(result['summary']['strictIntersectionCount'],1)
        self.assertEqual(result['summary']['strictEntityIdIntersectionCount'],0)
        self.assertEqual(result['summary']['herbTargetCount'],1)
        self.assertEqual(result['summary']['diseaseTargetCount'],1)
        self.assertEqual(len(result['targets']),1)
        self.assertEqual(result['targets'][0]['matchType'],'严格交集')
        self.assertEqual(set(result['targets'][0]['sourceEntityIds']),{self.gene.pk,self.protein.pk})
        self.assertEqual(result['targets'][0]['canonicalTargetKey'],'entrez:9606:3569')
        self.assertEqual(result['targetIdentity']['verifiedGeneIntersectionCount'],1)
        self.assertEqual(EvidenceRelation.objects.count(),3)
        from apps.core.models import AnalysisTask
        task=AnalysisTask.objects.get(pk=result['taskId']);saved=task.result
        self.assertIn(current_release().pk,task.source_releases.values_list('pk',flat=True))
        self.gene.label='new label';self.gene.save();self.apply();task.refresh_from_db()
        self.assertEqual(task.result,saved)

    def test_complete_snapshot_keeps_original_ids_when_verified_targets_merge(self):
        from apps.core.models import AnalysisTask
        from apps.core.services.complete_evidence import _network_data
        from apps.core.services.scientist_report import build_report
        self.apply()
        herb=self.entity('herb','snapshot-herb','snapshot-herb')
        compound=self.entity('compound','snapshot-compound','snapshot-compound')
        disease=self.entity('disease','snapshot-disease','snapshot-disease')
        expected={}
        for index,(subject,obj,kind,target) in enumerate([
            (herb,compound,'contains',self.gene),
            (compound,self.gene,'targets',self.gene),
            (disease,self.protein,'disease_target',self.protein),
        ]):
            edge=EvidenceRelation.objects.create(source_release=self.release,source_record_id=f'snapshot:{index}',
                subject=subject,object=obj,relation_type=kind,evidence_type='fixture')
            expected[edge.pk]=(target.pk,target.stable_id)
        parameters={'herb':herb.label,'disease':disease.label,'formulaHerbs':[herb.label],
                    'question':'Synthetic identity provenance','focus':'source identities'}
        result,tables=_network_data(AnalysisTask(owner=self.user,input_parameters=parameters),100)
        sources=list(tables['targetSources'])
        self.assertEqual({row['relationId']:(row['targetEntityId'],row['targetStableId']) for row in sources},expected)
        self.assertEqual(set(tables['targets'][0]['sourceEntityIds']),{self.gene.pk,self.protein.pk})
        report,_=build_report(parameters,result,tables)
        self.assertTrue(report['identityMerged'])
        self.assertTrue(report['authorityIdentityVerified'])
        self.assertEqual(report['results']['intersection_count'],1)

    def test_complete_entity_intersection_is_not_lost_to_relation_row_limit(self):
        self.apply(); herb=self.entity('herb','limited-herb','limited-herb')
        compound=self.entity('compound','limited-compound','limited-compound')
        disease=self.entity('disease','limited-disease','limited-disease')
        EvidenceRelation.objects.create(source_release=self.release,source_record_id='limited-herb-compound',
            subject=herb,object=compound,relation_type='contains',evidence_type='fixture')
        EvidenceRelation.objects.create(source_release=self.release,source_record_id='limited-target-first',
            subject=compound,object=self.gene,relation_type='targets',evidence_type='fixture')
        EvidenceRelation.objects.create(source_release=self.release,source_record_id='limited-target-common',
            subject=compound,object=self.protein,relation_type='targets',evidence_type='fixture')
        EvidenceRelation.objects.create(source_release=self.release,source_record_id='limited-disease-common',
            subject=disease,object=self.protein,relation_type='disease_target',evidence_type='fixture')
        result=build_network_pharmacology(user=self.user,herb_query='limited-herb',disease_query='limited-disease',
            row_limit=1,persist=False)
        self.assertEqual(result['summary']['strictIntersectionCount'],1)
        self.assertEqual(result['summary']['strictEntityIdIntersectionCount'],1)
        self.assertEqual(set(result['targets'][0]['sourceEntityIds']),{self.gene.pk,self.protein.pk})
        self.assertTrue(result['rawLimits']['inputRelationsTruncated']['compoundTargets'])
        comparison=result['targetIdentity']['entityIdComparison']
        self.assertEqual(comparison['herbTargetCount'],2)
        self.assertEqual(comparison['diseaseTargetCount'],1)
        self.assertEqual(comparison['intersectionCount'],1)
        self.assertEqual(comparison['intersectionEntities'][0]['id'],self.protein.pk)
