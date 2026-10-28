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
        self.assertEqual(result['summary']['strictIntersectionCount'],0)
        self.assertEqual(result['targetIdentity']['verifiedGeneIntersectionCount'],1)
        self.assertEqual(EvidenceRelation.objects.count(),3)
        from apps.core.models import AnalysisTask
        task=AnalysisTask.objects.get(pk=result['taskId']);saved=task.result
        self.assertIn(current_release().pk,task.source_releases.values_list('pk',flat=True))
        self.gene.label='new label';self.gene.save();self.apply();task.refresh_from_db()
        self.assertEqual(task.result,saved)
