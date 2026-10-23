"""Reject locale-ambiguous numeric cells without rewriting source cells."""

import csv
import hashlib
import io
import tempfile
from copy import deepcopy
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import SimpleTestCase, TestCase, override_settings
from openpyxl import Workbook

from apps.proteomics.raw_matrix import _matrix_value, analyze_raw_matrix
from apps.core.models import AnalysisTask, ResearchDataset
from apps.proteomics.services import (
    _number,
    _parse_rows,
    parse_dataset_table,
    resolve_mapping,
    run_proteomics_analysis,
)


class NumericFormatTests(SimpleTestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory(prefix="tcm-numeric-format-test-")
        self.addCleanup(self.media.cleanup)
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media.name,
            STORAGES={"default": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
                "OPTIONS": {"location": self.media.name, "base_url": "/media/"},
            }},
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.thresholds = {"log2FcMin": 1.0, "fdrMax": 0.05, "pValueMax": 0.05}

    def table(self, extension, columns, rows):
        filename = f"input.{extension}"
        if extension == "xlsx":
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(columns)
            for row in rows:
                sheet.append(row)
            stream = io.BytesIO()
            workbook.save(stream)
            workbook.close()
            payload = stream.getvalue()
        else:
            stream = io.StringIO(newline="")
            writer = csv.writer(stream, delimiter="\t" if extension == "tsv" else ",")
            writer.writerow(columns)
            writer.writerows(rows)
            payload = stream.getvalue().encode()
        Path(self.media.name, filename).write_bytes(payload)
        return parse_dataset_table(filename, filename)

    @staticmethod
    def design(missing_policy="available_replicates", normalization="none", design_type="unpaired"):
        design = {
            "identifierColumn": "Protein",
            "sampleColumns": ["C1", "C2", "C3", "T1", "T2", "T3"],
            "controlSamples": ["C1", "C2", "C3"],
            "treatmentSamples": ["T1", "T2", "T3"],
            "valuesAreLog2": True,
            "normalization": normalization,
            "missingPolicy": missing_policy,
            "designType": design_type,
        }
        if design_type == "paired":
            design["samplePairs"] = [
                {"pairId": str(index), "controlSample": f"C{index}", "treatmentSample": f"T{index}"}
                for index in range(1, 4)
            ]
        if design_type == "multifactor":
            design.update({
                "controlSamples": [], "treatmentSamples": [],
                "contrastFactor": "group", "referenceLevel": "control", "treatmentLevel": "treated",
                "sampleFactors": [
                    {"sampleColumn": sample, "factors": {"group": group, "batch": batch}}
                    for sample, group, batch in [
                        ("C1", "control", "A"), ("C2", "control", "B"), ("C3", "control", "A"),
                        ("T1", "treated", "A"), ("T2", "treated", "B"), ("T3", "treated", "B"),
                    ]
                ],
            })
        return design

    def test_numeric_converters_reject_commas_without_guessing_locale(self):
        for value in ("0,01", "1,2", "1,234", "1,234.5", "1.234,5", "-1,2e-3", "0,5%"):
            with self.subTest(value=value):
                self.assertEqual(_number(value), (None, "ambiguous_numeric_format"))
                self.assertEqual(_matrix_value(value, values_are_log2=True), (None, "ambiguous_numeric_format"))

    def test_plain_decimal_scientific_and_existing_percent_rules_unchanged(self):
        for value, expected in [("2", 2), ("-2.5", -2.5), ("+2.5", 2.5), (" 1e-3 ", 0.001), ("2%", 0.02)]:
            with self.subTest(value=value):
                self.assertEqual(_number(value), (expected, None))
        for value in ("", "NA", "nan", "null", "none", "-"):
            self.assertEqual(_number(value), (None, None))
            self.assertEqual(_matrix_value(value, values_are_log2=True), (None, None))
        self.assertEqual(_matrix_value("2%", values_are_log2=True), (None, "invalid_sample_value"))
        self.assertEqual(_matrix_value("8", values_are_log2=False), (3.0, None))

    def test_differential_formats_preserve_labels_raw_cells_indices_and_field_qc(self):
        columns = ["Gene", "Protein", "log2FC", "pvalue", "FDR", "Comment"]
        input_rows = [
            ["TP53", "Other, protein", "+2.5", "1e-3", "2%", "unchanged, note"],
            ["BADFC", "Alpha", "1,2", "0.01", "0.02", "fc"],
            ["BADP", "Beta", "2", "0,01", "0.02", "p"],
            ["BADFDR", "Gamma", "2", "0.01", "0,01", "fdr"],
            ["BADTHOUSANDS", "Delta", "1,234", "0.01", "0.02", "thousands"],
            ["BADPERCENT", "Epsilon", "2", "0.01", "0,5%", "percent"],
        ]
        for extension in ("csv", "tsv", "xlsx"):
            with self.subTest(extension=extension):
                table = self.table(extension, columns, input_rows)
                original = deepcopy(table.rows)
                analyzed, qc = _parse_rows(table.rows, resolve_mapping(table.columns, {}), self.thresholds)
                self.assertEqual(table.rows, original)
                self.assertEqual([row.raw for row in analyzed], original)
                self.assertEqual([row.row_index for row in analyzed], list(range(6)))
                self.assertEqual(analyzed[0].protein_name, "Other, protein")
                self.assertTrue(analyzed[0].selected)
                self.assertEqual((analyzed[0].log2_fold_change, analyzed[0].p_value, analyzed[0].fdr), (2.5, .001, .02))
                self.assertEqual(qc["ambiguousNumericFormatRowCount"], 5)
                for index, field in [(1, "log2fc"), (2, "p_value"), (3, "fdr"), (4, "log2fc"), (5, "fdr")]:
                    self.assertFalse(analyzed[index].selected)
                    self.assertIn("ambiguous_numeric_format", analyzed[index].exclusion_reasons)
                    self.assertIn(f"ambiguous_{field}_numeric_format", analyzed[index].qc_warnings)
                self.assertIsNone(analyzed[1].log2_fold_change)
                self.assertEqual(analyzed[1].p_value, .01)
                self.assertEqual(analyzed[1].fdr, .02)
                self.assertEqual(analyzed[1].raw["log2FC"], "1,2")
                self.assertEqual(analyzed[1].raw["Comment"], "fc")

    def test_matrix_formats_preserve_raw_and_reject_ambiguous_rows_with_available_replicates(self):
        columns = ["Protein", "C1", "C2", "C3", "T1", "T2", "T3", "Note"]
        input_rows = [
            ["Other, protein", "1", "+2", "3e0", "4", "5", "7", "valid, note"],
            ["BAD", "1,2", "2", "3", "4", "5", "7", "untouched"],
        ]
        for extension in ("csv", "tsv", "xlsx"):
            with self.subTest(extension=extension):
                table = self.table(extension, columns, input_rows)
                original = deepcopy(table.rows)
                derived, exclusions, details, warnings = analyze_raw_matrix(table.rows, self.design())
                self.assertEqual(table.rows, original)
                self.assertEqual(derived[0]["__identifier"], "Other, protein")
                self.assertNotEqual(derived[0]["__pvalue"], "")
                self.assertEqual(derived[1]["__log2fc"], "")
                self.assertEqual(derived[1]["__pvalue"], "")
                self.assertIn("ambiguous_numeric_format", exclusions[1])
                self.assertIn("ambiguous_sample_numeric_format", details["rowWarnings"][1])
                self.assertIn("ambiguous_sample_numeric_format:C1", details["rowWarnings"][1])
                self.assertEqual(details["qc"]["rowsWithAmbiguousNumericFormat"], 1)
                self.assertEqual(details["qc"]["ambiguousNumericFormatValueCount"], 1)
                self.assertEqual(details["qc"]["missingSampleValueCount"], 0)
                self.assertEqual(details["qc"]["rowsTested"], 1)
                self.assertTrue(any("逗号" in warning for warning in warnings))

    def test_native_excel_numbers_use_their_values_regardless_of_display_format(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Gene", "log2FC", "pvalue", "FDR"])
        sheet.append(["Other, protein", 2.5, 0.01, 0.02])
        for cell in sheet[2][1:]:
            cell.number_format = "#,##0.00"
        stream = io.BytesIO()
        workbook.save(stream)
        workbook.close()
        Path(self.media.name, "native.xlsx").write_bytes(stream.getvalue())
        table = parse_dataset_table("native.xlsx", "native.xlsx")
        rows, qc = _parse_rows(table.rows, resolve_mapping(table.columns, {}), self.thresholds)
        self.assertEqual(rows[0].original_label, "Other, protein")
        self.assertEqual((rows[0].log2_fold_change, rows[0].p_value, rows[0].fdr), (2.5, .01, .02))
        self.assertTrue(rows[0].selected)
        self.assertEqual(qc["ambiguousNumericFormatRowCount"], 0)

    def test_ambiguity_rejects_entire_row_in_all_designs_and_missing_policies(self):
        rows = [{"Protein": "BAD", "C1": "1,2", "C2": "2", "C3": "3", "T1": "5", "T2": "7", "T3": "8"}]
        for design_type in ("unpaired", "paired", "multifactor"):
            for policy in ("complete_rows", "available_replicates"):
                with self.subTest(design=design_type, missing_policy=policy):
                    derived, exclusions, details, _ = analyze_raw_matrix(rows, self.design(policy, design_type=design_type))
                    self.assertIn("ambiguous_numeric_format", exclusions[0])
                    self.assertEqual(details["qc"]["rowsTested"], 0)
                    self.assertEqual(derived[0]["__fdr"], "")

    def test_ambiguous_row_cannot_influence_median_offsets_of_valid_rows(self):
        valid = [
            {"Protein": "A", "C1": "1", "C2": "2", "C3": "4", "T1": "5", "T2": "7", "T3": "8"},
            {"Protein": "B", "C1": "2", "C2": "5", "C3": "6", "T1": "4", "T2": "6", "T3": "9"},
            {"Protein": "C", "C1": "4", "C2": "6", "C3": "9", "T1": "7", "T2": "10", "T3": "14"},
        ]
        ambiguous = {"Protein": "BAD", "C1": "1,2", "C2": "9000", "C3": "9000", "T1": "9000", "T2": "9000", "T3": "9000"}
        design = self.design(normalization="median_center")
        reference, _, reference_details, _ = analyze_raw_matrix(valid, design)
        actual, exclusions, details, _ = analyze_raw_matrix([*valid, ambiguous], design)
        self.assertEqual(actual[:3], reference)
        self.assertEqual(details["qc"]["rowsTested"], reference_details["qc"]["rowsTested"])
        self.assertIn("ambiguous_numeric_format", exclusions[3])

    def test_actual_missing_value_keeps_existing_available_replicates_policy(self):
        rows = [{"Protein": "P", "C1": "", "C2": "2", "C3": "3", "T1": "5", "T2": "7", "T3": "8"}]
        derived, exclusions, details, _ = analyze_raw_matrix(rows, self.design())
        self.assertEqual(exclusions, {})
        self.assertNotEqual(derived[0]["__pvalue"], "")
        self.assertEqual(details["rowWarnings"][0], ["missing_sample_values"])

    def test_fdr_priority_p_fallback_and_constant_row_policy_remain_unchanged(self):
        table = self.table("csv", ["Gene", "log2FC", "pvalue", "FDR"], [
            ["FDR_FIRST", "2", "0.9", "0.01"], ["P_FALLBACK", "2", "0.01", ""],
        ])
        rows, _ = _parse_rows(table.rows, resolve_mapping(table.columns, {}), self.thresholds)
        self.assertTrue(all(row.selected for row in rows))
        derived, exclusions, details, _ = analyze_raw_matrix([
            {"Protein": "CONSTANT", "C1": "2", "C2": "2", "C3": "2", "T1": "2", "T2": "2", "T3": "2"}
        ], self.design())
        self.assertEqual(exclusions, {})
        self.assertEqual(derived[0]["__pvalue"], "1.0")
        self.assertEqual(details["qc"]["rowsTested"], 1)


class NumericFormatIntegrationTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory(prefix="tcm-numeric-integration-test-")
        self.addCleanup(self.media.cleanup)
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media.name,
            STORAGES={"default": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
                "OPTIONS": {"location": self.media.name, "base_url": "/media/"},
            }},
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.owner = get_user_model().objects.create_user(username="numeric-format-owner")

    def task(self, extension, columns, rows, *, raw_matrix=False):
        if extension == "xlsx":
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(columns)
            for row in rows:
                sheet.append(row)
            stream = io.BytesIO()
            workbook.save(stream)
            workbook.close()
            content = stream.getvalue()
        else:
            stream = io.StringIO(newline="")
            writer = csv.writer(stream, delimiter="\t" if extension == "tsv" else ",")
            writer.writerow(columns)
            writer.writerows(rows)
            content = stream.getvalue().encode()
        filename = f"input.{extension}"
        key = default_storage.save(filename, ContentFile(content))
        dataset = ResearchDataset.objects.create(
            owner=self.owner, name="Synthetic numeric format regression",
            original_filename=filename, storage_key=key,
            content_sha256=hashlib.sha256(content).hexdigest(), byte_size=len(content),
        )
        parameters = {
            "thresholds": {"log2FcMin": 1.0, "pValueMax": 0.05, "fdrMax": 0.05},
            "mapping": {}, "referenceTargets": [],
        }
        if raw_matrix:
            parameters.update(analysisMode="raw_matrix", matrixDesign=NumericFormatTests.design())
        return AnalysisTask.objects.create(
            owner=self.owner, task_type=AnalysisTask.TaskType.PROTEOMICS,
            dataset=dataset, input_parameters=parameters,
        ), content

    def test_full_differential_result_reports_exact_fields_and_preserves_source_file(self):
        for extension in ("csv", "tsv", "xlsx"):
            with self.subTest(extension=extension):
                task, original = self.task(extension, ["Gene", "Protein", "log2FC", "FDR", "pvalue"], [
                    ["TP53", "Other, protein", "2", "0.01", "0.02"],
                    ["BADFC", "A", "1,2", "0.01", "0.02"],
                    ["BADFDR", "B", "2", "0,01", "0.02"],
                ])
                result, stored, _ = run_proteomics_analysis(task)
                self.assertEqual(result["algorithmVersion"], "proteomics-py-1.11")
                self.assertEqual(result["qc"]["ambiguousNumericFormatRowCount"], 2)
                self.assertEqual([row.row_index for row in stored], [0, 1, 2])
                self.assertEqual(stored[0].protein_name, "Other, protein")
                self.assertTrue(stored[0].selected)
                self.assertIsNone(stored[1].log2_fold_change)
                self.assertIn("ambiguous_log2fc_numeric_format", stored[1].qc_warnings)
                self.assertIn("ambiguous_fdr_numeric_format", stored[2].qc_warnings)
                self.assertTrue(any("逗号" in warning for warning in result["warnings"]))
                with default_storage.open(task.dataset.storage_key, "rb") as stream:
                    self.assertEqual(stream.read(), original)

    def test_full_matrix_result_retains_field_qc_without_using_ambiguous_row(self):
        for extension in ("csv", "tsv", "xlsx"):
            with self.subTest(extension=extension):
                task, original = self.task(extension, ["Protein", "C1", "C2", "C3", "T1", "T2", "T3"], [
                    ["Other, protein", "1", "2", "3", "7", "8", "10"],
                    ["BAD", "1,2", "2", "3", "7", "8", "10"],
                ], raw_matrix=True)
                result, stored, _ = run_proteomics_analysis(task)
                self.assertEqual(result["qc"]["rawMatrix"]["rowsTested"], 1)
                self.assertEqual(result["qc"]["ambiguousNumericFormatRowCount"], 1)
                self.assertEqual(result["qc"]["rawMatrix"]["rowsWithAmbiguousNumericFormat"], 1)
                self.assertFalse(stored[1].selected)
                self.assertIsNone(stored[1].p_value)
                self.assertIn("ambiguous_numeric_format", stored[1].exclusion_reasons)
                self.assertIn("ambiguous_sample_numeric_format:C1", stored[1].qc_warnings)
                self.assertEqual(stored[0].original_label, "Other, protein")
                with default_storage.open(task.dataset.storage_key, "rb") as stream:
                    self.assertEqual(stream.read(), original)
