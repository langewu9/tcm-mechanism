from io import BytesIO
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from django.utils import timezone
from openpyxl import Workbook

from apps.core.models import (
    AnalysisTask,
    DataSource,
    EntityIdentifier,
    EvidenceRelation,
    KnowledgeEntity,
    ResearchDataset,
    SourceRelease,
)
from apps.proteomics.models import ProteomicsRowResult
from apps.proteomics.integrations import (
    run_opt_in_gprofiler,
    run_opt_in_reactome,
    run_opt_in_string,
)
from apps.proteomics.external_gprofiler import GProfilerError
from apps.proteomics.services import (
    ProteomicsInputError,
    parse_dataset_table,
    resolve_mapping,
    run_proteomics_analysis,
)
from apps.proteomics.raw_matrix import analyze_raw_matrix
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
        identifier_release = SourceRelease.objects.create(
            source=DataSource.objects.create(
                slug="test-uniprot",
                name="UniProt test snapshot",
                access_mode=DataSource.AccessMode.MANUAL,
            ),
            version="2026-01",
        )
        EntityIdentifier.objects.create(
            entity=self.tp53,
            source_release=identifier_release,
            namespace="uniprot",
            identifier="P04637",
        )
        result, stored_rows, release_ids = run_proteomics_analysis(self.task)

        self.assertEqual(result["summary"]["selectedRowCount"], 3)
        self.assertEqual(result["summary"]["normalizedCount"], 2)
        self.assertEqual(result["summary"]["candidateOverlapCount"], 1)
        self.assertEqual(result["validation"]["overlap"], ["TP53"])
        self.assertEqual(result["validation"]["referenceOnly"], ["IL6"])
        self.assertEqual(result["pathways"][0]["name"], "TP53 regulation")
        tp53_row = next(row for row in stored_rows if row.original_label == "TP53")
        self.assertEqual(
            {(item["namespace"], item["identifier"], item["sourceVersion"]) for item in tp53_row.external_identifiers},
            {("platform_entity", "TP53", "test-v1"), ("uniprot", "P04637", "2026-01")},
        )
        self.assertEqual(result["summary"]["stableIdentifierCount"], 2)
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

    def test_raw_matrix_uses_explicit_design_welch_test_and_bh_fdr(self):
        content = (
            "Gene Symbol,Control_1,Control_2,Control_3,Treatment_1,Treatment_2,Treatment_3\n"
            "TP53,8,9,8,64,72,64\n"
            "IL6,4,5,4,4,5,4\n"
            "MISSING,6,7,,48,56,48\n"
            "BAD,0,7,8,48,56,48\n"
        ).encode()
        dataset = self.make_dataset("raw-matrix.csv", content)
        task = AnalysisTask.objects.create(
            owner=self.owner,
            task_type=AnalysisTask.TaskType.PROTEOMICS,
            dataset=dataset,
            input_parameters={
                "analysisMode": "raw_matrix",
                "matrixDesign": {
                    "identifierColumn": "Gene Symbol",
                    "sampleColumns": ["Control_1", "Control_2", "Control_3", "Treatment_1", "Treatment_2", "Treatment_3"],
                    "controlSamples": ["Control_1", "Control_2", "Control_3"],
                    "treatmentSamples": ["Treatment_1", "Treatment_2", "Treatment_3"],
                    "valuesAreLog2": False,
                    "normalization": "none",
                    "missingPolicy": "complete_rows",
                },
                "thresholds": {"log2FcMin": 1.0, "fdrMax": 0.05, "pValueMax": 0.05},
                "referenceTargets": [],
            },
        )

        result, stored_rows, release_ids = run_proteomics_analysis(task)

        self.assertEqual(result["differentialAnalysis"]["test"], "Welch two-sample t-test (unpaired)")
        self.assertEqual(result["differentialAnalysis"]["pValueAdjustment"], "Benjamini-Hochberg FDR")
        self.assertEqual(result["differentialAnalysis"]["controlSamples"], ["Control_1", "Control_2", "Control_3"])
        self.assertEqual(result["qc"]["rawMatrix"]["rowsTested"], 2)
        self.assertEqual(result["qc"]["rawMatrix"]["missingSampleValueCount"], 1)
        self.assertEqual(result["qc"]["rawMatrix"]["invalidSampleValueCount"], 1)
        tp53 = next(row for row in stored_rows if row.original_label == "TP53")
        self.assertAlmostEqual(tp53.log2_fold_change, 3.0, places=6)
        self.assertLess(tp53.p_value, 0.05)
        self.assertLessEqual(tp53.fdr, 0.05)
        self.assertTrue(tp53.selected)
        incomplete = next(row for row in stored_rows if row.original_label == "MISSING")
        self.assertIn("incomplete_samples", incomplete.exclusion_reasons)
        invalid = next(row for row in stored_rows if row.original_label == "BAD")
        self.assertIn("invalid_sample_values", invalid.exclusion_reasons)
        self.assertTrue(any("非配对 Welch" in warning for warning in result["warnings"]))
        self.assertIn(self.release.pk, release_ids)

    def test_raw_matrix_available_replicates_policy_is_explicit_and_does_not_impute(self):
        from apps.proteomics.raw_matrix import analyze_raw_matrix

        rows = [
            {"ID": "TP53", "C1": "8", "C2": "9", "C3": "8", "T1": "64", "T2": "72", "T3": ""},
            {"ID": "IL6", "C1": "4", "C2": "5", "C3": "4", "T1": "4", "T2": "5", "T3": "4"},
        ]
        design = {
            "identifierColumn": "ID",
            "sampleColumns": ["C1", "C2", "C3", "T1", "T2", "T3"],
            "controlSamples": ["C1", "C2", "C3"],
            "treatmentSamples": ["T1", "T2", "T3"],
            "valuesAreLog2": False,
            "normalization": "median_center",
            "missingPolicy": "available_replicates",
        }
        synthetic, exclusions, details, warnings = analyze_raw_matrix(rows, design)

        self.assertEqual(exclusions, {})
        self.assertNotEqual(synthetic[0]["__log2fc"], "")
        self.assertEqual(details["qc"]["rowsTested"], 2)
        self.assertEqual(details["qc"]["missingSampleValueCount"], 1)
        self.assertEqual(details["rowWarnings"][0], ["missing_sample_values"])
        self.assertTrue(any("未执行数值填补" in warning for warning in warnings))

    def test_raw_matrix_non_estimable_zero_variance_row_is_excluded(self):
        from apps.proteomics.raw_matrix import analyze_raw_matrix

        rows = [{"ID": "TP53", "C1": "1", "C2": "1", "T1": "5", "T2": "5"}]
        design = {
            "identifierColumn": "ID",
            "sampleColumns": ["C1", "C2", "T1", "T2"],
            "controlSamples": ["C1", "C2"],
            "treatmentSamples": ["T1", "T2"],
            "valuesAreLog2": True,
            "normalization": "none",
            "missingPolicy": "complete_rows",
        }

        synthetic, exclusions, details, _warnings = analyze_raw_matrix(rows, design)

        self.assertEqual(exclusions, {0: ["test_not_estimable"]})
        self.assertEqual(synthetic[0]["__pvalue"], "")
        self.assertEqual(details["qc"]["rowsTested"], 0)

    def test_raw_matrix_paired_test_uses_explicit_sample_pairs(self):
        content = (
            "Gene,C1,T1,C2,T2,C3,T3\n"
            "TP53,8,16,8,32,8,64\n"
            "IL6,8,16,8,16,8,16\n"
            "PARTIAL,8,16,8,,8,64\n"
        ).encode()
        dataset = self.make_dataset("paired-matrix.csv", content)
        sample_pairs = [
            {"pairId": "subject-1", "controlSample": "C1", "treatmentSample": "T1"},
            {"pairId": "subject-2", "controlSample": "C2", "treatmentSample": "T2"},
            {"pairId": "subject-3", "controlSample": "C3", "treatmentSample": "T3"},
        ]
        task = AnalysisTask.objects.create(
            owner=self.owner,
            task_type=AnalysisTask.TaskType.PROTEOMICS,
            dataset=dataset,
            input_parameters={
                "analysisMode": "raw_matrix",
                "matrixDesign": {
                    "identifierColumn": "Gene",
                    "sampleColumns": ["C1", "T1", "C2", "T2", "C3", "T3"],
                    "designType": "paired",
                    "controlSamples": ["C1", "C2", "C3"],
                    "treatmentSamples": ["T1", "T2", "T3"],
                    "samplePairs": sample_pairs,
                    "valuesAreLog2": False,
                    "normalization": "none",
                    "missingPolicy": "complete_rows",
                },
                "thresholds": {"log2FcMin": 0, "fdrMax": 1, "pValueMax": 1},
                "referenceTargets": [],
            },
        )

        result, stored_rows, _release_ids = run_proteomics_analysis(task)

        self.assertEqual(result["differentialAnalysis"]["designType"], "paired")
        self.assertEqual(result["differentialAnalysis"]["test"], "paired two-sample t-test")
        self.assertEqual(result["differentialAnalysis"]["samplePairs"], sample_pairs)
        self.assertEqual(result["qc"]["rawMatrix"]["pairCount"], 3)
        tp53 = next(row for row in stored_rows if row.original_label == "TP53")
        self.assertAlmostEqual(tp53.log2_fold_change, 2.0, places=6)
        self.assertIsNotNone(tp53.p_value)
        self.assertTrue(tp53.selected)
        il6 = next(row for row in stored_rows if row.original_label == "IL6")
        self.assertIn("test_not_estimable", il6.exclusion_reasons)
        partial = next(row for row in stored_rows if row.original_label == "PARTIAL")
        self.assertIn("incomplete_samples", partial.exclusion_reasons)

    def test_raw_matrix_multifactor_model_adjusts_for_batch_and_records_contrast(self):
        sample_columns = ["C_A1", "C_A2", "C_B1", "C_B2", "D_A1", "D_A2", "D_B1", "D_B2"]
        factors = {
            "C_A1": {"condition": "control", "batch": "A"},
            "C_A2": {"condition": "control", "batch": "A"},
            "C_B1": {"condition": "control", "batch": "B"},
            "C_B2": {"condition": "control", "batch": "B"},
            "D_A1": {"condition": "drug", "batch": "A"},
            "D_A2": {"condition": "drug", "batch": "A"},
            "D_B1": {"condition": "drug", "batch": "B"},
            "D_B2": {"condition": "drug", "batch": "B"},
        }
        assignments = [
            {"sampleColumn": sample, "factors": factors[sample]}
            for sample in sample_columns
        ]
        design = {
            "identifierColumn": "Gene",
            "sampleColumns": sample_columns,
            "designType": "multifactor",
            "sampleFactors": assignments,
            "contrastFactor": "condition",
            "referenceLevel": "control",
            "treatmentLevel": "drug",
            "valuesAreLog2": True,
            "normalization": "none",
            "missingPolicy": "complete_rows",
        }
        rows = [{"Gene": "TP53", **dict(zip(sample_columns, [10, 10.2, 12, 12.4, 11.2, 11.5, 13.2, 13.5]))}]
        _synthetic, exclusions, details, warnings = analyze_raw_matrix(rows, design)
        self.assertEqual(exclusions, {})
        self.assertEqual(details["method"]["test"], "additive multifactor linear-model contrast t-test")
        self.assertEqual(details["method"]["contrast"], {
            "factor": "condition", "referenceLevel": "control", "treatmentLevel": "drug",
        })
        self.assertAlmostEqual(details["qc"]["modelResidualDegreesOfFreedom"], 5)
        self.assertIn("未拟合因素交互项", warnings[0])
        partial_design = {**design, "missingPolicy": "available_replicates"}
        partial_row = {
            "Gene": "PARTIAL",
            **dict(zip(sample_columns, ["10", "10.2", "", "", "", "", "13.2", "13.5"])),
        }
        _partial_rows, partial_exclusions, _partial_details, _partial_warnings = analyze_raw_matrix(
            [partial_row], partial_design,
        )
        self.assertEqual(partial_exclusions, {0: ["rank_deficient_sample_design"]})

        dataset = self.make_dataset(
            "multifactor-matrix.csv",
            ("Gene," + ",".join(sample_columns) + "\nTP53,10,10.2,12,12.4,11.2,11.5,13.2,13.5\n").encode(),
        )
        task = AnalysisTask.objects.create(
            owner=self.owner,
            task_type=AnalysisTask.TaskType.PROTEOMICS,
            dataset=dataset,
            input_parameters={
                "analysisMode": "raw_matrix",
                "matrixDesign": design,
                "thresholds": {"log2FcMin": 0, "fdrMax": 1, "pValueMax": 1},
                "referenceTargets": [],
            },
        )
        result, stored_rows, _release_ids = run_proteomics_analysis(task)
        self.assertAlmostEqual(stored_rows[0].log2_fold_change, 1.2, places=6)
        self.assertIsNotNone(stored_rows[0].p_value)
        self.assertEqual(result["differentialAnalysis"]["sampleFactors"], assignments)
        self.assertEqual(result["qc"]["rawMatrix"]["factorCount"], 2)

    def test_raw_matrix_multifactor_rejects_fully_confounded_design(self):
        sample_columns = ["C1", "C2", "D1", "D2"]
        factors = {
            "C1": {"condition": "control", "batch": "A"},
            "C2": {"condition": "control", "batch": "A"},
            "D1": {"condition": "drug", "batch": "B"},
            "D2": {"condition": "drug", "batch": "B"},
        }
        design = {
            "identifierColumn": "Gene",
            "sampleColumns": sample_columns,
            "designType": "multifactor",
            "sampleFactors": [{"sampleColumn": sample, "factors": factors[sample]} for sample in sample_columns],
            "contrastFactor": "condition",
            "referenceLevel": "control",
            "treatmentLevel": "drug",
            "valuesAreLog2": True,
            "normalization": "none",
            "missingPolicy": "complete_rows",
        }
        with self.assertRaisesRegex(ProteomicsInputError, "完全共线"):
            analyze_raw_matrix([{"Gene": "TP53", "C1": "8", "C2": "9", "D1": "10", "D2": "11"}], design)

    def test_raw_matrix_multifactor_rejects_factor_names_that_collide_after_trimming(self):
        sample_columns = ["C1", "C2", "D1", "D2"]
        assignments = [
            {"sampleColumn": sample, "factors": {"condition": level, " condition ": level, "batch": batch}}
            for sample, level, batch in (
                ("C1", "control", "A"), ("C2", "control", "B"),
                ("D1", "drug", "A"), ("D2", "drug", "B"),
            )
        ]
        design = {
            "identifierColumn": "Gene",
            "sampleColumns": sample_columns,
            "designType": "multifactor",
            "sampleFactors": assignments,
            "contrastFactor": "condition",
            "referenceLevel": "control",
            "treatmentLevel": "drug",
            "valuesAreLog2": True,
            "normalization": "none",
            "missingPolicy": "complete_rows",
        }
        with self.assertRaisesRegex(ProteomicsInputError, "去除首尾空格后也不能重复"):
            analyze_raw_matrix([{"Gene": "TP53", "C1": "8", "C2": "9", "D1": "10", "D2": "11"}], design)

    def test_analysis_succeeds_with_zero_significant_rows_and_preserves_qc(self):
        content = (
            "Gene,Control_1,Control_2,Treatment_1,Treatment_2\n"
            "TP53,8,9,64,72\n"
            "IL6,4,5,4,5\n"
        ).encode()
        dataset = self.make_dataset("no-hits.csv", content)
        task = AnalysisTask.objects.create(
            owner=self.owner,
            task_type=AnalysisTask.TaskType.PROTEOMICS,
            dataset=dataset,
            input_parameters={
                "analysisMode": "raw_matrix",
                "matrixDesign": {
                    "identifierColumn": "Gene",
                    "sampleColumns": ["Control_1", "Control_2", "Treatment_1", "Treatment_2"],
                    "controlSamples": ["Control_1", "Control_2"],
                    "treatmentSamples": ["Treatment_1", "Treatment_2"],
                    "valuesAreLog2": False,
                    "normalization": "none",
                    "missingPolicy": "complete_rows",
                },
                "thresholds": {"log2FcMin": 99.0, "fdrMax": 0.05, "pValueMax": 0.05},
                "referenceTargets": [],
            },
        )

        result, stored_rows, release_ids = run_proteomics_analysis(task)

        self.assertEqual(result["summary"]["selectedRowCount"], 0)
        self.assertEqual(result["qc"]["rawMatrix"]["rowsTested"], 2)
        self.assertEqual(len(stored_rows), 2)
        self.assertTrue(all(not row.selected for row in stored_rows))
        # Full row exports keep mapping provenance even when no row passes the
        # differential thresholds; this does not create a pathway result.
        self.assertEqual(release_ids, [self.release.pk])

    def test_celery_task_persists_results_and_is_idempotent(self):
        with patch("apps.proteomics.tasks.run_opt_in_reactome") as external_analysis, patch(
            "apps.proteomics.tasks.run_opt_in_string"
        ) as string_analysis, patch(
            "apps.proteomics.tasks.run_opt_in_gprofiler"
        ) as gprofiler_analysis:
            outcome = run_proteomics_task.run(self.task.pk)
        external_analysis.assert_not_called()
        string_analysis.assert_not_called()
        gprofiler_analysis.assert_not_called()

        self.task.refresh_from_db()
        self.assertEqual(outcome["status"], AnalysisTask.Status.SUCCEEDED)
        self.assertEqual(self.task.status, AnalysisTask.Status.SUCCEEDED)
        self.assertEqual(self.task.progress, 100)
        self.assertEqual(self.task.result["algorithmVersion"], "proteomics-py-1.8")
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
        self.assertEqual(
            next(item["identifier"] for item in external_row.external_identifiers if item["namespace"] == "entrezgene"),
            "5594",
        )
        entrez_id = next(item for item in external_row.external_identifiers if item["namespace"] == "entrezgene")
        self.assertEqual(entrez_id["source"], "mygene-info")
        self.assertEqual(entrez_id["sourceVersion"], f"captured-{timezone.localdate().isoformat()}")
        self.assertIsNotNone(entrez_id["sourceReleaseId"])
        preview_row = next(item for item in result["rows"] if item["originalLabel"] == "Unknown label")
        self.assertTrue(any(item["namespace"] == "entrezgene" for item in preview_row["externalIdentifiers"]))
        self.assertEqual(result["externalReactome"]["pathways"][0]["stableId"], "R-HSA-5673001")
        self.assertEqual(result["summary"]["enrichmentMode"], "LOCAL+REACTOME")
        self.assertEqual(len(release_ids), 2)
        self.assertEqual(list(SourceRelease.objects.filter(pk__in=release_ids).values_list("source__slug", flat=True)), ["mygene-info", "reactome"])
        self.assertEqual(warnings, [])

    def test_opt_in_gprofiler_uses_significant_query_and_all_identified_rows_as_background(self):
        result, row_results, _release_ids = run_proteomics_analysis(self.task)
        response = {
            "sourceVersion": "e114_eg62_p19_test:versions",
            "terms": [{
                "termId": "GO:0001234",
                "name": "Example process",
                "source": "GO:BP",
                "pValue": None,
                "adjustedPValue": 0.01,
                "correctionMethod": "FDR",
                "intersectionSize": 2,
                "querySize": 3,
                "termSize": 9,
                "effectiveDomainSize": 1000,
                "precision": 2 / 3,
                "recall": 2 / 9,
                "matchedIdentifiers": ["ENSG000001", "ENSG000002"],
            }],
            "queryCount": 3,
            "queryTruncatedCount": 0,
            "backgroundCount": 4,
            "backgroundType": "measured_identifiers_custom",
            "organism": "Homo sapiens",
            "sources": ["GO:BP", "GO:CC", "GO:MF", "KEGG"],
            "threshold": 0.05,
            "correctionMethod": "FDR",
            "rawPValuesReturned": False,
            "providerMetadata": {},
            "dataVersions": {"gprofiler_version": "e114_eg62_p19_test"},
        }
        with patch("apps.proteomics.integrations.analyze_human_go_kegg", return_value=response) as analyze:
            release_ids, warnings = run_opt_in_gprofiler(self.task, result, row_results)

        query, background = analyze.call_args.args
        self.assertIn("TP53", query)
        self.assertIn("IL6", background)
        self.assertTrue(set(query).issubset(set(background)))
        self.assertEqual(result["externalGProfiler"]["status"], "succeeded")
        self.assertEqual(result["summary"]["goKeggTermCount"], 1)
        release = SourceRelease.objects.get(pk=release_ids[0])
        self.assertEqual(release.source.slug, "gprofiler")
        self.assertEqual(release.version, "e114_eg62_p19_test:versions")
        self.assertEqual(warnings, [])

    def test_opt_in_gprofiler_provider_failure_keeps_local_result_and_admin_can_disable(self):
        result, row_results, _release_ids = run_proteomics_analysis(self.task)
        with patch(
            "apps.proteomics.integrations.analyze_human_go_kegg",
            side_effect=GProfilerError("safe provider error"),
        ):
            release_ids, warnings = run_opt_in_gprofiler(self.task, result, row_results)
        self.assertEqual(result["externalGProfiler"]["status"], "unavailable")
        self.assertEqual(release_ids, [])
        self.assertTrue(warnings)

        source = DataSource.objects.get(slug="gprofiler")
        source.enabled = False
        source.save(update_fields=["enabled"])
        with patch("apps.proteomics.integrations.analyze_human_go_kegg") as analyze:
            release_ids, warnings = run_opt_in_gprofiler(self.task, result, row_results)
        analyze.assert_not_called()
        self.assertEqual(result["externalGProfiler"]["status"], "disabled")
        self.assertEqual(release_ids, [])
        self.assertTrue(warnings)

    def test_opt_in_string_queries_only_selected_symbols_and_records_version(self):
        result, row_results, _release_ids = run_proteomics_analysis(self.task)
        selected_labels = list(dict.fromkeys(
            row.normalized_symbol for row in row_results if row.selected and row.normalized_symbol
        ))
        network = {
            "analysisKind": "string_ppi",
            "organism": "Homo sapiens",
            "taxonId": 9606,
            "requiredScore": 800,
            "networkType": "physical",
            "source": "STRING",
            "sourceVersion": "12.0",
            "sourceVersionKnown": True,
            "inputCount": len(selected_labels),
            "interactionCount": 1,
            "nodes": [
                {"id": "9606.ENSP0001", "label": "TP53", "type": "protein"},
                {"id": "9606.ENSP0002", "label": "MAPK1", "type": "protein"},
            ],
            "edges": [{"source": "9606.ENSP0001", "target": "9606.ENSP0002", "score": 0.91, "scoreOutOf1000": 910}],
            "retrievedAt": "2026-10-03T00:00:00+00:00",
            "note": "physical interaction evidence",
        }
        with patch(
            "apps.proteomics.integrations.query_string_physical_network",
            return_value=(network, "12.0"),
        ) as query:
            release_ids, warnings = run_opt_in_string(self.task, result, row_results, 800)

        query.assert_called_once_with(selected_labels, 800)
        self.assertEqual(result["externalString"]["status"], "succeeded")
        self.assertEqual(result["externalString"]["interactionCount"], 1)
        self.assertTrue(result["externalString"]["consentRecorded"])
        self.assertTrue(result["externalString"]["sourceVersionKnown"])
        release = SourceRelease.objects.get(pk=release_ids[0])
        self.assertEqual(release.source.slug, "string")
        self.assertEqual(release.version, "12.0")
        self.assertEqual(warnings, [])
