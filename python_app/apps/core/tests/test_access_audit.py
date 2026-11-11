import hashlib
import json
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import DatabaseError
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import AnalysisTask, MedicalCase, ResearchDataset, SensitiveAccessEvent, VisualizationArtifact
from apps.core.services.access_audit import mark_sensitive_access


class SensitiveAccessAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.owner = users.objects.create_user(username="access-owner")
        cls.other = users.objects.create_user(username="access-other")
        cls.root = users.objects.create_superuser(username="access-root", email="root@example.test")
        cls.case = MedicalCase.objects.create(owner=cls.owner, title="PRIVATE_TITLE", deidentified_text="PRIVATE_CLINICAL_BODY")
        cls.dataset = ResearchDataset.objects.create(
            owner=cls.owner, name="PRIVATE_DATASET_NAME", original_filename="PRIVATE_FILENAME.csv",
            storage_key="synthetic/private.csv", content_sha256="a" * 64, byte_size=20,
        )
        cls.task = AnalysisTask.objects.create(
            owner=cls.owner, created_by=cls.owner, task_type="text_analysis", status="succeeded",
            medical_case=cls.case, input_parameters={"query": "PRIVATE_INPUT"},
            result={"query": "PRIVATE_RESULT", "evidence": {}, "algorithmVersion": "synthetic-v1",
                    "ruleSource": "synthetic", "sources": [], "evidenceRecords": []},
        )
        cls.other_task = AnalysisTask.objects.create(owner=cls.other, task_type="network")
        cls.artifact = VisualizationArtifact.objects.create(
            task=cls.task, render_task=cls.task, owner=cls.owner, chart_key="evidence_network",
            file_format="svg", storage_key="synthetic/private.svg", filename="PRIVATE_CHART.svg",
            mime_type="image/svg+xml", byte_size=6, content_sha256="b" * 64, input_sha256="c" * 64,
            renderer_version="synthetic-v1",
        )

    def setUp(self):
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        setting = override_settings(MEDIA_ROOT=media.name, STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": media.name}},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        })
        setting.enable()
        self.addCleanup(setting.disable)
        default_storage.save(self.dataset.storage_key, ContentFile(b"PRIVATE_FILE_CONTENT"))
        default_storage.save(self.artifact.storage_key, ContentFile(b"<svg/>"))
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_owner_detail_read_records_identity_resource_and_matching_request_id(self):
        response = self.api.get(reverse("case-detail", args=[self.case.pk]))
        self.assertEqual(response.status_code, 200)
        event = SensitiveAccessEvent.objects.get()
        self.assertEqual(event.actor, self.owner)
        self.assertEqual(event.operation, "case.retrieve")
        self.assertEqual(event.action, "view")
        self.assertEqual(str(event.request_id), response["X-Request-ID"])
        self.assertEqual(event.resources, [{"type": "case", "id": self.case.pk, "ownerId": self.owner.pk}])

    def test_list_audits_only_returned_owner_records_and_preserves_response_contract(self):
        response = self.api.get(reverse("analysis-task-summaries"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        event = SensitiveAccessEvent.objects.get()
        self.assertEqual(event.action, "list")
        self.assertEqual(event.resources, [{"type": "task", "id": self.task.pk, "ownerId": self.owner.pk}])

    def test_denied_and_invalid_reads_do_not_log_a_successful_access(self):
        self.api.force_authenticate(self.other)
        self.assertEqual(self.api.get(reverse("case-detail", args=[self.case.pk])).status_code, 404)
        self.api.force_authenticate(None)
        self.assertEqual(self.api.get(reverse("case-detail", args=[self.case.pk])).status_code, 401)
        self.assertFalse(SensitiveAccessEvent.objects.exists())

    def test_original_file_artifact_and_export_are_audited(self):
        # This test exercises access auditing on a valid published artifact.
        parent = AnalysisTask.objects.create(owner=self.owner, task_type="network", status="succeeded")
        render = AnalysisTask.objects.create(owner=self.owner, task_type="visualization", status="succeeded",
            parent_task=parent, input_parameters={"analysisKind": "r_visualization", "chartKey": "evidence_network",
                "parentTaskId": parent.pk, "inputSha256": "c" * 64})
        self.artifact.task = parent
        self.artifact.render_task = render
        self.artifact.content_sha256 = hashlib.sha256(b"<svg/>").hexdigest()
        self.artifact.save()
        render.result = {"taskId": render.pk, "parentTaskId": parent.pk, "chartKey": "evidence_network",
            "inputSha256": "c" * 64, "rendererVersion": "synthetic-v1", "artifacts": [{
                "id": self.artifact.pk, "format": "svg", "filename": self.artifact.filename,
                "mimeType": "image/svg+xml", "sha256": self.artifact.content_sha256, "byteSize": 6,
                "rendererVersion": "synthetic-v1",
                "downloadUrl": reverse("analysis-artifact-download", args=[self.artifact.pk]),
            }]}
        render.save(update_fields=["result"])
        requests = [
            (reverse("dataset-download", args=[self.dataset.pk]), "dataset.download", "download"),
            (reverse("analysis-artifact-download", args=[self.artifact.pk]), "artifact.download", "download"),
            (reverse("analysis-task-export", args=[self.task.pk]), "task.export", "export"),
        ]
        for url, operation, action in requests:
            with self.subTest(operation=operation):
                response = self.api.get(url)
                self.assertEqual(response.status_code, 200)
                event = SensitiveAccessEvent.objects.latest("id")
                self.assertEqual((event.operation, event.action), (operation, action))
                if response.streaming:
                    b"".join(response.streaming_content)

    def test_record_has_no_private_content_filename_query_or_credentials(self):
        response = self.api.get(reverse("dataset-detail", args=[self.dataset.pk]), {
            "q": "PRIVATE_SEARCH_TERM", "token": "PRIVATE_QUERY_TOKEN",
        }, HTTP_AUTHORIZATION="PRIVATE_AUTH_HEADER", HTTP_COOKIE="sessionid=PRIVATE_COOKIE")
        self.assertEqual(response.status_code, 200)
        event = SensitiveAccessEvent.objects.get()
        serialized = json.dumps({key: str(value) for key, value in event.__dict__.items()}, ensure_ascii=False)
        self.assertNotIn("PRIVATE_", serialized)

    def test_audit_failure_withholds_both_json_and_file_responses(self):
        for url in (reverse("case-detail", args=[self.case.pk]), reverse("dataset-download", args=[self.dataset.pk])):
            with self.subTest(url=url), patch(
                "config.access_audit.SensitiveAccessEvent.objects.create", side_effect=DatabaseError("PRIVATE_DB_ERROR"),
            ):
                response = self.api.get(url)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"]["code"], "ACCESS_AUDIT_UNAVAILABLE")
                self.assertNotIn(b"PRIVATE_", response.content)
                self.assertIn("no-store", response["Cache-Control"])

    def test_admin_reads_are_audited_and_audit_records_are_read_only(self):
        self.client.force_login(self.root)
        response = self.client.get(reverse("admin:core_medicalcase_change", args=[self.case.pk]))
        self.assertEqual(response.status_code, 200)
        event = SensitiveAccessEvent.objects.get()
        self.assertEqual((event.actor_id, event.channel, event.operation), (self.root.pk, "admin", "admin.medicalcase.view"))
        detail = reverse("admin:core_sensitiveaccessevent_change", args=[event.pk])
        self.assertEqual(self.client.get(detail).status_code, 200)
        self.assertEqual(self.client.post(detail, {"operation": "forged"}).status_code, 403)
        delete = reverse("admin:core_sensitiveaccessevent_delete", args=[event.pk])
        self.assertEqual(self.client.post(delete, {"post": "yes"}).status_code, 403)
        self.assertEqual(SensitiveAccessEvent.objects.count(), 1)

    def test_large_bulk_reference_list_is_bounded_and_explicitly_marked(self):
        request = RequestFactory().get("/")
        records = ({"type": "task", "id": number, "ownerId": self.owner.pk, "body": "PRIVATE_BODY"} for number in range(1, 1001))
        mark_sensitive_access(request, operation="task.list", action="list", resources=records)
        self.assertEqual(len(request.sensitive_access["resources"]), 250)
        self.assertTrue(request.sensitive_access["resources_truncated"])
        self.assertNotIn("PRIVATE_BODY", str(request.sensitive_access))
