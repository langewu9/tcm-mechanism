from io import BytesIO
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from openpyxl import Workbook

from apps.core.models import (
    AnalysisTask,
    DataSource,
    EvidenceRelation,
    KnowledgeEntity,
    ResearchDataset,
    SourceRelease,
)
from apps.proteomics.models import ProteomicsRowResult
from apps.proteomics.integrations import run_opt_in_reactome
from apps.proteomics.services import (
    ProteomicsInputError,
    parse_dataset_table,
    resolve_mapping,
    run_proteomics_analysis,
)
from apps.proteomics.tasks import run_proteomics_task


class ProteomicsServiceTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_dir.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

        self.owner = get_user_model().objects.create_user(
            username="proteomics-researcher", password="test-password-123"
        )
        self.csv_bytes = (
            "Gene Symbol,Protein name,log2FC,FDR,pvalue\n"
            "TP53,P53,2,0.01,0.02\n"
            "IL6,Interleukin 6,0.2,0.01,0.02\n"
            'Unknown label,"Other, protein",3,0.01,0.02\n'
            "NOVEL1,Novel protein,2,0.03,0.04\n"
            "BAD,Invalid value,not-a-number,0.01,0.02\n"
            ",,2,0.01,0.02\n"
        ).encode("utf-8")
        self.dataset = self.make_dataset("pilot.csv", self.csv_bytes)
        self.task = AnalysisTask.objects.create(
            owner=self.owner,
            task_type=AnalysisTask.TaskType.PROTEOMICS,
            dataset=self.dataset,
            input_parameters={
                "mapping": {},
                "thresholds": {"log2FcMin": 1.0, "fdrMax": 0.05, "pValueMax": 0.05},
                "referenceTargets": ["tp53", "IL6"],
            },
        )
        source = DataSource.objects.create(
            slug="test-pathways",
            name="Test pathways",
            access_mode=DataSource.AccessMode.MANUAL,
        )
        self.release = SourceRelease.objects.create(source=source, version="test-v1")
        self.tp53 = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.GENE,
            stable_id="TP53",
            label="TP53",
            source_release=self.release,
            synonyms=["P53"],
            metadata={"source": "test-gene-catalog"},
        )
        self.pathway = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.PATHWAY,
            stable_id="R-HSA-TP53",
            label="TP53 regulation",
        )
        EvidenceRelation.objects.create(
            source_release=self.release,
            source_record_id="tp53-pathway-1",
            subject=self.tp53,
            object=self.pathway,
            relation_type="gene_pathway",
            evidence_type="curated",
            score=0.95,
        )

    def make_dataset(self, filename, content):
        key = default_storage.save(
            f"research-datasets/{self.owner.pk}/{filename}", ContentFile(content)
        )
        return ResearchDataset.objects.create(
            owner=self.owner,
            name="Pilot differential proteins",
            original_filename=filename,
            storage_key=key,
            content_sha256="abc123",
            byte_size=len(content),
        )

    def test_csv_parser_preserves_quoted_values_and_resolves_legacy_aliases(self):
        table = parse_dataset_table(self.dataset.storage_key, self.dataset.original_filename)
        mapping = resolve_mapping(table.columns, {})

        self.assertEqual(table.columns[0], "Gene Symbol")
        self.assertEqual(table.rows[2]["Protein name"], "Other, protein")
        self.assertEqual(mapping.gene_column, "Gene Symbol")
        self.assertEqual(mapping.log2fc_column, "log2FC")
        self.assertEqual(mapping.p_value_column, "pvalue")
        self.assertEqual(mapping.fdr_column, "FDR")

    def test_xlsx_parser_reads_first_sheet_and_rejects_missing_columns(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Differential results"
        sheet.append(["Gene", "log2FC", "FDR"])
        sheet.append(["TP53", 2.0, 0.01])
        stream = BytesIO()
        workbook.save(stream)
        dataset = self.make_dataset("pilot.xlsx", stream.getvalue())

        table = parse_dataset_table(dataset.storage_key, dataset.original_filename)
        mapping = resolve_mapping(table.columns, {})
        self.assertEqual(table.sheet_name, "Differential results")
        self.assertEqual(mapping.gene_column, "Gene")
        self.assertEqual(table.rows[0]["log2FC"], "2")
        with self.assertRaises(ProteomicsInputError):
            resolve_mapping(table.columns, {"gene_column": "not-a-column"})

    def test_analysis_matches_main_business_flow_and_adds_row_level_qc(self):
        result, stored_rows, release_ids = run_proteomics_analysis(self.task)

        self.assertEqual(result["summary"]["selectedRowCount"], 3)
        self.assertEqual(result["summary"]["normalizedCount"], 2)
        self.assertEqual(result["summary"]["candidateOverlapCount"], 1)
        self.assertEqual(result["validation"]["overlap"], ["TP53"])
        self.assertEqual(result["validation"]["referenceOnly"], ["IL6"])
        self.assertEqual(result["pathways"][0]["name"], "TP53 regulation")
        self.assertEqual(result["network"]["links"][0]["sourceVersion"], "test-v1")
        self.assertEqual(result["qc"]["missingIdentifierCount"], 1)
        self.assertEqual(result["qc"]["invalidNumericValueRowCount"], 1)
        self.assertEqual(result["qc"]["excludedRowCount"], 3)
        self.assertEqual(len(stored_rows), 6)
        self.assertEqual(sum(row.selected for row in stored_rows), 3)
        self.assertIn(self.release.pk, release_ids)
        self.assertEqual(result["rows"][0]["mappingSource"], "test-pathways:test-v1")
        self.assertEqual(result["dataset"]["sha256"], "abc123")
        self.assertTrue(any("符号格式" in warning for warning in result["warnings"]))

    def test_celery_task_persists_results_and_is_idempotent(self):
        with patch("apps.proteomics.tasks.run_opt_in_reactome") as external_analysis:
            outcome = run_proteomics_task.run(self.task.pk)
        external_analysis.assert_not_called()

        self.task.refresh_from_db()
        self.assertEqual(outcome["status"], AnalysisTask.Status.SUCCEEDED)
        self.assertEqual(self.task.status, AnalysisTask.Status.SUCCEEDED)
        self.assertEqual(self.task.progress, 100)
        self.assertEqual(self.task.result["algorithmVersion"], "proteomics-py-1.1")
        self.assertEqual(ProteomicsRowResult.objects.filter(task=self.task).count(), 6)
        self.assertEqual(list(self.task.source_releases.values_list("id", flat=True)), [self.release.pk])
        self.assertEqual(run_proteomics_task.run(self.task.pk)["status"], "skipped")

    def test_opt_in_external_analysis_records_gene_mapping_and_reactome_release(self):
        result, row_results, _release_ids = run_proteomics_analysis(self.task)
        mapping_response = {
            "mappings": [{"query": "Unknown label", "symbol": "MAPK1", "name": "ERK2", "entrezGeneId": "5594"}],
            "ambiguous": [],
            "unmapped": [],
            "rejected": [],
            "truncatedCount": 0,
            "rejectedCount": 0,
        }
        reactome_response = {
            "sourceVersion": "94",
            "token": "test-token",
            "identifiersNotFound": 0,
            "pathwaysFound": 1,
            "submittedIdentifierCount": 3,
            "truncatedIdentifierCount": 0,
            "rejectedIdentifierCount": 0,
            "pathways": [{
                "stableId": "R-HSA-5673001",
                "name": "RAF/MAP kinase cascade",
                "species": "Homo sapiens",
                "matchedEntities": 2,
                "totalEntities": 30,
                "coverage": 0.06,
                "pValue": 0.001,
                "fdr": 0.02,
            }],
        }
        with patch("apps.proteomics.integrations.resolve_human_identifiers", return_value=mapping_response), patch(
            "apps.proteomics.integrations.analyze_reactome_human_pathways", return_value=reactome_response
        ):
            release_ids, warnings = run_opt_in_reactome(self.task, result, row_results)

        external_row = next(row for row in row_results if row.original_label == "Unknown label")
        self.assertEqual(external_row.mapping_status, ProteomicsRowResult.MappingStatus.EXTERNAL)
        self.assertEqual(external_row.normalized_symbol, "MAPK1")
        self.assertEqual(result["externalReactome"]["pathways"][0]["stableId"], "R-HSA-5673001")
        self.assertEqual(result["summary"]["enrichmentMode"], "LOCAL+REACTOME")
        self.assertEqual(len(release_ids), 2)
        self.assertEqual(list(SourceRelease.objects.filter(pk__in=release_ids).values_list("source__slug", flat=True)), ["mygene-info", "reactome"])
        self.assertEqual(warnings, [])
