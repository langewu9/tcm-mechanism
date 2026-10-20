from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.admin.models import CHANGE, LogEntry
import json
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from apps.core.models import DataSource, SourceRelease, SyncRun


class SourceSettingsTests(APITestCase):
    def setUp(self):
        self.source = DataSource.objects.get(slug="reactome")
        self.admin = get_user_model().objects.create_superuser(username="settings-admin", email="settings@example.test")
        self.researcher = get_user_model().objects.create_user(username="settings-reader")
        self.url = reverse("sync-source-delete", args=[self.source.pk])
        self.client.force_authenticate(self.admin)

    def test_save_schedule_and_disable_without_removing_history(self):
        run = SyncRun.objects.create(source=self.source, status=SyncRun.Status.SUCCEEDED)
        config = self.source.configuration
        response = self.client.patch(self.url, {"enabled": False, "refresh_interval_hours": 48}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["enabled"])
        self.assertEqual(response.data["refresh_interval_hours"], 48)
        self.source.refresh_from_db()
        self.assertEqual(self.source.configuration, config)
        self.assertTrue(SyncRun.objects.filter(pk=run.pk).exists())
        audit = LogEntry.objects.get(user=self.admin, object_id=str(self.source.pk))
        self.assertEqual(audit.action_flag, CHANGE)
        changes = json.loads(audit.change_message)[0]
        self.assertEqual(changes["after"], {"enabled": False, "refresh_interval_hours": 48})
        self.assertTrue(changes["before"]["enabled"])

    def test_null_interval_switches_to_manual_only(self):
        self.source.refresh_interval_hours = 24
        self.source.save()
        response = self.client.patch(self.url, {"refresh_interval_hours": None}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["refresh_interval_hours"])
        self.assertEqual(response.data["enabled"], self.source.enabled)

    def test_invalid_or_unsafe_fields_do_not_mutate_source(self):
        initial_interval = self.source.refresh_interval_hours
        for payload in [{}, {"refresh_interval_hours": 0}, {"refresh_interval_hours": -1},
                        {"refresh_interval_hours": 8761}, {"refresh_interval_hours": 1.5},
                        {"enabled": "invalid"}, {"enabled": False, "configuration": {"connector": "unsafe"}}]:
            with self.subTest(payload=payload):
                response = self.client.patch(self.url, payload, format="json")
                self.assertEqual(response.status_code, 400)
                self.source.refresh_from_db()
                self.assertTrue(self.source.enabled)
                self.assertEqual(self.source.refresh_interval_hours, initial_interval)

    def test_only_superuser_can_change_settings(self):
        for user in [None, self.researcher]:
            with self.subTest(user=user):
                self.client.force_authenticate(user)
                self.assertIn(self.client.patch(self.url, {"enabled": False}, format="json").status_code, [401, 403])

    def test_unknown_source_returns_404(self):
        response = self.client.patch(reverse("sync-source-delete", args=[999999]), {"enabled": False}, format="json")
        self.assertEqual(response.status_code, 404)

    def test_cookie_authenticated_settings_requires_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.admin)
        response = client.patch(self.url, {"enabled": False}, format="json")
        self.assertEqual(response.status_code, 403)
        token = client.get(reverse("auth-csrf")).data["csrfToken"]
        response = client.patch(self.url, {"enabled": False}, format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)

    @patch("apps.sources.tasks.sync_source_run.delay")
    def test_duplicate_preview_is_rejected_before_enqueue(self, delay):
        url = reverse("sync-source-preview", args=[self.source.pk])
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 202)
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"]["code"], "SOURCE_SYNC_ACTIVE")
        self.assertEqual(self.source.sync_runs.count(), 1)
        delay.assert_called_once()

    @patch("apps.sources.tasks.sync_source_run.delay")
    def test_running_or_scheduled_task_blocks_manual_preview(self, delay):
        for status in [SyncRun.Status.PENDING, SyncRun.Status.RUNNING]:
            with self.subTest(status=status):
                run = SyncRun.objects.create(source=self.source, status=status, trigger=SyncRun.Trigger.SCHEDULED)
                response = self.client.post(reverse("sync-source-preview", args=[self.source.pk]), {}, format="json")
                self.assertEqual(response.status_code, 409)
                run.status = SyncRun.Status.SUCCEEDED
                run.save()
        delay.assert_not_called()

    @patch("apps.sources.tasks.sync_source_run.delay")
    def test_active_source_task_blocks_apply_of_another_preview(self, delay):
        release = SourceRelease.objects.create(source=self.source, version="settings-test")
        preview = SyncRun.objects.create(source=self.source, release=release, cursor="a" * 64,
            status=SyncRun.Status.SUCCEEDED, preview_summary={"mode": "preview", "connector": "reactome-catalog"})
        SyncRun.objects.create(source=self.source)
        response = self.client.post(reverse("sync-run-apply", args=[preview.pk]), {}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"]["code"], "SOURCE_SYNC_ACTIVE")
        delay.assert_not_called()

    @override_settings(SOURCE_SCHEDULED_PREVIEWS_ENABLED=False)
    def test_saving_interval_does_not_enable_global_scheduler_or_enqueue(self):
        response = self.client.patch(self.url, {"refresh_interval_hours": 24}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["scheduled_previews_enabled"])
        self.assertFalse(self.source.sync_runs.exists())
