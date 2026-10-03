"""Source deletion migrated from main keeps all version and sync provenance."""

import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import DataSource, KnowledgeEntity, SourceRelease, SyncRun


class SourceDeleteTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.admin = user_model.objects.create_user(
            username="delete-admin", is_staff=True, is_superuser=True
        )
        cls.researcher = user_model.objects.create_user(username="delete-researcher")
        cls.staff = user_model.objects.create_user(username="delete-staff", is_staff=True)

    def create_source(self, slug="delete-empty", **kwargs):
        return DataSource.objects.create(
            slug=slug,
            name="待删除的数据源登记",
            access_mode=DataSource.AccessMode.DOWNLOAD,
            **kwargs,
        )

    def delete_source(self, source, user=None):
        self.client.force_authenticate(user or self.admin)
        return self.client.delete(reverse("sync-source-delete", args=[source.pk]))

    def assert_conflict(self, response, source):
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"]["code"], "RESOURCE_CONFLICT")
        self.assertIn("溯源", response.data["error"]["message"])
        self.assertEqual(response.data["error"]["details"], {"sourceId": source.pk})
        self.assertEqual(response.data["error"]["requestId"], response["X-Request-ID"])
        self.assertTrue(DataSource.objects.filter(pk=source.pk).exists())

    def test_superuser_can_delete_unused_registration_without_touching_file_or_knowledge(self):
        entity = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.HERB,
            stable_id="delete-unrelated-herb",
            label="独立知识记录",
        )
        with tempfile.TemporaryDirectory() as directory:
            source_file = Path(directory) / "data_cache.db"
            source_file.write_bytes(b"source-file-must-remain")
            source = self.create_source(configuration={"databaseFile": str(source_file)})

            response = self.delete_source(source)

            self.assertEqual(response.status_code, 204)
            self.assertFalse(DataSource.objects.filter(pk=source.pk).exists())
            self.assertEqual(source_file.read_bytes(), b"source-file-must-remain")
        entity.refresh_from_db()
        self.assertEqual(entity.label, "独立知识记录")

    def test_researcher_and_staff_cannot_delete_registration(self):
        source = self.create_source()
        for user in [self.researcher, self.staff]:
            with self.subTest(user=user.username):
                response = self.delete_source(source, user)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.data["error"]["code"], "PERMISSION_DENIED")
                self.assertTrue(DataSource.objects.filter(pk=source.pk).exists())

    def test_anonymous_cannot_delete_registration(self):
        source = self.create_source()
        response = self.client.delete(reverse("sync-source-delete", args=[source.pk]))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["error"]["code"], "AUTHENTICATION_REQUIRED")
        self.assertTrue(DataSource.objects.filter(pk=source.pk).exists())

    def test_source_version_alone_prevents_deletion_even_without_knowledge_or_runs(self):
        source = self.create_source()
        release = SourceRelease.objects.create(source=source, version="test-version")

        self.assert_conflict(self.delete_source(source), source)

        self.assertTrue(SourceRelease.objects.filter(pk=release.pk).exists())

    def test_every_sync_status_preserves_history_even_without_version(self):
        for run_status in SyncRun.Status.values:
            with self.subTest(status=run_status):
                source = self.create_source(slug=f"delete-{run_status}")
                run = SyncRun.objects.create(
                    source=source, status=run_status, requested_by=self.admin
                )

                self.assert_conflict(self.delete_source(source), source)

                run.refresh_from_db()
                self.assertEqual(run.status, run_status)
                self.assertIsNone(run.release_id)

    def test_missing_source_returns_unified_not_found(self):
        self.client.force_authenticate(self.admin)
        response = self.client.delete(reverse("sync-source-delete", args=[999999]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"]["code"], "NOT_FOUND")
        self.assertTrue(response.data["error"]["requestId"])

    def test_session_authenticated_deletion_requires_csrf_then_accepts_valid_token(self):
        source = self.create_source()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        url = reverse("sync-source-delete", args=[source.pk])

        rejected = client.delete(url)

        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(rejected.json()["error"]["code"], "CSRF_FAILED")
        self.assertTrue(DataSource.objects.filter(pk=source.pk).exists())
        token = client.get("/api/v1/auth/csrf/").json()["csrfToken"]

        accepted = client.delete(url, HTTP_X_CSRFTOKEN=token)

        self.assertEqual(accepted.status_code, 204)
        self.assertFalse(DataSource.objects.filter(pk=source.pk).exists())
