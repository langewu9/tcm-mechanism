"""Volcano availability describes every persisted row, including excluded rows."""
import csv
import io
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, ResearchDataset
from apps.core.services.visualization import VisualizationInputError, build_chart_payload
from apps.proteomics.models import ProteomicsRowResult
from apps.proteomics.tasks import run_proteomics_task


class VolcanoEligibilityTests(APITestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = override_settings(MEDIA_ROOT=directory.name, STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage",
                        "OPTIONS": {"location": directory.name}},
        })
        storage.enable()
        self.addCleanup(storage.disable)
        self.owner = get_user_model().objects.create_user(username="volcano-eligibility-owner")
        self.client.force_authenticate(self.owner)

    def analyze(self, columns, rows, **parameters):
        content = io.StringIO()
        writer = csv.writer(content)
        writer.writerow(columns)
        writer.writerows(rows)
        encoded = content.getvalue().encode()
        key = default_storage.save("volcano-eligibility.csv", ContentFile(encoded))
        dataset = ResearchDataset.objects.create(owner=self.owner, name="Volcano eligibility fixture",
            original_filename="volcano-eligibility.csv", storage_key=key, byte_size=len(encoded))
        task = AnalysisTask.objects.create(owner=self.owner, dataset=dataset, task_type="proteomics",
            input_parameters={"mapping": {}, "referenceTargets": [],
                "thresholds": {"log2FcMin": 1, "pValueMax": .05, "fdrMax": .05}, **parameters})
        self.assertEqual(run_proteomics_task.run(task.pk)["status"], "succeeded")
        task.refresh_from_db()
        persisted = ProteomicsRowResult.objects.filter(task=task, log2_fold_change__isnull=False,
            p_value__isnull=False, p_value__gte=0, p_value__lte=1)
        self.assertEqual(task.result["qc"]["volcanoEligibleRowCount"], persisted.count())
        detail = self.client.get(reverse("analysis-task-detail", args=[task.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["result"]["qc"]["volcanoEligibleRowCount"], persisted.count())
        if persisted.exists():
            self.assertEqual(len(build_chart_payload(task, "proteomics_volcano")["data"]), persisted.count())
        else:
            with self.assertRaisesRegex(VisualizationInputError, "没有同时包含有效"):
                build_chart_payload(task, "proteomics_volcano")
        return task

    def test_all_persisted_rows_count_even_when_unselected_or_missing_identifiers(self):
        task = self.analyze(["Gene", "log2FC", "PValue", "FDR"], [
            ["SELECTED", 2, .01, .01],
            ["ZERO_FC_AND_P", 0, 0, .9],
            ["P_ONE", 0, 1, .9],
            ["INVALID_FDR", -2, .3, "Infinity"],
            ["", 2, .01, .01],
            ["FDR_ONLY", 2, "", .01],
            ["MISSING_FC", "", .02, .01],
            ["INFINITE_FC", "Infinity", .02, .01],
            ["NEGATIVE_INFINITE_FC", "-Infinity", .02, .01],
            ["NAN_FC", "NaN", .02, .01],
            ["INFINITE_P", 2, "Infinity", .01],
            ["NAN_P", 2, "NaN", .01],
            ["NEGATIVE_P", 2, -.1, .01],
            ["ABOVE_ONE_P", 2, 1.1, .01],
            ["INVALID_FC", "not-a-number", .02, .01],
            ["INVALID_P", 2, "not-a-number", .01],
        ])
        self.assertEqual(task.result["qc"]["volcanoEligibleRowCount"], 5)
        self.assertEqual(task.result["summary"]["selectedRowCount"], 3)
        self.assertEqual(task.proteomics_rows.filter(selected=False, p_value__gte=0,
            p_value__lte=1, log2_fold_change__isnull=False).count(), 4)

    def test_selected_preview_can_have_no_p_values_while_an_excluded_row_is_eligible(self):
        task = self.analyze(["Gene", "log2FC", "PValue", "FDR"],
            [["FDR_ONLY", 2, "", .01]] * 501 + [["EXCLUDED", 0, 1, 1]])
        self.assertEqual(task.result["qc"]["volcanoEligibleRowCount"], 1)
        self.assertTrue(task.result["previewTruncated"])
        self.assertEqual(len(task.result["rows"]), 500)
        self.assertTrue(all(row["pValue"] is None for row in task.result["rows"]))

    def test_fdr_only_and_missing_or_invalid_statistics_are_not_eligible(self):
        for columns, rows in [
            (["Gene", "log2FC", "FDR"], [["FDR_ONLY", 2, .01]]),
            (["Gene", "log2FC", "PValue"], [["EMPTY", "", ""], ["NONFINITE", "Infinity", "NaN"]]),
        ]:
            with self.subTest(columns=columns):
                self.assertEqual(self.analyze(columns, rows).result["qc"]["volcanoEligibleRowCount"], 0)

    def test_raw_matrix_counts_valid_computed_statistics_without_selected_rows(self):
        task = self.analyze(["Gene", "C1", "C2", "T1", "T2"], [
            ["CHANGED", 8, 9, 16, 20], ["UNCHANGED", 4, 5, 4, 5], ["INCOMPLETE", "", 5, 4, 5],
        ], analysisMode="raw_matrix", thresholds={"log2FcMin": 100, "pValueMax": .05, "fdrMax": .05},
            matrixDesign={"identifierColumn": "Gene", "sampleColumns": ["C1", "C2", "T1", "T2"],
                "controlSamples": ["C1", "C2"], "treatmentSamples": ["T1", "T2"],
                "designType": "unpaired", "valuesAreLog2": False, "normalization": "none",
                "missingPolicy": "complete_rows"})
        self.assertEqual(task.result["qc"]["volcanoEligibleRowCount"], 2)
        self.assertEqual(task.result["summary"]["selectedRowCount"], 0)
        self.assertEqual(task.result["rows"], [])
