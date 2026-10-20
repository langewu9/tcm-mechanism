from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.models import DataSource, KnowledgeEntity, SyncRun
from apps.sources.scheduling import enqueue_due_previews
from apps.sources.services import REACTOME_CONNECTOR
from apps.sources.serializers import DataSourceSyncSerializer


@override_settings(SOURCE_SCHEDULED_PREVIEWS_ENABLED=True)
class ScheduledPreviewTests(TestCase):
    def setUp(self):
        DataSource.objects.all().update(enabled=False)
        self.source = DataSource.objects.create(
            slug="scheduled-reactome", name="Scheduled Reactome", access_mode="api",
            refresh_interval_hours=24, configuration={"connector": REACTOME_CONNECTOR},
        )

    def test_admin_source_contract_exposes_schedule_configuration(self):
        data = DataSourceSyncSerializer(self.source).data
        self.assertEqual(data["refresh_interval_hours"], 24)
        self.assertIsNone(data["last_preview_requested_at"])
        self.assertTrue(data["scheduled_previews_enabled"])

    @patch("apps.sources.tasks.sync_source_run.delay")
    def test_due_source_enqueues_only_preview_and_does_not_duplicate(self, delay):
        entity_count = KnowledgeEntity.objects.count()
        self.assertEqual(enqueue_due_previews()["queued"], 1)
        run = self.source.sync_runs.get()
        self.assertEqual(run.trigger, SyncRun.Trigger.SCHEDULED)
        self.assertEqual(run.preview_summary, {"mode": "preview", "connector": REACTOME_CONNECTOR})
        self.assertIsNone(run.requested_by_id)
        self.assertEqual(KnowledgeEntity.objects.count(), entity_count)
        self.assertEqual(enqueue_due_previews()["queued"], 0)
        delay.assert_called_once_with(run.pk)

    @patch("apps.sources.tasks.sync_source_run.delay")
    def test_recent_manual_run_prevents_scheduled_duplicate(self, delay):
        SyncRun.objects.create(source=self.source, status=SyncRun.Status.SUCCEEDED)
        self.assertEqual(enqueue_due_previews()["queued"], 0)
        delay.assert_not_called()

    @patch("apps.sources.tasks.sync_source_run.delay")
    def test_old_active_run_is_not_overlapped(self, delay):
        run = SyncRun.objects.create(source=self.source)
        SyncRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(days=2))
        self.assertEqual(enqueue_due_previews()["queued"], 0)
        delay.assert_not_called()

    @patch("apps.sources.tasks.sync_source_run.delay")
    def test_elapsed_interval_enqueues_again(self, delay):
        run = SyncRun.objects.create(source=self.source, status=SyncRun.Status.SUCCEEDED)
        SyncRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(days=2))
        self.assertEqual(enqueue_due_previews()["queued"], 1)

    @patch("apps.sources.tasks.sync_source_run.delay", side_effect=ConnectionError("broker offline"))
    def test_broker_failure_is_audited_and_backed_off(self, delay):
        self.assertEqual(enqueue_due_previews()["failed"], 1)
        run = self.source.sync_runs.get()
        self.assertEqual(run.status, SyncRun.Status.FAILED)
        self.source.refresh_from_db()
        self.assertIsNotNone(self.source.last_preview_requested_at)
        self.assertEqual(enqueue_due_previews()["failed"], 0)
        delay.assert_called_once()

    @override_settings(SOURCE_SCHEDULED_PREVIEWS_ENABLED=False)
    @patch("apps.sources.tasks.sync_source_run.delay")
    def test_disabled_feature_does_not_create_runs(self, delay):
        self.assertEqual(enqueue_due_previews(), {"queued": 0, "failed": 0, "skipped": 0})
        self.assertFalse(self.source.sync_runs.exists())
        delay.assert_not_called()

    @patch("apps.sources.tasks.sync_source_run.delay")
    def test_disabled_unscheduled_and_unsupported_sources_are_ignored(self, delay):
        for fields in [
            {"enabled": False}, {"refresh_interval_hours": None},
            {"refresh_interval_hours": 0}, {"configuration": {"connector": "unknown"}},
        ]:
            with self.subTest(fields=fields):
                DataSource.objects.filter(pk=self.source.pk).update(**fields)
                self.assertEqual(enqueue_due_previews()["queued"], 0)
                DataSource.objects.filter(pk=self.source.pk).update(
                    enabled=True, refresh_interval_hours=24,
                    configuration={"connector": REACTOME_CONNECTOR},
                )
        delay.assert_not_called()
