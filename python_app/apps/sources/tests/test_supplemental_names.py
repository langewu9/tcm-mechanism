from pathlib import Path
from tempfile import TemporaryDirectory
from openpyxl import Workbook
from django.test import TestCase
from apps.core.models import DataSource, SourceRelease, KnowledgeEntity, SourceRecord, SourceEntityMapping, EvidenceRelation
from apps.sources.supplemental_names import import_batman_names
from apps.core.services.catalog_identity import exact_entity_queryset


class SupplementalNamesTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'names.xlsx'
        source = DataSource.objects.create(slug='batman', name='BATMAN')
        release = SourceRelease.objects.create(source=source, version='original')
        self.herb = KnowledgeEntity.objects.create(entity_type='herb', label='麦冬', stable_id='batman:herb:1', source_release=release)

    def write(self, rows):
        w = Workbook()
        w.active.append(['Pinyin.Name', 'Chinese.Name', 'English.Name', 'Latin.Name'])
        for row in rows:
            w.active.append(row)
        w.save(self.path)
        w.close()

    def test_aliases_are_retrieval_only_and_idempotent(self):
        self.write([['MAI DONG', '麦冬', 'Dwarf lilyturf', 'Radix ophiopogonis']])
        self.assertEqual(import_batman_names(self.path)['state'], 'preview')
        self.assertEqual(SourceRecord.objects.count(), 0)
        first = import_batman_names(self.path, apply=True)
        self.assertEqual(list(exact_entity_queryset('herb', 'mai dong')), [self.herb])
        self.assertEqual(import_batman_names(self.path, apply=True)['state'], 'unchanged')
        self.assertEqual(SourceRecord.objects.count(), 1)
        self.assertEqual(SourceEntityMapping.objects.count(), 4)
        self.assertEqual(EvidenceRelation.objects.count(), 0)
        self.assertEqual(KnowledgeEntity.objects.count(), 1)

    def test_shared_alias_with_unknown_herb_stays_ambiguous(self):
        self.write([['MAI DONG', '麦冬', 'shared', ''], ['OTHER', '另一种药', 'shared', '']])
        import_batman_names(self.path, apply=True)
        self.assertFalse(exact_entity_queryset('herb', 'shared').exists())
        row = SourceEntityMapping.objects.get(namespace='batman.name.english')
        self.assertEqual(row.status, 'ambiguous')
        self.assertIsNone(row.entity_id)

    def test_missing_and_formula_rows_are_retained_without_binding(self):
        self.write([['UNKNOWN', '无此药', '', ''], ['=HYPERLINK("bad")', '麦冬', '', '']])
        result = import_batman_names(self.path, apply=True)
        self.assertEqual(result['quarantined'], 2)
        self.assertEqual(SourceRecord.objects.count(), 2)
        self.assertFalse(SourceEntityMapping.objects.filter(status='mapped').exists())

    def test_duplicate_chinese_entities_are_not_picked_arbitrarily(self):
        KnowledgeEntity.objects.create(entity_type='herb', label='麦冬', stable_id='batman:herb:2', source_release=self.herb.source_release)
        self.write([['MAI DONG', '麦冬', '', '']])
        import_batman_names(self.path, apply=True)
        self.assertFalse(SourceEntityMapping.objects.filter(status='mapped').exists())
