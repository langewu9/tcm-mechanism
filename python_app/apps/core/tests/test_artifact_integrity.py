"""Temporary synthetic files only; no models, R service or work database."""
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, VisualizationArtifact


@override_settings(SECURE_SSL_REDIRECT=False)
class ArtifactIntegrityTests(APITestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.temp.name, STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": self.temp.name}},
        })
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        User = get_user_model()
        self.owner = User.objects.create_user(username="synthetic-integrity-owner")
        self.other = User.objects.create_user(username="synthetic-integrity-other")
        self.admin = User.objects.create_superuser(username="synthetic-integrity-admin", email="test@example.test")
        self.parent = AnalysisTask.objects.create(owner=self.owner, task_type="network", status="succeeded", result={})
        self.render = AnalysisTask.objects.create(owner=self.owner, task_type="visualization", status="succeeded",
            parent_task=self.parent, input_parameters={"analysisKind": "r_visualization", "chartKey": "overlap",
                "parentTaskId": self.parent.pk, "inputSha256": "a" * 64})
        self.content = b'<svg xmlns="http://www.w3.org/2000/svg"><text>SYNTHETIC</text></svg>'
        self.key = f"analysis-artifacts/{self.owner.pk}/{self.parent.pk}/{self.render.pk}/synthetic.svg"
        default_storage.save(self.key, ContentFile(self.content))
        self.artifact = VisualizationArtifact.objects.create(task=self.parent, render_task=self.render, owner=self.owner,
            chart_key="overlap", file_format="svg", filename="synthetic.svg", mime_type="image/svg+xml",
            storage_key=self.key, content_sha256=hashlib.sha256(self.content).hexdigest(), input_sha256="a" * 64,
            byte_size=len(self.content), renderer_version="synthetic-v1")
        self.publish_manifest()
        self.client.force_authenticate(self.owner)
        self.url = reverse("analysis-artifact-download", args=[self.artifact.pk])

    def publish_manifest(self):
        a = self.artifact
        self.render.result = {"status": "succeeded", "taskId": self.render.pk, "parentTaskId": self.parent.pk,
            "chartKey": "overlap", "inputSha256": "a" * 64, "rendererVersion": "synthetic-v1", "artifacts": [{
                "id": a.pk, "format": a.file_format, "filename": a.filename, "mimeType": a.mime_type,
                "sha256": a.content_sha256, "byteSize": a.byte_size, "rendererVersion": a.renderer_version,
                "downloadUrl": self.url if hasattr(self, "url") else reverse("analysis-artifact-download", args=[a.pk]),
            }]}
        self.render.save(update_fields=["result"])

    def assert_unavailable(self, response):
        self.assertEqual(response.status_code, 503, getattr(response, "data", None))
        self.assertFalse(response.streaming)
        self.assertEqual(response.data["error"]["code"], "ARTIFACT_UNAVAILABLE")
        self.assertNotIn(self.key, str(response.data))
        self.assertNotIn(self.temp.name, str(response.data))

    def test_verified_html_widget_remains_inline_in_an_opaque_sandbox(self):
        self.content = b"<!doctype html><html><body>Verified widget</body></html>"
        Path(self.temp.name, self.key).write_bytes(self.content)
        self.artifact.file_format = "html"
        self.artifact.filename = "synthetic.html"
        self.artifact.mime_type = "text/html; charset=utf-8"
        self.artifact.content_sha256 = hashlib.sha256(self.content).hexdigest()
        self.artifact.byte_size = len(self.content)
        self.artifact.save()
        self.publish_manifest()
        response = self.client.get(self.url, {"inline": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), self.content)
        self.assertIn("inline", response["Content-Disposition"])
        policy = response["Content-Security-Policy"]
        self.assertIn("sandbox allow-scripts allow-downloads", policy)
        self.assertIn("connect-src 'none'", policy)
        self.assertIn("frame-ancestors 'self'", policy)
        self.assertNotIn("allow-same-origin", policy)
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")
        Path(self.temp.name, self.key).write_bytes(b"X" * len(self.content))
        self.assert_unavailable(self.client.get(self.url, {"inline": "1"}))

    def test_same_size_corruption_is_not_served(self):
        Path(self.temp.name, self.key).write_bytes(b"X" * len(self.content))
        before = AnalysisTask.objects.get(pk=self.render.pk).result
        self.assert_unavailable(self.client.get(self.url))
        self.assertEqual(AnalysisTask.objects.get(pk=self.render.pk).result, before)
        self.assertEqual(VisualizationArtifact.objects.count(), 1)

    def test_unpublished_running_or_failed_residual_is_not_served(self):
        for state in ["queued", "running", "failed", "cancelled"]:
            AnalysisTask.objects.filter(pk=self.render.pk).update(status=state)
            self.assert_unavailable(self.client.get(self.url))
            self.assertEqual(AnalysisTask.objects.get(pk=self.render.pk).status, state)

    def test_missing_and_truncated_files_are_not_served(self):
        Path(self.temp.name, self.key).unlink()
        self.assert_unavailable(self.client.get(self.url))
        Path(self.temp.name, self.key).write_bytes(self.content[:-1])
        self.assert_unavailable(self.client.get(self.url))

    def test_owner_admin_and_legacy_binding_can_read_the_exact_verified_bytes(self):
        for account in [self.owner, self.admin]:
            self.client.force_authenticate(account)
            response = self.client.get(self.url, {"inline": "1"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), self.content)
            self.assertIn("inline", response["Content-Disposition"])
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.assertEqual(response["Content-Security-Policy"], "sandbox")
        AnalysisTask.objects.filter(pk=self.render.pk).update(parent_task=None)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), self.content)

    def test_permissions_are_checked_before_storage_access(self):
        self.client.force_authenticate(self.other)
        with patch.object(default_storage, "open", side_effect=AssertionError("Unauthorized storage read")):
            self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_invalid_manifest_and_owner_or_source_identity_are_rejected(self):
        original = self.render.result
        for field, value in [("taskId", self.parent.pk), ("parentTaskId", 99999), ("chartKey", "other"), ("inputSha256", "b" * 64), ("artifacts", [])]:
            AnalysisTask.objects.filter(pk=self.render.pk).update(result={**original, field: value})
            self.assert_unavailable(self.client.get(self.url))
        AnalysisTask.objects.filter(pk=self.render.pk).update(result=original, owner=self.other)
        self.assert_unavailable(self.client.get(self.url))

    def test_symlink_and_non_regular_file_are_not_followed(self):
        path = Path(self.temp.name, self.key)
        path.unlink()
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside, "outside.svg")
            target.write_bytes(self.content)
            path.symlink_to(target)
            self.assert_unavailable(self.client.get(self.url))
        path.unlink()
        path.mkdir()
        self.assert_unavailable(self.client.get(self.url))

    def test_manifest_file_size_and_content_type_must_match(self):
        original = self.render.result
        for field, value in [("id", True), ("byteSize", True), ("byteSize", len(self.content) + 1), ("sha256", "b" * 64), ("mimeType", "text/html"), ("downloadUrl", "https://invalid.example/file")]:
            manifest = {**original["artifacts"][0], field: value}
            AnalysisTask.objects.filter(pk=self.render.pk).update(result={**original, "artifacts": [manifest]})
            self.assert_unavailable(self.client.get(self.url))

    def test_response_uses_verified_copy_even_if_stored_file_changes_afterwards(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        Path(self.temp.name, self.key).write_bytes(b"X" * len(self.content))
        self.assertEqual(b"".join(response.streaming_content), self.content)

    def test_storage_adapter_is_opened_once_and_never_exceeds_the_artifact_limit(self):
        from io import BytesIO
        from apps.core.services.artifact_integrity import verified_artifact_bytes
        from apps.core.services.visualization import MAX_ARTIFACT_BYTES
        class SyntheticStorage:
            calls = 0
            def open(storage, key, mode):
                storage.calls += 1
                return BytesIO(self.content)
        storage = SyntheticStorage()
        self.assertEqual(verified_artifact_bytes(self.artifact, storage).read(), self.content)
        self.assertEqual(storage.calls, 1)
        self.artifact.byte_size = MAX_ARTIFACT_BYTES + 1
        self.artifact.save(update_fields=["byte_size"])
        self.assert_unavailable(self.client.get(self.url))
