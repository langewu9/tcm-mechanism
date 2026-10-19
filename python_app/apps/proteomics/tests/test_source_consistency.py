"""Scientific identifiers must retain the same source visibility and meaning."""
import csv
import io
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from apps.core.models import AnalysisTask, DataSource, EntityIdentifier, EvidenceRelation, KnowledgeEntity, ResearchDataset, SourceRelease
from apps.proteomics.models import ProteomicsRowResult
from apps.proteomics.services import run_proteomics_analysis


class ProteomicsSourceConsistencyTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = override_settings(MEDIA_ROOT=directory.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.user = get_user_model().objects.create_user(username="source-consistency")
        self.source = DataSource.objects.create(slug="enabled-local", name="Enabled local", enabled=True)
        self.release = SourceRelease.objects.create(source=self.source, version="local-v1")
        self.disabled = DataSource.objects.create(slug="disabled-local", name="Disabled local", enabled=False)
        self.disabled_release = SourceRelease.objects.create(source=self.disabled, version="disabled-v1")

    def entity(self, label="TP53", *, release=None, metadata=None):
        return KnowledgeEntity.objects.create(entity_type="protein", stable_id=f"fixture:{label}", label=label,
                                              source_release=release or self.release, metadata=metadata or {"symbol": "TP53"})

    def analyze(self, label, *, selected=True):
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Gene", "log2FC", "PValue", "FDR"])
        writer.writerow([label, 2 if selected else 0.2, 0.001, 0.01])
        content = output.getvalue().encode()
        key = default_storage.save("source-consistency/input.csv", ContentFile(content))
        dataset = ResearchDataset.objects.create(owner=self.user, name="SYNTHETIC source checks",
                                                 original_filename="input.csv", storage_key=key, byte_size=len(content))
        task = AnalysisTask.objects.create(owner=self.user, dataset=dataset, task_type="proteomics", input_parameters={
            "thresholds": {"log2FcMin": 1, "pValueMax": 0.05, "fdrMax": 0.05}})
        return run_proteomics_analysis(task)

    def test_disabled_entity_source_cannot_be_counted_as_database_mapping(self):
        self.entity(release=self.disabled_release)
        result, rows, releases = self.analyze("TP53")
        self.assertEqual(result["summary"]["databaseMappedCount"], 0)
        self.assertEqual(rows[0].mapping_status, ProteomicsRowResult.MappingStatus.UNVERIFIED)
        self.assertIsNone(rows[0].matched_entity)
        self.assertNotIn(self.disabled_release.pk, releases)

    def test_disabled_identifier_source_is_not_used_as_an_alias_or_exported(self):
        entity = self.entity()
        EntityIdentifier.objects.create(entity=entity, source_release=self.disabled_release,
                                        namespace="uniprot", identifier="P04637")
        result, rows, _ = self.analyze("P04637")
        self.assertEqual(result["summary"]["databaseMappedCount"], 0)
        self.assertIsNone(rows[0].matched_entity)
        _, mapped_rows, _ = self.analyze("TP53")
        self.assertNotIn("P04637", {item["identifier"] for item in mapped_rows[0].external_identifiers})

    def test_disabled_relation_source_does_not_reappear_as_pathway_evidence(self):
        entity = self.entity()
        pathway = KnowledgeEntity.objects.create(entity_type="pathway", stable_id="fixture:pathway", label="Synthetic pathway")
        EvidenceRelation.objects.create(subject=entity, object=pathway, source_release=self.disabled_release,
                                        source_record_id="disabled-edge", relation_type="gene_pathway", evidence_type="synthetic")
        result, _, releases = self.analyze("TP53")
        self.assertEqual(result["summary"]["pathwayCount"], 0)
        self.assertEqual(result["network"]["links"], [])
        self.assertNotIn(self.disabled_release.pk, releases)

    def test_disabled_pathway_entity_source_does_not_reappear_through_an_enabled_edge(self):
        entity = self.entity()
        pathway = KnowledgeEntity.objects.create(entity_type="pathway", stable_id="fixture:pathway", label="Synthetic pathway", source_release=self.disabled_release)
        EvidenceRelation.objects.create(subject=entity, object=pathway, source_release=self.release,
                                        source_record_id="enabled-edge", relation_type="gene_pathway", evidence_type="synthetic")
        result, _, _ = self.analyze("TP53")
        self.assertEqual(result["summary"]["pathwayCount"], 0)
        self.assertEqual(result["network"]["links"], [])

    def test_historical_protein_name_is_traceable_but_not_a_verified_gene_symbol(self):
        label = "2-hydroxy-6-oxo-7-methylocta-2,4-dienoate hydrolase"
        entity = self.entity(label, metadata={"sourceKind": "target", "identifierStatus": "name_only"})
        result, rows, releases = self.analyze(label)
        self.assertEqual(rows[0].matched_entity, entity)
        self.assertEqual(rows[0].normalized_symbol, "")
        self.assertEqual(rows[0].mapping_status, ProteomicsRowResult.MappingStatus.UNMAPPED)
        self.assertEqual(result["summary"]["databaseMappedCount"], 0)
        self.assertEqual(result["summary"]["normalizedCount"], 0)
        self.assertEqual(result["unmapped"], [label])
        self.assertIn(self.release.pk, releases)
        self.assertTrue(rows[0].qc_warnings)

    def test_symbol_shaped_historical_value_remains_unverified(self):
        self.entity(metadata={"sourceKind": "target", "identifierStatus": "unverified_symbol", "symbol": "TP53"})
        result, rows, _ = self.analyze("TP53")
        self.assertEqual(rows[0].mapping_status, ProteomicsRowResult.MappingStatus.UNVERIFIED)
        self.assertEqual(rows[0].normalized_symbol, "TP53")
        self.assertEqual(result["summary"]["databaseMappedCount"], 0)
        self.assertEqual(result["summary"]["unverifiedSymbolCount"], 1)

    def test_every_exported_active_identifier_release_is_retained_in_task_provenance(self):
        entity = self.entity()
        source = DataSource.objects.create(slug="enabled-identifiers", name="Enabled identifier source")
        release = SourceRelease.objects.create(source=source, version="identifier-v2")
        EntityIdentifier.objects.create(entity=entity, source_release=release, namespace="uniprot", identifier="P04637")
        _, rows, releases = self.analyze("P04637")
        self.assertEqual(rows[0].mapping_status, ProteomicsRowResult.MappingStatus.DATABASE)
        self.assertIn(release.pk, releases)

    def test_unselected_rows_keep_the_provenance_of_their_exported_identifiers(self):
        entity = self.entity()
        source = DataSource.objects.create(slug="enabled-identifiers", name="Enabled identifier source")
        release = SourceRelease.objects.create(source=source, version="identifier-v2")
        EntityIdentifier.objects.create(entity=entity, source_release=release, namespace="uniprot", identifier="P04637")
        result, rows, releases = self.analyze("P04637", selected=False)
        self.assertFalse(rows[0].selected)
        self.assertEqual(result["summary"]["selectedRowCount"], 0)
        self.assertTrue(rows[0].external_identifiers)
        self.assertIn(self.release.pk, releases)
        self.assertIn(release.pk, releases)
