import hashlib
import tempfile
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.deletion import ProtectedError
from django.test import RequestFactory, override_settings
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from apps.core.models import AnalysisTask, MedicalCase, MedicalCaseAuditEvent, ResearchDataset, ResearchDatasetAuditEvent


class ResearchRetentionTests(APITestCase):
    def setUp(self):
        cache.clear()
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        self.addCleanup(settings.disable)
        User = get_user_model()
        self.owner = User.objects.create_user(username="retention-owner", password="test-password-123")
        self.other = User.objects.create_user(username="retention-other", password="test-password-123")
        self.admin = User.objects.create_superuser(username="retention-admin", email="retention-admin@example.test", password="test-password-123")
        self.client.force_authenticate(self.owner)
        self.contents = b"Gene,log2FC,FDR\nTP53,2,0.01\n"
        uploaded = self.client.post(reverse("dataset-list"), {
            "name": "Synthetic retention fixture", "file": SimpleUploadedFile("synthetic.csv", self.contents),
        }, format="multipart")
        self.assertEqual(uploaded.status_code, 201, uploaded.data)
        self.dataset = ResearchDataset.objects.get(pk=uploaded.data["id"])
        created = self.client.post(reverse("case-list"), {"title": "Synthetic retention case", "deidentified_text": "虚构测试文本", "source_reference": "SYNTHETIC"}, format="json")
        self.case = MedicalCase.objects.get(pk=created.data["id"])

    def archive(self, kind, record):
        response = self.client.delete(reverse(f"{kind}-detail", args=[record.pk]))
        self.assertEqual(response.status_code, 204)
        record.refresh_from_db()
        self.assertIsNotNone(record.archived_at)

    def test_dataset_archive_restore_preserves_original_rows_hash_and_provenance(self):
        original_id, key, sha = self.dataset.pk, self.dataset.storage_key, self.dataset.content_sha256
        task = AnalysisTask.objects.create(owner=self.owner, dataset=self.dataset, task_type="proteomics", status="succeeded", result={"synthetic": True})
        self.archive("dataset", self.dataset)
        self.assertEqual(self.dataset.archived_by_id, self.owner.pk)
        self.assertEqual(self.client.get(reverse("dataset-list")).data["count"], 0)
        self.assertEqual(self.client.get(reverse("dataset-list"), {"archived": "true"}).data["count"], 1)
        with default_storage.open(key, "rb") as original:
            self.assertEqual(original.read(), self.contents)
        self.assertEqual(sha, hashlib.sha256(self.contents).hexdigest())
        self.assertEqual(self.dataset.rows.count(), 1)
        task.refresh_from_db()
        self.assertEqual(task.dataset_id, original_id)
        self.assertEqual(task.result, {"synthetic": True})
        self.assertEqual(self.client.get(reverse("dataset-download", args=[original_id])).status_code, 200)
        for _ in range(2):
            response = self.client.post(reverse("dataset-restore", args=[original_id]))
            self.assertEqual(response.status_code, 200)
        self.dataset.refresh_from_db()
        self.assertIsNone(self.dataset.archived_at)
        self.assertEqual(self.dataset.storage_key, key)
        self.assertEqual(self.dataset.owner_id, self.owner.pk)
        self.assertEqual(list(self.dataset.audit_events.order_by("id").values_list("action", flat=True)), ["created", "archived", "restored"])

    def test_case_archive_keeps_text_audit_and_completed_task(self):
        task = AnalysisTask.objects.create(owner=self.owner, medical_case=self.case, task_type="case_link", status="succeeded")
        self.archive("case", self.case)
        self.assertEqual(self.case.deidentified_text, "虚构测试文本")
        self.assertEqual(task.medical_case_id, self.case.pk)
        event = MedicalCaseAuditEvent.objects.get(case=self.case, action="archived")
        self.assertEqual(event.actor_id, self.owner.pk)
        self.assertNotIn("虚构测试文本", str(event.content_hashes))
        self.assertEqual(self.client.get(reverse("case-list")).data["count"], 0)
        self.assertEqual(self.client.get(reverse("case-list"), {"archived": "true"}).data["count"], 1)
        self.assertEqual(self.client.post(reverse("case-restore", args=[self.case.pk])).status_code, 200)
        self.assertEqual(MedicalCaseAuditEvent.objects.filter(case=self.case, action="restored").count(), 1)

    def test_archived_records_and_all_actions_remain_private(self):
        self.archive("dataset", self.dataset)
        self.archive("case", self.case)
        self.client.force_authenticate(self.other)
        for kind, record in [("dataset", self.dataset), ("case", self.case)]:
            for state in ["false", "true", "all"]:
                self.assertEqual(self.client.get(reverse(f"{kind}-list"), {"archived": state}).data["count"], 0)
            for action in ["detail", "audit"]:
                self.assertEqual(self.client.get(reverse(f"{kind}-{action}", args=[record.pk])).status_code, 404)
            self.assertEqual(self.client.post(reverse(f"{kind}-restore", args=[record.pk])).status_code, 404)
            self.assertEqual(self.client.delete(reverse(f"{kind}-detail", args=[record.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("dataset-download", args=[self.dataset.pk])).status_code, 404)

    def test_admin_can_inspect_and_restore_all_archived_records_without_changing_owner(self):
        self.archive("dataset", self.dataset)
        self.archive("case", self.case)
        self.client.force_authenticate(self.admin)
        for kind, record in [("dataset", self.dataset), ("case", self.case)]:
            self.assertEqual(self.client.get(reverse(f"{kind}-list"), {"archived": "all"}).data["count"], 1)
            self.assertEqual(self.client.post(reverse(f"{kind}-restore", args=[record.pk])).status_code, 200)
            record.refresh_from_db()
            self.assertEqual(record.owner_id, self.owner.pk)
        self.assertEqual(self.dataset.audit_events.first().actor_id, self.admin.pk)

    def test_original_file_is_immutable_even_without_analysis_tasks(self):
        response = self.client.patch(reverse("dataset-detail", args=[self.dataset.pk]), {
            "file": SimpleUploadedFile("replacement.csv", b"id,value\nOTHER,42\n"),
        }, format="multipart")
        self.assertEqual(response.status_code, 409)
        with default_storage.open(self.dataset.storage_key, "rb") as original:
            self.assertEqual(original.read(), self.contents)

    def test_archived_records_cannot_be_edited_or_used_for_new_analysis(self):
        self.archive("dataset", self.dataset)
        self.archive("case", self.case)
        for kind, record in [("dataset", self.dataset), ("case", self.case)]:
            self.assertEqual(self.client.patch(reverse(f"{kind}-detail", args=[record.pk]), {"name": "changed"}, format="json").status_code, 404)
        self.assertEqual(self.client.post(reverse("dataset-analyze", args=[self.dataset.pk]), {}, format="json").status_code, 404)
        self.assertEqual(self.client.post(reverse("case-analysis", args=[self.case.pk]), {"confirmLocalModel": True}, format="json").status_code, 404)
        workspace = self.client.get(reverse("text-analysis"))
        self.assertEqual(workspace.data["cases"], [])
        self.assertEqual(self.client.post(reverse("text-analysis"), {"query": "测试", "caseId": self.case.pk}, format="json").status_code, 404)

    def test_orm_and_admin_cannot_hard_delete_retained_records(self):
        request = RequestFactory().get("/")
        request.user = self.admin
        for record in [self.dataset, self.case]:
            with self.assertRaises(ProtectedError):
                record.delete()
            with self.assertRaises(ProtectedError):
                type(record).objects.filter(pk=record.pk).delete()
            self.assertFalse(admin.site._registry[type(record)].has_delete_permission(request, record))
        self.assertFalse(admin.site._registry[ResearchDatasetAuditEvent].has_delete_permission(request))

    def test_repeated_archive_is_idempotent_and_client_cannot_set_archival_fields(self):
        response = self.client.patch(reverse("dataset-detail", args=[self.dataset.pk]), {"archived_at": "2026-10-01T00:00:00Z", "archived_by": self.other.pk, "owner_id": self.other.pk}, format="json")
        self.assertEqual(response.status_code, 200)
        self.dataset.refresh_from_db()
        self.assertIsNone(self.dataset.archived_at)
        self.assertEqual(self.dataset.owner_id, self.owner.pk)
        self.archive("dataset", self.dataset)
        self.archive("dataset", self.dataset)
        self.assertEqual(self.dataset.audit_events.filter(action="archived").count(), 1)

    def test_failed_audit_rolls_back_archival(self):
        from apps.core.services.research_retention import set_archived
        with patch("apps.core.services.research_retention.dataset_audit", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                set_archived(self.dataset, actor=self.owner, archived=True)
        self.dataset.refresh_from_db()
        self.assertIsNone(self.dataset.archived_at)
        self.assertTrue(default_storage.exists(self.dataset.storage_key))

    def test_archive_requires_session_csrf_and_bad_filter_has_unified_error(self):
        browser = APIClient(enforce_csrf_checks=True)
        browser.force_login(self.owner)
        response = browser.delete(reverse("dataset-detail", args=[self.dataset.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.data)
        response = self.client.get(reverse("dataset-list"), {"archived": "invalid"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.data)

    def test_dashboard_counts_exclude_archived_records(self):
        self.archive("dataset", self.dataset)
        self.archive("case", self.case)
        response = self.client.get(reverse("research-dashboard"))
        self.assertEqual(response.data["stats"]["datasets"], 0)
        self.assertEqual(response.data["stats"]["cases"], 0)

    def test_case_audit_keeps_operator_identity_after_restore(self):
        operator = get_user_model().objects.create_superuser(username="retention-case-operator", email="case-operator@example.test", password="test-password-123")
        self.client.force_authenticate(operator)
        self.archive("case", self.case)
        self.assertEqual(self.client.post(reverse("case-restore", args=[self.case.pk])).status_code, 200)
        with self.assertRaises(ProtectedError):
            operator.delete()
        self.assertEqual(MedicalCaseAuditEvent.objects.filter(case=self.case, actor=operator, action="restored").count(), 1)
