from io import BytesIO
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import override_settings
from django.urls import reverse
from openpyxl import load_workbook
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, ResearchDataset
from apps.proteomics.models import ProteomicsRowResult


class ProteomicsApiTests(APITestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_dir.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.owner = get_user_model().objects.create_user(
            username="analysis-owner", password="test-password-123"
        )
        self.other_user = get_user_model().objects.create_user(
            username="analysis-other", password="test-password-123"
        )
        key = default_storage.save(
            "research-datasets/owner/source.csv",
            ContentFile(b"Gene,log2FC,FDR\nTP53,2,0.01\n"),
        )
        self.dataset = ResearchDataset.objects.create(
            owner=self.owner,
            name="API test set",
            original_filename="source.csv",
            storage_key=key,
            content_sha256="test-digest",
            byte_size=25,
        )

    def test_analyze_is_owner_scoped_and_enqueues_traceable_task(self):
        self.client.force_authenticate(self.owner)
        with patch("apps.proteomics.tasks.run_proteomics_task.apply_async") as enqueue:
            response = self.client.post(
                reverse("dataset-analyze", args=[self.dataset.pk]),
                {
                    "mapping": {"geneColumn": "Gene"},
                    "thresholds": {"log2FcMin": 1, "fdrMax": 0.05, "pValueMax": 0.05},
                    "referenceTargets": ["TP53, IL6", "tp53"],
                },
                format="json",
            )

        self.assertEqual(response.status_code, 202)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertEqual(task.owner, self.owner)
        self.assertEqual(task.dataset, self.dataset)
        self.assertEqual(task.task_type, AnalysisTask.TaskType.PROTEOMICS)
        self.assertEqual(task.status, AnalysisTask.Status.QUEUED)
        self.assertFalse(task.input_parameters["externalReactome"])
        self.assertFalse(task.input_parameters["externalString"])
        self.assertFalse(task.input_parameters["externalGProfiler"])
        self.assertEqual(task.input_parameters["stringRequiredScore"], 700)
        self.assertEqual(task.input_parameters["datasetSha256"], "test-digest")
        self.assertEqual(task.input_parameters["referenceTargets"], ["TP53", "IL6"])
        enqueue.assert_called_once_with(args=[task.pk])

        self.client.force_authenticate(self.other_user)
        hidden = self.client.post(reverse("dataset-analyze", args=[self.dataset.pk]), {}, format="json")
        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(AnalysisTask.objects.count(), 1)

    def test_external_mapping_and_reactome_are_only_enabled_by_explicit_opt_in(self):
        self.client.force_authenticate(self.owner)
        with patch("apps.proteomics.tasks.run_proteomics_task.apply_async"):
            response = self.client.post(
                reverse("dataset-analyze", args=[self.dataset.pk]),
                {"externalReactome": True},
                format="json",
            )

        self.assertEqual(response.status_code, 202)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertTrue(task.input_parameters["externalReactome"])

    def test_string_ppi_requires_a_separate_explicit_opt_in_and_bounded_score(self):
        self.client.force_authenticate(self.owner)
        with patch("apps.proteomics.tasks.run_proteomics_task.apply_async"):
            response = self.client.post(
                reverse("dataset-analyze", args=[self.dataset.pk]),
                {"externalString": True, "stringRequiredScore": 850},
                format="json",
            )
        self.assertEqual(response.status_code, 202)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertTrue(task.input_parameters["externalString"])
        self.assertEqual(task.input_parameters["stringRequiredScore"], 850)

        invalid = self.client.post(
            reverse("dataset-analyze", args=[self.dataset.pk]),
            {"externalString": True, "stringRequiredScore": 1001},
            format="json",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(AnalysisTask.objects.count(), 1)

    def test_go_kegg_enrichment_requires_a_separate_explicit_opt_in(self):
        self.client.force_authenticate(self.owner)
        with patch("apps.proteomics.tasks.run_proteomics_task.apply_async"):
            response = self.client.post(
                reverse("dataset-analyze", args=[self.dataset.pk]),
                {"externalGProfiler": True},
                format="json",
            )
        self.assertEqual(response.status_code, 202)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertTrue(task.input_parameters["externalGProfiler"])

    def test_queue_failure_returns_standard_503_and_keeps_failed_audit_task(self):
        self.client.force_authenticate(self.owner)
        with patch(
            "apps.proteomics.tasks.run_proteomics_task.apply_async",
            side_effect=ConnectionError("private broker detail"),
        ):
            response = self.client.post(
                reverse("dataset-analyze", args=[self.dataset.pk]), {}, format="json"
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["error"]["code"], "SERVICE_UNAVAILABLE")
        self.assertNotIn("private broker detail", str(response.data))
        task = AnalysisTask.objects.get()
        self.assertEqual(task.status, AnalysisTask.Status.FAILED)
        self.assertEqual(task.error_summary, "任务队列暂不可用，请稍后重试。")

    def test_superuser_analysis_remains_visible_to_dataset_owner_and_records_requester(self):
        admin = get_user_model().objects.create_superuser(
            username="analysis-admin", email="analysis-admin@example.test", password="test-password-123"
        )
        self.client.force_authenticate(admin)
        with patch("apps.proteomics.tasks.run_proteomics_task.apply_async"):
            created = self.client.post(
                reverse("dataset-analyze", args=[self.dataset.pk]), {}, format="json"
            )

        task = AnalysisTask.objects.get(pk=created.data["id"])
        self.assertEqual(task.owner, self.owner)
        self.assertEqual(task.created_by, admin)
        self.assertEqual(created.data["owner_username"], self.owner.username)
        self.assertEqual(created.data["requested_by_username"], admin.username)

        self.client.force_authenticate(self.owner)
        visible = self.client.get(reverse("analysis-task-detail", args=[task.pk]))
        self.assertEqual(visible.status_code, 200)

    def test_original_file_cannot_be_deleted_or_replaced_after_analysis_is_created(self):
        AnalysisTask.objects.create(
            owner=self.owner,
            task_type=AnalysisTask.TaskType.PROTEOMICS,
            dataset=self.dataset,
        )
        self.client.force_authenticate(self.owner)

        deleted = self.client.delete(reverse("dataset-detail", args=[self.dataset.pk]))
        replaced = self.client.patch(
            reverse("dataset-detail", args=[self.dataset.pk]),
            {"file": ContentFile(b"Gene\nTP53\n", name="replacement.csv")},
            format="multipart",
        )

        self.assertEqual(deleted.status_code, 409)
        self.assertEqual(replaced.status_code, 409)
        self.assertTrue(default_storage.exists(self.dataset.storage_key))
        self.assertTrue(ResearchDataset.objects.filter(pk=self.dataset.pk).exists())

    def test_row_results_are_paginated_and_private_to_the_task_owner(self):
        task = AnalysisTask.objects.create(
            owner=self.owner,
            task_type=AnalysisTask.TaskType.PROTEOMICS,
            dataset=self.dataset,
            status=AnalysisTask.Status.SUCCEEDED,
        )
        ProteomicsRowResult.objects.create(
            task=task,
            row_index=0,
            original_label="TP53",
            normalized_symbol="TP53",
            mapping_status=ProteomicsRowResult.MappingStatus.UNVERIFIED,
            selected=True,
        )
        self.client.force_authenticate(self.owner)
        visible = self.client.get(reverse("analysis-task-rows", args=[task.pk]))
        self.assertEqual(visible.status_code, 200)
        self.assertEqual(visible.data["count"], 1)
        self.assertEqual(visible.data["results"][0]["normalized_symbol"], "TP53")

        self.client.force_authenticate(self.other_user)
        hidden = self.client.get(reverse("analysis-task-rows", args=[task.pk]))
        self.assertEqual(hidden.status_code, 404)

    def test_csv_and_xlsx_exports_are_private_and_escape_formula_like_labels(self):
        task = AnalysisTask.objects.create(
            owner=self.owner,
            task_type=AnalysisTask.TaskType.PROTEOMICS,
            dataset=self.dataset,
            status=AnalysisTask.Status.SUCCEEDED,
            result={"algorithmVersion": "proteomics-py-1.1"},
            input_parameters={"thresholds": {"fdrMax": 0.05}},
        )
        ProteomicsRowResult.objects.create(
            task=task,
            row_index=0,
            original_label="=2+2",
            protein_name="@danger",
            mapping_status=ProteomicsRowResult.MappingStatus.UNMAPPED,
            selected=True,
        )
        self.client.force_authenticate(self.owner)
        detail = self.client.get(reverse("analysis-task-detail", args=[task.pk]))
        self.assertEqual(detail.status_code, 200, getattr(detail, "data", detail.content))
        self.assertEqual(task.task_type, AnalysisTask.TaskType.PROTEOMICS)
        self.assertEqual(task.status, AnalysisTask.Status.SUCCEEDED)

        csv_response = self.client.get(reverse("analysis-task-export", args=[task.pk]), {"file_format": "csv"})
        self.assertEqual(csv_response.status_code, 200, getattr(csv_response, "data", csv_response.content))
        self.assertIn("attachment;", csv_response["Content-Disposition"])
        csv_content = csv_response.content.decode("utf-8-sig")
        self.assertIn("'=2+2", csv_content)
        self.assertIn("'@danger", csv_content)

        xlsx_response = self.client.get(reverse("analysis-task-export", args=[task.pk]), {"file_format": "xlsx"})
        self.assertEqual(xlsx_response.status_code, 200)
        workbook = load_workbook(BytesIO(xlsx_response.content), data_only=False)
        self.assertEqual(workbook.sheetnames, ["分析信息", "逐行结果"])
        self.assertEqual(workbook["逐行结果"]["B2"].value, "'=2+2")
        self.assertEqual(workbook["逐行结果"]["B2"].data_type, "s")

        self.client.force_authenticate(self.other_user)
        hidden = self.client.get(reverse("analysis-task-export", args=[task.pk]), {"file_format": "csv"})
        self.assertEqual(hidden.status_code, 404)
