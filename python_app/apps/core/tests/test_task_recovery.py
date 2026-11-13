"""Synthetic interruption/recovery boundaries; no broker, models or external API.

These tests exercise durable state transitions and stale worker publication,
not operating-system process termination. The latter is an isolated rehearsal.
"""
from copy import deepcopy
from datetime import timedelta
from io import StringIO
import json
from threading import Event, Thread
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from billiard.exceptions import Terminated, TimeLimitExceeded, WorkerLostError
from celery.worker.request import Request
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.core.models import (
    AnalysisSnapshotRow, AnalysisTask, DataSource, KnowledgeEntity, MedicalCase,
    MedicalCaseCandidate, SourceRelease, SyncRun, VisualizationArtifact,
)
from apps.core.services.case_analysis import case_input_sha256
from apps.core.services.task_recovery import (
    TaskExecutionStopped, lock_running_analysis, mark_interrupted,
)
from apps.core.tasks import (
    run_case_analysis_task, run_complete_evidence_task, run_external_analysis_task,
    run_research_assistant_task, run_visualization_task,
)
from apps.proteomics.models import ProteomicsRowResult
from apps.proteomics.tasks import run_proteomics_task
from apps.sources.tasks import sync_source_run
from config.background_tasks import RecoverableRequest, RecoverableTask


class RecoveryFixtures:
    def setUp(self):
        super().setUp()
        self.owner = get_user_model().objects.create_user(username="synthetic-recovery-owner")
        self.source = DataSource.objects.create(
            slug="synthetic-recovery-source", name="合成中断测试来源", access_mode="manual",
        )
        self.release = SourceRelease.objects.create(
            source=self.source, version="synthetic-v1", checksum_sha256="a" * 64,
            metadata={"fixtureOnly": True},
        )

    def analysis(self, *, task_type="network", status="running", parameters=None, **extra):
        task = AnalysisTask.objects.create(
            owner=self.owner, created_by=self.owner, task_type=task_type, status=status,
            progress=37, started_at=timezone.now() - timedelta(hours=2),
            input_parameters=parameters or {"analysisKind": "network_pharmacology", "complete": True},
            result={"fixtureOnly": True, "immutableResult": ["原始合成结果"]}, **extra,
        )
        task.source_releases.add(self.release)
        AnalysisSnapshotRow.objects.create(task=task, table="entities", ordinal=0,
            payload={"fixtureOnly": True, "sourceReleaseId": self.release.pk})
        return task

    def sync(self, *, status="running", **extra):
        return SyncRun.objects.create(
            source=self.source, release=self.release, requested_by=self.owner, status=status,
            started_at=timezone.now() - timedelta(hours=2), records_seen=11, records_created=7,
            records_updated=3, records_retired=1, cursor="synthetic-cursor",
            preview_summary={"fixtureOnly": True, "mode": "preview"}, **extra,
        )

    def analysis_content(self, task):
        task.refresh_from_db()
        return {
            "owner": task.owner_id, "createdBy": task.created_by_id,
            "type": task.task_type, "dataset": task.dataset_id, "case": task.medical_case_id,
            "parent": task.parent_task_id, "input": deepcopy(task.input_parameters),
            "result": deepcopy(task.result), "started": task.started_at,
            "releases": list(task.source_releases.order_by("pk").values_list("pk", flat=True)),
            "rows": list(task.snapshot_rows.order_by("pk").values("table", "ordinal", "payload")),
        }

    def sync_content(self, run):
        run.refresh_from_db()
        return {name: deepcopy(getattr(run, name)) for name in (
            "source_id", "release_id", "requested_by_id", "trigger", "cursor", "started_at",
            "records_seen", "records_created", "records_updated", "records_retired", "preview_summary",
        )}

    def command(self, **options):
        output = StringIO()
        call_command("fail_interrupted_tasks", stdout=output, **options)
        return json.loads(output.getvalue())


class InterruptedTaskTransitionTests(RecoveryFixtures, TestCase):
    def test_all_six_analysis_callback_names_stop_only_the_matching_running_task(self):
        mappings = [
            ("core.complete_evidence", "network", {"analysisKind": "catalog_evidence", "complete": True}),
            ("core.analyze_medical_case", "case_link", {"analysisKind": "case_analysis"}),
            ("core.research_assistant", "research_assistant", {"analysisKind": "research_assistant"}),
            ("core.external_analysis", "network", {"analysisKind": "reactome_enrichment"}),
            ("core.render_visualization", "visualization", {"analysisKind": "visualization"}),
            ("proteomics.run_analysis", "proteomics", {"analysisKind": "proteomics"}),
        ]
        for name, kind, parameters in mappings:
            with self.subTest(name=name):
                task = self.analysis(task_type=kind, parameters=parameters)
                before = self.analysis_content(task)
                self.assertTrue(mark_interrupted(name, args=[task.pk], reason="worker_lost"))
                task.refresh_from_db()
                self.assertEqual(task.status, "failed")
                self.assertEqual(task.progress, 100)
                self.assertIsNotNone(task.finished_at)
                self.assertTrue(task.error_summary)
                self.assertEqual(self.analysis_content(task), before)

    def test_sync_callback_preserves_preview_counters_release_and_requester(self):
        run = self.sync(); before = self.sync_content(run)
        self.assertTrue(mark_interrupted("sources.sync_run", kwargs={"run_id": run.pk}, reason="hard_timeout"))
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertIsNotNone(run.finished_at)
        self.assertTrue(run.error_summary)
        self.assertEqual(self.sync_content(run), before)

    def test_repeat_failure_callback_is_idempotent(self):
        task = self.analysis(task_type="proteomics")
        self.assertTrue(mark_interrupted("proteomics.run_analysis", args=[task.pk]))
        task.refresh_from_db(); first = (task.finished_at, task.error_summary, task.progress)
        self.assertFalse(mark_interrupted("proteomics.run_analysis", args=[task.pk], reason="hard_timeout"))
        task.refresh_from_db()
        self.assertEqual((task.finished_at, task.error_summary, task.progress), first)

    def test_analysis_callback_accepts_the_real_task_id_keyword(self):
        task = self.analysis(task_type="proteomics")
        self.assertTrue(mark_interrupted("proteomics.run_analysis", kwargs={"task_id": task.pk}))
        task.refresh_from_db(); self.assertEqual(task.status, "failed")

    def test_queued_success_failed_and_cancelled_analysis_are_immutable(self):
        for status in ["queued", "succeeded", "failed", "cancelled"]:
            with self.subTest(status=status):
                task = self.analysis(task_type="proteomics", status=status,
                    error_summary="原有说明", finished_at=timezone.now())
                before = AnalysisTask.objects.values().get(pk=task.pk)
                self.assertFalse(mark_interrupted("proteomics.run_analysis", args=[task.pk]))
                self.assertEqual(AnalysisTask.objects.values().get(pk=task.pk), before)

    def test_pending_success_and_failed_sync_runs_are_immutable(self):
        for status in ["pending", "succeeded", "failed"]:
            with self.subTest(status=status):
                run = self.sync(status=status, error_summary="原有说明", finished_at=timezone.now())
                before = SyncRun.objects.values().get(pk=run.pk)
                self.assertFalse(mark_interrupted("sources.sync_run", args=[run.pk]))
                self.assertEqual(SyncRun.objects.values().get(pk=run.pk), before)

    def test_unknown_name_wrong_type_or_missing_id_never_stops_a_running_task(self):
        task = self.analysis(task_type="text_analysis")
        before = AnalysisTask.objects.values().get(pk=task.pk)
        for name, args in [("not.registered", [task.pk]), ("sources.schedule_previews", [task.pk]),
                ("core.analyze_medical_case", [task.pk]), ("proteomics.run_analysis", [task.pk]),
                ("core.complete_evidence", [task.pk]), ("core.render_visualization", [task.pk]),
                ("core.research_assistant", [task.pk]), ("core.external_analysis", [task.pk]),
                ("proteomics.run_analysis", [task.pk + 99999])]:
            with self.subTest(name=name, args=args):
                self.assertFalse(mark_interrupted(name, args=args))
                self.assertEqual(AnalysisTask.objects.values().get(pk=task.pk), before)

    def test_invalid_or_ambiguous_arguments_do_not_guess_an_id(self):
        task = self.analysis(task_type="proteomics")
        cases = [
            (None, None), ([], {}), ([True], None), ([False], None), ([0], None), ([-1], None),
            ([float(task.pk)], None), ([str(task.pk)], None), ([None], None), ([task.pk, 123], None),
            (task.pk, None), ({"task_id": task.pk}, None), (None, [task.pk]),
            ([], {"taskId": task.pk}), ([], {"task_id": True}),
            ([], {"task_id": task.pk, "unexpected": 1}),
            ([task.pk], {"task_id": task.pk + 1}),
        ]
        for args, kwargs in cases:
            with self.subTest(args=args, kwargs=kwargs):
                self.assertFalse(mark_interrupted("proteomics.run_analysis", args=args, kwargs=kwargs))
                task.refresh_from_db(); self.assertEqual(task.status, "running")

    def test_lock_running_analysis_accepts_running_and_refuses_all_other_states(self):
        task = self.analysis()
        with transaction.atomic():
            self.assertEqual(lock_running_analysis(task.pk).pk, task.pk)
        for status in ["queued", "succeeded", "failed", "cancelled"]:
            AnalysisTask.objects.filter(pk=task.pk).update(status=status)
            with self.subTest(status=status), transaction.atomic(), self.assertRaises(TaskExecutionStopped):
                lock_running_analysis(task.pk)
        with transaction.atomic(), self.assertRaises((TaskExecutionStopped, AnalysisTask.DoesNotExist)):
            lock_running_analysis(task.pk + 99999)


class RecoveryParentCallbackTests(TestCase):
    def request(self):
        request = object.__new__(RecoverableRequest)
        request.name = "proteomics.run_analysis"
        request._args = [123]
        request._kwargs = {}
        return request

    def test_only_hard_timeout_records_parent_interruption(self):
        request = self.request()
        with patch("config.background_tasks._record_interruption") as record, \
                patch.object(Request, "on_timeout", return_value="parent") as parent:
            self.assertEqual(request.on_timeout(True, 1080), "parent")
            record.assert_not_called()
            self.assertEqual(request.on_timeout(False, 1200), "parent")
            record.assert_called_once_with("proteomics.run_analysis", [123], {}, "hard_timeout")
            self.assertEqual(parent.call_count, 2)

    def test_parent_worker_loss_and_termination_callbacks_are_recorded(self):
        for exception, reason in [(WorkerLostError("synthetic loss"), "worker_lost"),
                (Terminated("synthetic termination"), "worker_lost"),
                (TimeLimitExceeded(1200), "hard_timeout")]:
            with self.subTest(exception=type(exception).__name__):
                request = self.request()
                with patch("config.background_tasks._record_interruption") as record, \
                        patch.object(Request, "on_failure", return_value="parent") as parent:
                    info = SimpleNamespace(exception=SimpleNamespace(exc=exception))
                    self.assertEqual(request.on_failure(info, send_failed_event=False), "parent")
                    record.assert_called_once_with("proteomics.run_analysis", [123], {}, reason)
                    parent.assert_called_once_with(info, send_failed_event=False, return_ok=False)

    def test_ordinary_parent_failure_is_delegated_without_guessing_worker_loss(self):
        request = self.request()
        with patch("config.background_tasks._record_interruption") as record, \
                patch.object(Request, "on_failure", return_value="parent"):
            self.assertEqual(request.on_failure(SimpleNamespace(exception=ValueError("synthetic"))), "parent")
            record.assert_not_called()

    def test_task_failure_hook_and_request_class_are_bound_for_all_persisted_workers(self):
        for worker in [run_complete_evidence_task, run_case_analysis_task, run_research_assistant_task,
                run_external_analysis_task, run_visualization_task, run_proteomics_task, sync_source_run]:
            with self.subTest(worker=worker.name):
                self.assertIsInstance(worker, RecoverableTask)
                self.assertEqual(worker.Request, "config.background_tasks:RecoverableRequest")
                self.assertFalse(worker.reject_on_worker_lost)
                with patch("config.background_tasks._record_interruption") as record:
                    worker.on_failure(ValueError("synthetic"), "synthetic-celery-id", [123], {}, None)
                    record.assert_called_once_with(worker.name, [123], {}, "worker_exception")


class ManualInterruptedTaskRecoveryTests(RecoveryFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.cutoff = timezone.now() - timedelta(hours=1)

    def test_default_dry_run_counts_both_kinds_without_writes(self):
        task = self.analysis(); run = self.sync()
        before_tasks = list(AnalysisTask.objects.values())
        before_syncs = list(SyncRun.objects.values())
        report = self.command(before=self.cutoff.isoformat())
        self.assertTrue(report["dryRun"])
        self.assertFalse(report["automaticRetry"])
        self.assertFalse(report["workersStoppedAutomaticallyVerified"])
        self.assertEqual(report["matched"], 2)
        self.assertEqual(report["updated"], 0)
        self.assertEqual(list(AnalysisTask.objects.values()), before_tasks)
        self.assertEqual(list(SyncRun.objects.values()), before_syncs)

    def test_apply_requires_explicit_confirmation_that_workers_are_stopped(self):
        task = self.analysis()
        with self.assertRaises(CommandError):
            self.command(before=self.cutoff.isoformat(), apply=True)
        task.refresh_from_db(); self.assertEqual(task.status, "running")

    def test_cutoff_is_required_timezone_aware_valid_and_in_the_past(self):
        self.analysis()
        for options in [{}, {"before": "not-a-date"}, {"before": "2020-01-01T00:00:00"},
                {"before": (timezone.now() + timedelta(days=1)).isoformat()}]:
            with self.subTest(options=options), self.assertRaises(CommandError):
                self.command(**options)
        self.assertEqual(AnalysisTask.objects.get().status, "running")

    def test_apply_only_changes_old_running_rows_and_keeps_provenance(self):
        old = self.analysis(); run = self.sync()
        before_task = self.analysis_content(old); before_run = self.sync_content(run)
        for status in ["queued", "succeeded", "failed", "cancelled"]:
            self.analysis(status=status)
        new = self.analysis()
        AnalysisTask.objects.filter(pk=new.pk).update(started_at=self.cutoff + timedelta(seconds=1))
        no_start = self.analysis()
        AnalysisTask.objects.filter(pk=no_start.pk).update(started_at=None)
        untouched = {row["id"]: row for row in AnalysisTask.objects.exclude(pk=old.pk).values()}
        report = self.command(before=self.cutoff.isoformat(), apply=True, workers_stopped=True)
        self.assertFalse(report["dryRun"])
        self.assertEqual(report["matched"], 2)
        self.assertEqual(report["updated"], 2)
        self.assertEqual(self.analysis_content(old), before_task)
        self.assertEqual(self.sync_content(run), before_run)
        self.assertEqual({row["id"]: row for row in AnalysisTask.objects.exclude(pk=old.pk).values()}, untouched)
        self.assertEqual(AnalysisTask.objects.count(), 7)
        self.assertEqual(SyncRun.objects.count(), 1)

    def test_kind_filter_and_inclusive_cutoff_do_not_touch_other_kind(self):
        task = self.analysis(); run = self.sync()
        AnalysisTask.objects.filter(pk=task.pk).update(started_at=self.cutoff)
        report = self.command(before=self.cutoff.isoformat(), kind="analysis", apply=True, workers_stopped=True)
        self.assertEqual(report["updated"], 1)
        task.refresh_from_db(); run.refresh_from_db()
        self.assertEqual(task.status, "failed"); self.assertEqual(run.status, "running")
        report = self.command(before=self.cutoff.isoformat(), kind="sync", apply=True, workers_stopped=True)
        self.assertEqual(report["updated"], 1)
        run.refresh_from_db(); self.assertEqual(run.status, "failed")
        self.assertEqual(self.command(before=self.cutoff.isoformat(), apply=True, workers_stopped=True)["updated"], 0)


class StaleWorkerPublicationTests(RecoveryFixtures, TestCase):
    def test_external_worker_cannot_claim_a_queued_proteomics_task(self):
        task = self.analysis(task_type="proteomics", status="queued",
            parameters={"analysisKind": "proteomics", "fixtureOnly": True})
        before = AnalysisTask.objects.values().get(pk=task.pk)
        with patch("apps.core.tasks.execute_external_analysis") as execute:
            outcome = run_external_analysis_task.run(task.pk)
        self.assertEqual(outcome["status"], "skipped")
        execute.assert_not_called()
        self.assertEqual(AnalysisTask.objects.values().get(pk=task.pk), before)

    def test_assistant_result_returning_after_failure_cannot_resurrect_or_overwrite(self):
        task = self.analysis(task_type="research_assistant", status="queued",
            parameters={"analysisKind": "research_assistant"})
        before = self.analysis_content(task)
        def response(stale):
            self.assertTrue(mark_interrupted("core.research_assistant", args=[stale.pk]))
            return {"fixtureOnly": True, "lateResult": "must not be published"}
        with patch("apps.core.tasks.run_research_assistant", side_effect=response):
            outcome = run_research_assistant_task.run(task.pk)
        self.assertEqual(outcome["status"], "skipped")
        task.refresh_from_db(); self.assertEqual(task.status, "failed")
        # Claiming the task sets started_at; research/provenance content is unchanged.
        after = self.analysis_content(task); before["started"] = after["started"]
        self.assertEqual(after, before)

    def test_proteomics_late_result_cannot_replace_or_add_row_results(self):
        task = self.analysis(task_type="proteomics", status="queued")
        existing = ProteomicsRowResult.objects.create(task=task, row_index=1,
            original_label="SYNTHETIC_OLD", mapping_status="unmapped")
        before_rows = list(ProteomicsRowResult.objects.values())
        def response(stale):
            self.assertTrue(mark_interrupted("proteomics.run_analysis", args=[stale.pk]))
            return ({"lateResult": True}, [ProteomicsRowResult(task=task, row_index=2,
                original_label="SYNTHETIC_LATE", mapping_status="unmapped")], [self.release.pk])
        with patch("apps.proteomics.tasks.run_proteomics_analysis", side_effect=response):
            outcome = run_proteomics_task.run(task.pk)
        self.assertEqual(outcome["status"], "skipped")
        self.assertEqual(list(ProteomicsRowResult.objects.values()), before_rows)
        self.assertTrue(ProteomicsRowResult.objects.filter(pk=existing.pk).exists())
        task.refresh_from_db(); self.assertEqual(task.status, "failed")

    def test_failed_task_cannot_be_reclaimed_by_any_worker(self):
        cases = [
            (run_complete_evidence_task, "network"), (run_case_analysis_task, "case_link"),
            (run_research_assistant_task, "research_assistant"), (run_external_analysis_task, "network"),
            (run_visualization_task, "visualization"), (run_proteomics_task, "proteomics"),
        ]
        for worker, kind in cases:
            with self.subTest(worker=worker.name):
                task = self.analysis(task_type=kind, status="failed")
                before = AnalysisTask.objects.values().get(pk=task.pk)
                self.assertEqual(worker.run(task.pk)["status"], "skipped")
                self.assertEqual(AnalysisTask.objects.values().get(pk=task.pk), before)
        run = self.sync(status="failed"); before = SyncRun.objects.values().get(pk=run.pk)
        self.assertEqual(sync_source_run.run(run.pk)["status"], "skipped")
        self.assertEqual(SyncRun.objects.values().get(pk=run.pk), before)

    def test_external_late_response_cannot_create_or_attach_a_source_release(self):
        task = self.analysis(status="queued", parameters={"analysisKind": "reactome_enrichment", "rawTargets": []})
        before_releases = list(SourceRelease.objects.values())
        before = self.analysis_content(task)
        def response(*args):
            self.assertTrue(mark_interrupted("core.external_analysis", args=[task.pk]))
            return ({"fixtureOnly": True}, "synthetic-late-version")
        with patch("apps.core.services.external_analysis._run_reactome", side_effect=response):
            outcome = run_external_analysis_task.run(task.pk)
        self.assertEqual(outcome["status"], "skipped")
        self.assertEqual(list(SourceRelease.objects.values()), before_releases)
        after = self.analysis_content(task); before["started"] = after["started"]
        self.assertEqual(after, before)

    def test_visualization_late_response_never_writes_artifact_file_or_record(self):
        from apps.core.services.visualization import FORMAT_MIME_TYPES, build_chart_payload
        parent = self.analysis(status="succeeded")
        parent.result = {"charts": {"overlap": [{"name": "合成类别", "value": 2}]}}
        parent.save(update_fields=["result"])
        payload = build_chart_payload(parent, "overlap")
        task = self.analysis(task_type="visualization", status="queued", parent_task=parent,
            parameters={"parentTaskId": parent.pk, "chartKey": "overlap", "inputSha256": payload["inputSha256"]})
        before = self.analysis_content(task)
        def response(*args):
            self.assertTrue(mark_interrupted("core.render_visualization", args=[task.pk]))
            return {"rendererVersion": "synthetic-v1", "artifacts": [
                {"format": fmt, "mimeType": mime, "bytesBase64": "c3ludGhldGlj"}
                for fmt, mime in FORMAT_MIME_TYPES.items()]}
        with patch("apps.core.services.visualization._request_r_visualization", side_effect=response), \
                patch("apps.core.services.visualization.default_storage.save") as storage:
            outcome = run_visualization_task.run(task.pk)
        self.assertEqual(outcome["status"], "skipped")
        storage.assert_not_called()
        self.assertEqual(VisualizationArtifact.objects.count(), 0)
        after = self.analysis_content(task); before["started"] = after["started"]
        self.assertEqual(after, before)

    def test_medical_case_late_response_cannot_add_candidates_or_publish_result(self):
        case = MedicalCase.objects.create(owner=self.owner, title="合成医案", deidentified_text="合成资料：咳嗽。")
        task = self.analysis(task_type="case_link", status="queued", medical_case=case,
            parameters={"analysisKind": "case_analysis", "caseContentSha256": case_input_sha256(case)})
        before = self.analysis_content(task)
        def response(*args):
            self.assertTrue(mark_interrupted("core.analyze_medical_case", args=[task.pk]))
            return {"observations": [{"type": "symptom", "value": "咳嗽",
                "evidence": [{"field": "deidentified_text", "quote": "咳嗽"}]}],
                "formulaCandidates": [{"name": "合成方剂", "confidence": 0.5,
                    "evidence": [{"field": "deidentified_text", "quote": "咳嗽"}]}]}
        with patch("apps.core.services.case_analysis._local_model_response", side_effect=response):
            outcome = run_case_analysis_task.run(task.pk)
        self.assertEqual(outcome["status"], "skipped")
        self.assertEqual(MedicalCaseCandidate.objects.count(), 0)
        after = self.analysis_content(task); before["started"] = after["started"]
        self.assertEqual(after, before)


class RecoveryAtomicPublishTests(RecoveryFixtures, TestCase):
    def test_local_sqlite_connector_rolls_back_partial_catalogue_and_counters_before_failure(self):
        from apps.sources.sqlite_sync import SQLITE_CONNECTOR
        for mode, target in [("preview", "preview_sqlite_sync"), ("apply", "apply_sqlite_sync")]:
            with self.subTest(mode=mode):
                run = self.sync(status="pending")
                run.preview_summary.update({"mode": mode, "connector": SQLITE_CONNECTOR})
                run.save(update_fields=["preview_summary"])
                before = self.sync_content(run)
                releases_before = SourceRelease.objects.count()
                def partial_write_then_fail(stale):
                    release = SourceRelease.objects.create(source=self.source,
                        version=f"synthetic-unpublished-{mode}")
                    KnowledgeEntity.objects.create(entity_type="herb",
                        stable_id=f"synthetic:unpublished:{mode}", label="不能发布的合成实体",
                        source_release=release)
                    stale.records_seen = 999
                    stale.preview_summary = {"partialWrite": True}
                    stale.save(update_fields=["records_seen", "preview_summary"])
                    raise RuntimeError("Synthetic interruption after a catalogue write")
                with patch(f"apps.sources.tasks.{target}", side_effect=partial_write_then_fail), \
                        self.assertLogs("apps.sources.tasks", level="ERROR"):
                    outcome = sync_source_run.run(run.pk)
                self.assertEqual(outcome["status"], "failed")
                run.refresh_from_db()
                self.assertEqual(run.status, "failed")
                self.assertIsNotNone(run.finished_at)
                self.assertTrue(run.error_summary)
                self.assertFalse(KnowledgeEntity.objects.filter(stable_id=f"synthetic:unpublished:{mode}").exists())
                self.assertEqual(SourceRelease.objects.count(), releases_before)
                after = self.sync_content(run); before["started_at"] = after["started_at"]
                self.assertEqual(after, before)

    def test_ambiguous_queue_confirmation_does_not_overwrite_an_already_published_success(self):
        from apps.core.exceptions import TaskQueueUnavailable
        from apps.core.services.external_analysis import _enqueue
        task = self.analysis(status="queued", parameters={"analysisKind": "reactome_enrichment"})
        published = {}
        def completed_before_confirmation_failed(*, args):
            self.assertEqual(args, [task.pk])
            AnalysisTask.objects.filter(pk=task.pk, status="queued").update(
                status="succeeded", progress=100, finished_at=timezone.now(),
                result={"fixtureOnly": True, "publishedBeforeQueueConfirmation": True})
            published.update(AnalysisTask.objects.values().get(pk=task.pk))
            raise ConnectionError("Synthetic queue acknowledgement was lost after delivery")
        with patch("apps.core.tasks.run_external_analysis_task.apply_async", side_effect=completed_before_confirmation_failed), \
                patch("apps.core.services.external_analysis.record_runtime_event"), \
                self.assertRaises(TaskQueueUnavailable):
            _enqueue(task)
        self.assertEqual(AnalysisTask.objects.values().get(pk=task.pk), published)
        self.assertEqual(AnalysisTask.objects.count(), 1)
        self.assertEqual(task.snapshot_rows.count(), 1)
        self.assertEqual(list(task.source_releases.values_list("pk", flat=True)), [self.release.pk])


class CompleteEvidenceStaleRecoveryTests(RecoveryFixtures, TransactionTestCase):
    def test_publication_lock_requires_an_explicit_callers_transaction(self):
        task = self.analysis()
        with self.assertRaises(RuntimeError):
            lock_running_analysis(task.pk)

    def test_complete_evidence_stale_object_cannot_publish_snapshot_rows(self):
        # This publisher explicitly starts REPEATABLE READ, so it must not run
        # inside the already-querying transaction held by Django TestCase.
        from apps.core.services.complete_evidence import execute_complete_evidence
        task = self.analysis(parameters={"analysisKind": "catalog_evidence", "complete": True})
        before = self.analysis_content(task)
        self.assertTrue(mark_interrupted("core.complete_evidence", args=[task.pk]))
        data = ({"fixtureOnly": True}, {"entities": [{"sourceReleaseId": self.release.pk}],
            "evidenceRecords": []})
        with patch("apps.core.services.complete_evidence._catalog_data", return_value=data), \
                self.assertRaises(TaskExecutionStopped):
            execute_complete_evidence(task)
        self.assertEqual(self.analysis_content(task), before)


@skipUnless(connection.vendor == "postgresql", "PostgreSQL row locks require separate connections")
class RecoveryRowLockTests(RecoveryFixtures, TransactionTestCase):
    def test_parent_interruption_callback_does_not_wait_for_a_childs_publication_lock(self):
        task = self.analysis(task_type="proteomics")
        acquired = Event(); release = Event(); callback_finished = Event()
        errors = []; outcomes = []
        def publisher():
            close_old_connections()
            try:
                with transaction.atomic():
                    lock_running_analysis(task.pk)
                    acquired.set()
                    if not release.wait(10):
                        raise AssertionError("Synthetic child publication lock was not released")
            except BaseException as exc:
                errors.append(exc); acquired.set()
            finally:
                close_old_connections()
        def parent_callback():
            close_old_connections()
            try:
                outcomes.append(mark_interrupted("proteomics.run_analysis", args=[task.pk], reason="hard_timeout"))
            except BaseException as exc:
                errors.append(exc)
            finally:
                callback_finished.set(); close_old_connections()
        child = Thread(target=publisher, daemon=True)
        callback = Thread(target=parent_callback, daemon=True)
        child.start()
        try:
            self.assertTrue(acquired.wait(10), "Child did not acquire its publication lock")
            self.assertEqual(errors, [])
            callback.start()
            # Completion while the child lock is still held is the boundary:
            # the parent must remain able to terminate the timed-out child.
            self.assertTrue(callback_finished.wait(2), "Parent callback waited on the child's task lock")
            self.assertEqual(errors, [])
            self.assertEqual(outcomes, [False])
            task.refresh_from_db(); self.assertEqual(task.status, "running")
        finally:
            release.set(); child.join(10)
            if callback.ident is not None:
                callback.join(10)
        self.assertFalse(child.is_alive())
        self.assertFalse(callback.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(mark_interrupted("proteomics.run_analysis", args=[task.pk], reason="hard_timeout"))
        task.refresh_from_db(); self.assertEqual(task.status, "failed")

    def test_manual_recovery_skips_a_row_still_locked_by_a_live_publisher(self):
        task = self.analysis()
        acquired = Event(); release = Event(); errors = []
        def publisher():
            close_old_connections()
            try:
                with transaction.atomic():
                    lock_running_analysis(task.pk)
                    acquired.set()
                    if not release.wait(10):
                        raise AssertionError("Synthetic publisher lock was not released")
            except BaseException as exc:
                errors.append(exc); acquired.set()
            finally:
                close_old_connections()
        thread = Thread(target=publisher, daemon=True); thread.start()
        try:
            self.assertTrue(acquired.wait(10), "Publisher did not acquire its row lock")
            self.assertEqual(errors, [])
            report = self.command(before=(timezone.now() - timedelta(hours=1)).isoformat(),
                kind="analysis", apply=True, workers_stopped=True)
            self.assertEqual(report["matched"], 1)
            self.assertEqual(report["updated"], 0)
            self.assertEqual(report["skippedLocked"], 1)
            task.refresh_from_db(); self.assertEqual(task.status, "running")
        finally:
            release.set(); thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
