from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from openpyxl import Workbook
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.core.models import (CanonicalIdentifier, DataSource, EvidenceRelation,
    KnowledgeEntity, SourceEntityMapping, SourceRecord, SourceRelease)
from apps.sources.legacy_workbooks import SOURCES, normalize_row
from apps.sources.workbook_import import import_workbook


class WorkbookImportTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def workbook(self, slug, rows):
        definition = SOURCES[slug]
        book = Workbook()
        sheet = book.active
        sheet.append(definition.headers)
        for row in rows:
            sheet.append([row.get(header) for header in definition.headers])
        book.save(Path(self.directory.name) / definition.filename)
        book.close()

    def batman(self, **changes):
        return {"Herb Name": "Huanglian", "中文名": "黄连", "Compound Name": "Quercetin",
            "CID": "5280343", "Gene ID": "7157", "Gene Name": "TP53", "Score": "known target in HIT", **changes}

    def test_preview_has_no_database_writes(self):
        self.workbook("batman", [self.batman()])
        before = {model: model.objects.count() for model in (DataSource, SourceRecord, KnowledgeEntity, SourceRelease)}
        result = import_workbook(self.directory.name, "batman")
        self.assertEqual((result["rows"], result["relations"]), (1, 2))
        for model in (DataSource, SourceRecord, KnowledgeEntity, SourceRelease):
            self.assertEqual(model.objects.count(), before[model])

    def test_raw_duplicates_are_preserved_and_repeat_is_idempotent(self):
        self.workbook("batman", [self.batman(), self.batman()])
        result = import_workbook(self.directory.name, "batman", apply=True)
        self.assertEqual(result["state"], "published")
        self.assertEqual(SourceRecord.objects.count(), 2)
        self.assertEqual(SourceRecord.objects.values("payload_sha256").distinct().count(), 1)
        self.assertEqual(EvidenceRelation.objects.filter(is_active=True).count(), 4)
        self.assertFalse(EvidenceRelation.objects.filter(source_record_ref=None).exists())
        self.assertIsNone(EvidenceRelation.objects.get(source_record_id="Sheet1:000000002:edge:1").score)
        self.assertEqual(import_workbook(self.directory.name, "batman", apply=True)["state"], "unchanged")
        self.assertEqual(SourceRecord.objects.count(), 2)
        self.assertIsNone(DataSource.objects.get(slug="batman").refresh_interval_hours)
        from apps.core.services.herb_evidence import batch_herb_component_evidence
        query = batch_herb_component_evidence(query_type="herb", queries=["黄连"])["results"][0]
        self.assertEqual(len(query["compounds"]), 1)
        self.assertEqual(len(query["targets"]), 1)
        self.assertEqual(len(query["relations"]), 3)  # one structure, both target rows
        self.assertEqual(EvidenceRelation.objects.count(), 4)  # no raw evidence deleted

    def test_exact_pubchem_is_shared_names_and_unknown_species_are_not(self):
        self.workbook("batman", [self.batman()])
        self.workbook("hit", [{"Herb ID": "H1", "Chinese Character": "黄连", "Compound Id": "C1",
            "Compound Name": "槲皮素", "Pubchem ID": "CID:5280343", "Chembl ID": "CHEMBL50",
            "Target ID": "T1", "Protein Name": "Cellular tumor antigen p53", "Symbol": "TP53", "Uniprot": "P04637"}])
        for slug in ("batman", "hit"):
            import_workbook(self.directory.name, slug, apply=True)
        self.assertEqual(KnowledgeEntity.objects.filter(entity_type="compound").count(), 1)
        self.assertEqual(KnowledgeEntity.objects.filter(entity_type="herb").count(), 2)
        self.assertEqual(set(KnowledgeEntity.objects.filter(entity_type__in=["gene", "protein"]).values_list("taxon_key", flat=True)), {"unknown"})
        self.assertEqual(CanonicalIdentifier.objects.get(namespace="pubchem").entity_id,
            CanonicalIdentifier.objects.get(namespace="chembl-compound").entity_id)
        from apps.core.services.catalog_identity import exact_entity_queryset
        self.assertEqual(exact_entity_queryset("compound", "槲皮素").get().pk,
            exact_entity_queryset("compound", "Quercetin").get().pk)

    def test_disease_triple_context_survives_and_names_are_proteins(self):
        self.workbook("disease-herb", [{"疾病": "Alzheimer's Disease", "中药": "黄连", "靶点基因": "Muscarinic acetylcholine receptor M1"}])
        result = import_workbook(self.directory.name, "disease-herb", apply=True)
        self.assertEqual(result["relations"], 3)
        target = KnowledgeEntity.objects.get(entity_type="protein")
        self.assertEqual(target.taxon_key, "unknown")
        edge = EvidenceRelation.objects.get(relation_type="disease_herb_target")
        self.assertEqual(edge.metadata["herbStableId"], KnowledgeEntity.objects.get(entity_type="herb").stable_id)
        self.assertEqual(edge.metadata["diseaseStableId"], edge.subject.stable_id)
        self.assertFalse(EvidenceRelation.objects.filter(relation_type="disease_target").exists())

    def test_missing_endpoint_is_quarantined_without_fake_target(self):
        self.workbook("disease-targets", [{"疾病": "Disease", "靶点基因": None, "来源文件": "input.xlsx"}])
        result = import_workbook(self.directory.name, "disease-targets", apply=True)
        self.assertEqual(result["quarantined"], 1)
        self.assertEqual(SourceRecord.objects.get().payload["靶点基因"], None)
        self.assertEqual(EvidenceRelation.objects.count(), 0)

    def test_failed_stage_invisible_and_can_resume(self):
        self.workbook("batman", [self.batman()])
        with patch("apps.sources.workbook_import._publish", side_effect=ValidationError("audit failure")):
            with self.assertRaises(ValidationError):
                import_workbook(self.directory.name, "batman", apply=True)
        self.assertFalse(DataSource.objects.get(slug="batman").enabled)
        self.assertFalse(KnowledgeEntity.objects.filter(is_active=True).exists())
        self.assertFalse(EvidenceRelation.objects.filter(is_active=True).exists())
        self.assertEqual(import_workbook(self.directory.name, "batman", apply=True)["state"], "published")
        self.assertEqual(SourceRecord.objects.count(), 1)

    def test_new_version_retires_edges_only_after_complete_audit(self):
        self.workbook("batman", [self.batman()])
        import_workbook(self.directory.name, "batman", apply=True)
        old_edge = EvidenceRelation.objects.first()
        old_uuid = old_edge.object.canonical_id
        self.workbook("batman", [self.batman(Score=4.5)])
        with patch("apps.sources.workbook_import._publish", side_effect=ValidationError("blocked")):
            with self.assertRaises(ValidationError):
                import_workbook(self.directory.name, "batman", apply=True)
        old_edge.refresh_from_db()
        self.assertTrue(old_edge.is_active)
        import_workbook(self.directory.name, "batman", apply=True)
        old_edge.refresh_from_db()
        self.assertFalse(old_edge.is_active)
        self.assertEqual(old_edge.object.canonical_id, old_uuid)
        self.assertEqual(SourceRecord.objects.count(), 2)
        self.assertEqual(EvidenceRelation.objects.filter(is_active=True).count(), 2)

    def test_bad_header_fails_before_any_release(self):
        self.workbook("batman", [])
        book = Workbook()
        book.active.append(["wrong"])
        book.save(Path(self.directory.name) / SOURCES["batman"].filename)
        book.close()
        with self.assertRaises(ValueError):
            import_workbook(self.directory.name, "batman", apply=True)
        self.assertFalse(SourceRelease.objects.exists())

    def test_similarity_score_never_masquerades_as_activity(self):
        row = normalize_row("tcmip", {"中药": "艾叶", "成分名称": "bornyl acetate", "靶标": "HSD11B1", "相似得分": 0.967, "Activity": "IC50:994", "参考文献": "source"})
        edge = row.relations[1]
        self.assertEqual(edge.metadata["score_kind"], "similarity_not_activity")
        self.assertEqual(edge.evidence_text, "IC50:994")

    def test_selected_herb_context_is_not_lost_to_disease_row_cap(self):
        self.workbook("disease-herb", [
            {"疾病": "Disease", "中药": "其他药", "靶点基因": "GENE1"},
            {"疾病": "Disease", "中药": "黄连", "靶点基因": "GENE2"},
        ])
        import_workbook(self.directory.name, "disease-herb", apply=True)
        from apps.core.services.network_pharmacology import build_network_pharmacology
        result = build_network_pharmacology(user=None, herb_query="黄连",
            disease_query="Disease", row_limit=1, persist=False)
        self.assertEqual(result["summary"]["directAssociationTargetCount"], 1)
        self.assertEqual(result["raw"]["directDiseaseHerbLinks"][0]["target"], "GENE2")
        self.assertTrue(result["rawLimits"]["inputRelationsTruncated"]["diseaseTargets"])
