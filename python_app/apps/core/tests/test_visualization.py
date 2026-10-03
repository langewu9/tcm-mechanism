import base64
import hashlib
import json
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, VisualizationArtifact
from apps.core.services.visualization import VisualizationInputError, build_chart_payload
from apps.core.tasks import run_visualization_task
from apps.proteomics.models import ProteomicsRowResult


class VisualizationWorkflowTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="viz-owner", password="test-password-123")
        self.other = user_model.objects.create_user(username="viz-other", password="test-password-123")
        self.parent = AnalysisTask.objects.create(
            owner=self.owner,
            created_by=self.owner,
            task_type=AnalysisTask.TaskType.NETWORK,
            status=AnalysisTask.Status.SUCCEEDED,
            result={
                "charts": {
                    "overlap": [
                        {"name": "中药靶点", "value": 4},
                        {"name": "疾病靶点", "value": 3},
                    ],
                    "components": [{"name": "compound-a", "targets": 2}],
                    "pathways": [{"name": "pathway-a", "targets": 1}],
                },
                "privateCaseText": "病案中的敏感症状",
            },
        )

    def test_chart_payload_uses_only_allowlisted_summary_data(self):
        payload = build_chart_payload(self.parent, "overlap")
        self.assertEqual(payload["chartType"], "bar")
        self.assertEqual(payload["data"][0], {"label": "中药靶点", "value": 4})
        self.assertNotIn("病案中的敏感症状", json.dumps(payload, ensure_ascii=False))
        canonical = json.dumps(
            {key: value for key, value in payload.items() if key != "inputSha256"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(payload["inputSha256"], hashlib.sha256(canonical.encode()).hexdigest())

    def test_proteomics_volcano_payload_uses_persisted_rows_and_records_thresholds(self):
        task = AnalysisTask.objects.create(
            owner=self.owner,
            task_type=AnalysisTask.TaskType.PROTEOMICS,
            status=AnalysisTask.Status.SUCCEEDED,
            input_parameters={"privateCaseText": "不得交给 R 的医案文本"},
            result={
                "thresholds": {"log2FcMin": 1.0, "fdrMax": 0.05, "pValueMax": 0.01},
                "summary": {"privateText": "不得发送"},
            },
        )
        ProteomicsRowResult.objects.create(
            task=task,
            row_index=0,
            original_label="P04637",
            normalized_symbol="TP53",
            mapping_status=ProteomicsRowResult.MappingStatus.UNVERIFIED,
            log2_fold_change=2.0,
            p_value=0.0,
            fdr=0.001,
            selected=True,
        )
        ProteomicsRowResult.objects.create(
            task=task,
            row_index=1,
            original_label="IL6",
            mapping_status=ProteomicsRowResult.MappingStatus.UNVERIFIED,
            log2_fold_change=-1.2,
            p_value=0.04,
            fdr=0.07,
            selected=False,
        )
        ProteomicsRowResult.objects.create(
            task=task,
            row_index=2,
            original_label="MISSING_P",
            mapping_status=ProteomicsRowResult.MappingStatus.UNMAPPED,
            log2_fold_change=1.5,
            p_value=None,
            selected=False,
        )

        payload = build_chart_payload(task, "proteomics_volcano")

        self.assertEqual(payload["chartType"], "volcano")
        self.assertEqual(payload["thresholds"], {"log2FoldChange": 1.0, "pValue": 0.01})
        self.assertEqual(len(payload["data"]), 2)
        self.assertEqual(payload["data"][0]["label"], "TP53")
        self.assertEqual(payload["data"][0]["pValue"], 0.0)
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("不得交给 R", serialized)
        self.assertNotIn("不得发送", serialized)
        canonical = json.dumps(
            {key: value for key, value in payload.items() if key != "inputSha256"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(payload["inputSha256"], hashlib.sha256(canonical.encode()).hexdigest())

    @patch("apps.core.services.visualization.MAX_VOLCANO_POINTS", 2)
    def test_proteomics_volcano_payload_is_bounded_and_discloses_truncation(self):
        task = AnalysisTask.objects.create(
            owner=self.owner,
            task_type=AnalysisTask.TaskType.PROTEOMICS,
            status=AnalysisTask.Status.SUCCEEDED,
            result={"thresholds": {"log2FcMin": 1.0, "pValueMax": 0.05}},
        )
        ProteomicsRowResult.objects.bulk_create([
            ProteomicsRowResult(
                task=task,
                row_index=index,
                original_label=f"GENE{index}",
                mapping_status=ProteomicsRowResult.MappingStatus.UNMAPPED,
                log2_fold_change=float(index),
                p_value=0.01 * (index + 1),
                fdr=0.02 * (index + 1),
                selected=index == 0,
            )
            for index in range(3)
        ])

        payload = build_chart_payload(task, "proteomics_volcano")

        self.assertEqual(len(payload["data"]), 2)
        self.assertIn("展示 2/3 条", payload["subtitle"])
        self.assertIn("按筛选状态与显著性排序截取", payload["subtitle"])

    def test_proteomics_volcano_payload_trims_to_r_request_byte_limit(self):
        task = AnalysisTask.objects.create(
            owner=self.owner,
            task_type=AnalysisTask.TaskType.PROTEOMICS,
            status=AnalysisTask.Status.SUCCEEDED,
            result={"thresholds": {"log2FcMin": 1.0, "pValueMax": 0.05}},
        )
        ProteomicsRowResult.objects.bulk_create([
            ProteomicsRowResult(
                task=task,
                row_index=index,
                original_label=(f"GENE{index}" + "X" * 115),
                mapping_status=ProteomicsRowResult.MappingStatus.UNMAPPED,
                log2_fold_change=float(index),
                p_value=0.01 * (index + 1),
                fdr=0.02 * (index + 1),
                selected=index == 0,
            )
            for index in range(3)
        ])

        with patch("apps.core.services.visualization.MAX_R_VIZ_REQUEST_BYTES", 700):
            payload = build_chart_payload(task, "proteomics_volcano")

        self.assertLess(len(payload["data"]), 3)
        self.assertIn("受请求大小限制绘制", payload["subtitle"])
        self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False).encode("utf-8")), 700)

    def test_proteomics_volcano_payload_rejects_missing_statistical_rows(self):
        task = AnalysisTask.objects.create(
            owner=self.owner,
            task_type=AnalysisTask.TaskType.PROTEOMICS,
            status=AnalysisTask.Status.SUCCEEDED,
            result={"thresholds": {"log2FcMin": 1.0, "pValueMax": 0.05}},
        )

        with self.assertRaisesRegex(VisualizationInputError, "没有同时包含有效"):
            build_chart_payload(task, "proteomics_volcano")

    def test_go_kegg_bubble_payload_is_bounded_and_validates_each_term(self):
        terms = [
            {
                "name": f"GO term {index}",
                "source": "GO:BP" if index % 2 else "KEGG",
                "geneRatio": 0.1 + (index % 8) / 10,
                "adjustedPValue": 0.001 + index / 10000,
                "intersectionSize": index + 1,
                "matchedIdentifiers": ["SHOULD_NOT_BE_SENT"],
            }
            for index in range(105)
        ]
        terms.extend([
            {"name": "bad FDR", "source": "GO:BP", "geneRatio": 0.5, "adjustedPValue": 0.9, "intersectionSize": 1},
            {"name": "bad source", "source": "USER_INPUT", "geneRatio": 0.5, "adjustedPValue": 0.01, "intersectionSize": 1},
            {"name": "bad ratio", "source": "GO:BP", "geneRatio": 2, "adjustedPValue": 0.01, "intersectionSize": 1},
        ])
        task = AnalysisTask.objects.create(
            owner=self.owner,
            task_type=AnalysisTask.TaskType.PROTEOMICS,
            status=AnalysisTask.Status.SUCCEEDED,
            result={
                "privateCaseText": "不得交给 R 的医案文本",
                "externalGProfiler": {
                    "status": "succeeded",
                    "sourceVersion": "e114_eg62_test\n",
                    "terms": terms,
                },
            },
        )

        payload = build_chart_payload(task, "proteomics_go_kegg_enrichment")

        self.assertEqual(payload["chartType"], "enrichment_bubble")
        self.assertIn("e114_eg62_test", payload["subtitle"])
        self.assertNotIn("\n", payload["subtitle"])
        self.assertEqual(len(payload["data"]), 100)
        self.assertEqual(payload["data"][0]["source"], "KEGG")
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("不得交给 R", serialized)
        self.assertNotIn("SHOULD_NOT_BE_SENT", serialized)
        self.assertNotIn("bad FDR", serialized)
        canonical = json.dumps(
            {key: value for key, value in payload.items() if key != "inputSha256"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(payload["inputSha256"], hashlib.sha256(canonical.encode()).hexdigest())

    def test_go_kegg_bubble_payload_rejects_unfinished_or_empty_results(self):
        task = AnalysisTask.objects.create(
            owner=self.owner,
            task_type=AnalysisTask.TaskType.PROTEOMICS,
            status=AnalysisTask.Status.SUCCEEDED,
            result={"externalGProfiler": {"status": "no_significant_terms", "terms": []}},
        )
        with self.assertRaisesRegex(ValueError, "没有可绘制"):
            build_chart_payload(task, "proteomics_go_kegg_enrichment")

    @patch("apps.core.tasks.run_visualization_task.apply_async")
    @override_settings(R_VIZ_BASE_URL="http://r-viz:8001", R_VIZ_API_TOKEN="test-token")
    def test_visualization_job_is_queued_and_private(self, enqueue):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            reverse("analysis-task-visualizations", args=[self.parent.pk]),
            {"chartKey": "overlap"}, format="json",
        )
        self.assertEqual(response.status_code, 202)
        job = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertEqual(job.task_type, AnalysisTask.TaskType.VISUALIZATION)
        self.assertEqual(job.input_parameters["parentTaskId"], self.parent.pk)
        enqueue.assert_called_once_with(args=[job.pk])

        self.client.force_authenticate(self.other)
        private = self.client.get(reverse("analysis-task-detail", args=[job.pk]))
        self.assertEqual(private.status_code, 404)

    @patch("apps.core.tasks.run_visualization_task.apply_async")
    @override_settings(R_VIZ_BASE_URL="http://r-viz:8001", R_VIZ_API_TOKEN="test-token")
    def test_go_kegg_visualization_uses_the_existing_owner_scoped_task_queue(self, enqueue):
        parent = AnalysisTask.objects.create(
            owner=self.owner,
            created_by=self.owner,
            task_type=AnalysisTask.TaskType.PROTEOMICS,
            status=AnalysisTask.Status.SUCCEEDED,
            result={
                "externalGProfiler": {
                    "status": "succeeded",
                    "terms": [{
                        "name": "cellular response",
                        "source": "GO:BP",
                        "geneRatio": 0.4,
                        "adjustedPValue": 0.01,
                        "intersectionSize": 4,
                    }],
                },
            },
        )
        self.client.force_authenticate(self.other)
        denied = self.client.post(
            reverse("analysis-task-visualizations", args=[parent.pk]),
            {"chartKey": "proteomics_go_kegg_enrichment"},
            format="json",
        )
        self.assertEqual(denied.status_code, 404)

        self.client.force_authenticate(self.owner)
        response = self.client.post(
            reverse("analysis-task-visualizations", args=[parent.pk]),
            {"chartKey": "proteomics_go_kegg_enrichment"},
            format="json",
        )

        self.assertEqual(response.status_code, 202, response.data)
        job = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertEqual(job.input_parameters["parentTaskId"], parent.pk)
        self.assertEqual(job.input_parameters["chartKey"], "proteomics_go_kegg_enrichment")
        enqueue.assert_called_once_with(args=[job.pk])

        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(reverse("analysis-task-detail", args=[job.pk])).status_code, 404)

    @patch("apps.core.tasks.run_visualization_task.apply_async")
    @override_settings(R_VIZ_BASE_URL="http://r-viz:8001", R_VIZ_API_TOKEN="test-token")
    def test_worker_persists_bounded_private_artifacts_and_owner_gated_download(self, enqueue):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            reverse("analysis-task-visualizations", args=[self.parent.pk]),
            {"chartKey": "overlap"}, format="json",
        )
        self.assertEqual(response.status_code, 202, response.data)
        job = AnalysisTask.objects.get(pk=response.data["id"])
        enqueue.assert_called_once_with(args=[job.pk])
        formats = {
            "svg": (b"<svg></svg>", "image/svg+xml"),
            "pdf": (b"%PDF-test", "application/pdf"),
            "png": (b"\x89PNG\r\n\x1a\n", "image/png"),
            "html": (b"<!doctype html>", "text/html; charset=utf-8"),
        }

        def provider(payload):
            self.assertNotIn("病案中的敏感症状", json.dumps(payload, ensure_ascii=False))
            return {
                "rendererVersion": "fixture-r-0.1",
                "inputSha256": payload["inputSha256"],
                "artifacts": [
                    {"format": file_format, "mimeType": mime, "bytesBase64": base64.b64encode(data).decode()}
                    for file_format, (data, mime) in formats.items()
                ],
            }

        with tempfile.TemporaryDirectory() as media_dir, override_settings(MEDIA_ROOT=media_dir):
            with patch("apps.core.services.visualization._request_r_visualization", side_effect=provider):
                outcome = run_visualization_task.run(job.pk)
            job.refresh_from_db()
            self.assertEqual(outcome["status"], AnalysisTask.Status.SUCCEEDED)
            self.assertEqual(len(job.result["artifacts"]), 4)
            artifact = VisualizationArtifact.objects.get(render_task=job, file_format="svg")
            self.assertEqual(artifact.content_sha256, hashlib.sha256(formats["svg"][0]).hexdigest())

            self.client.force_authenticate(self.other)
            denied = self.client.get(reverse("analysis-artifact-download", args=[artifact.pk]))
            self.assertEqual(denied.status_code, 404)

            self.client.force_authenticate(self.owner)
            download = self.client.get(reverse("analysis-artifact-download", args=[artifact.pk]))
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download["Content-Disposition"].split(".")[-1].strip('"'), "svg")
