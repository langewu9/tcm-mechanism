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
from apps.core.services.visualization import build_chart_payload
from apps.core.tasks import run_visualization_task


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
