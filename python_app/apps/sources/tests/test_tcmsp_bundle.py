import hashlib,json,sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from openpyxl import Workbook
from django.test import TestCase
from apps.core.models import DataSource,SourceRelease,KnowledgeEntity,EvidenceRelation,SourceRecord,SourceEntityMapping
from apps.sources.connectors.target_reference import HEADER,QUERY,FIELDS
from apps.sources.tcmsp_bundle import prepare_bundle,INGREDIENT_HEADER,TARGET_HEADER,DISEASE_HEADER
from apps.sources.tcmsp_publish import publish_bundle
from apps.core.services.data_quality import compound_properties
from apps.core.services.target_identity import compare_target_identities


class TcmspBundleTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'TCMSP全部数据').mkdir();(self.root/'TCMSP_data').mkdir()
        raw=('\t'.join(HEADER)+'\nP05231\t9606\tIL6\t3569;\tInterleukin-6 (IL-6)\n').encode()
        (self.root/'ref.tsv').write_bytes(raw);self.manifest=self.root/'ref.json'
        self.manifest.write_text(json.dumps({'schemaVersion':'target-reference-v1','query':QUERY,'fields':FIELDS,
            'url':'https://rest.uniprot.org/uniprotkb/stream?fixture=1','file':'ref.tsv','version':'test_1','recordCount':1,'sha256':hashlib.sha256(raw).hexdigest()}))
        self.source=DataSource.objects.create(slug='tcmsp',name='TCMSP',configuration={'connector':'local-workbooks-master'})
        self.old=SourceRelease.objects.create(source=self.source,version='old')
        self.h=KnowledgeEntity.objects.create(entity_type='herb',stable_id='old-herb',label='old herb',source_release=self.old)
        self.c=KnowledgeEntity.objects.create(entity_type='compound',stable_id='old-compound',label='old compound',source_release=self.old)
        self.edge=EvidenceRelation.objects.create(source_release=self.old,source_record_id='old',subject=self.h,object=self.c,relation_type='contains',evidence_type='fixture')
        self.ingredients=[['Maidong','麦冬','MOL000001',1,'file.mol2','example compound',0,100,1,0,0,None,0,0,0,0],
            ['Maidong','麦冬','MOL000001',1,'file.mol2','example compound',0,100,1,0,0,None,0,0,0,0],['Empty','空数据']]
        good=['Maidong','麦冬','MOL000001',1,'example compound','Interleukin-6',1,1,'',0.8,0.7,'P05231','IL6']
        bad=['Maidong','麦冬','MOL000001',1,'example compound','Wrong protein',2,2,'validated',None,None,'P05231','IL6']
        self.targets=[good,good,bad]
        self.diseases=[['Interleukin-6',1,1,'Pulmonary fibrosis',7],['Interleukin-6',1,1,'Pulmonary fibrosis',7],['Wrong protein',2,2,'Pulmonary fibrosis',7]]
    def book(self,file,header,rows):
        wb=Workbook();ws=wb.active;ws.append(header)
        for r in rows:ws.append(r)
        wb.save(self.root/file);wb.close()
    def prepare(self):
        self.book('TCMSP全部数据/TCMSP_merged_ingredients.xlsx',INGREDIENT_HEADER,self.ingredients)
        self.book('TCMSP全部数据/TCMSP_merged_targets.xlsx',TARGET_HEADER,self.targets)
        self.book('TCMSP_data/Maidong_disease.xlsx',DISEASE_HEADER,self.diseases)
        self.stage=self.root/'stage.sqlite3'
        return prepare_bundle(self.root,self.manifest,self.stage,progress=lambda _:None)
    def publish(self):return publish_bundle(self.stage,self.root,self.manifest,apply=True,progress=lambda _:None)
    def test_staging_preserves_raw_and_deduplicates_without_touching_live_graph(self):
        info=self.prepare();self.assertEqual(info['counts']['rawRows'],9)
        self.assertEqual(info['counts']['targetReviewStatuses'],{'conflict':1,'verified':1})
        self.assertEqual(EvidenceRelation.objects.count(),1)
        with closing(sqlite3.connect(self.stage)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM edge WHERE relation='targets'").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM edge WHERE relation='disease_herb_target'").fetchone()[0],1)
    def test_publication_is_versioned_and_idempotent_and_normalization_is_live(self):
        self.prepare();result=self.publish();again=self.publish();self.assertEqual(again['state'],'unchanged')
        self.edge.refresh_from_db();self.assertFalse(self.edge.is_active)
        self.assertEqual(SourceRecord.objects.filter(source_release_id=result['releaseId']).count(),9)
        self.assertEqual(EvidenceRelation.objects.filter(source_release_id=result['releaseId'],is_active=True).count(),4)
        target=SourceEntityMapping.objects.get(source_release_id=result['releaseId'],namespace='tcmsp.target_id',source_entity_id='1').entity
        self.assertEqual(compare_target_identities({target.pk},{target.pk})['verifiedGeneIntersectionCount'],1)
        self.assertFalse(EvidenceRelation.objects.filter(is_active=True,source_record_ref__status='quarantined').exists())
        self.assertEqual(self.h.stable_id,'old-herb')
    def test_properties_keep_zero_and_true_field_provenance(self):
        self.prepare();r=self.publish();entity=SourceEntityMapping.objects.get(source_release_id=r['releaseId'],namespace='tcmsp.mol_id').entity
        props=compound_properties(entity)
        self.assertEqual(props['values']['ob'],0);self.assertIsNone(props['values']['halflife'])
        self.assertEqual(props['fieldSourceRecords']['mw'],'ingredients:000000002')
    def test_conflicting_properties_are_not_averaged_or_filled_with_zero(self):
        self.ingredients[1][7]=101;self.prepare();r=self.publish()
        entity=SourceEntityMapping.objects.get(source_release_id=r['releaseId'],namespace='tcmsp.mol_id').entity
        props=compound_properties(entity);self.assertIsNone(props['values']['mw']);self.assertIn('mw',props['conflicts'])
    def test_failed_publication_keeps_old_active_version_and_can_resume(self):
        self.prepare()
        with patch('apps.sources.tcmsp_publish.build_target_identities',side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):self.publish()
        self.edge.refresh_from_db();self.assertTrue(self.edge.is_active)
        self.source.refresh_from_db();self.assertNotIn('activeSupplementReleaseId',self.source.configuration)
        r=self.publish();self.assertEqual(r['state'],'published');self.assertEqual(SourceRecord.objects.filter(source_release_id=r['releaseId']).count(),9)
    def test_changed_workbook_cannot_publish_a_stale_stage(self):
        self.prepare();self.book('TCMSP_data/Maidong_disease.xlsx',DISEASE_HEADER,[])
        before=SourceRelease.objects.count()
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual(SourceRelease.objects.count(),before)
    def test_formula_cell_is_kept_as_text_but_not_activated(self):
        self.targets[0][11]='=BAD()';self.prepare();r=self.publish()
        self.assertGreater(r['counts']['quarantined'],0)
        self.assertFalse(EvidenceRelation.objects.filter(is_active=True,relation_type='targets').exists())
