"""Diagnostic access and storage use only temporary files/synthetic exceptions."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import DatabaseError
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AnalysisTask, SensitiveAccessEvent
from apps.core.tasks import run_case_analysis_task
from config.runtime_logs import query_runtime_events, record_runtime_event


SECRET = "SYNTHETIC_PASSWORD_COOKIE_MEDICAL_BODY"


class TemporaryLogsMixin:
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.setting = override_settings(RUNTIME_LOG_DIR=self.directory.name)
        self.setting.enable()
        self.addCleanup(self.setting.disable)


class RuntimeLogStorageTests(TemporaryLogsMixin, SimpleTestCase):
    def test_exception_details_are_allowlisted_before_writing(self):
        request = RequestFactory().post("/api/private/" + SECRET + "?token=" + SECRET, {"body": SECRET}, HTTP_COOKIE=SECRET)
        request.request_id = str(uuid.uuid4())
        try:
            raise RuntimeError(SECRET)
        except RuntimeError as exc:
            self.assertTrue(record_runtime_event("api.unhandled", request=request, exception=exc, status_code=500))
        raw = (Path(self.directory.name) / "events.jsonl").read_text()
        self.assertNotIn(SECRET, raw)
        self.assertNotIn(str(Path(__file__).parent), raw)
        data = query_runtime_events(request_id=request.request_id)
        event = data["results"][0]
        self.assertEqual(event["requestId"], request.request_id)
        self.assertEqual(event["exceptionType"], "RuntimeError")
        self.assertEqual(event["method"], "POST")
        self.assertTrue(event["frames"])
        self.assertEqual(set(event["frames"][0]), {"module", "function", "line"})

    def test_filters_and_bounded_results(self):
        stamp = timezone.now()
        record_runtime_event("case.rejected", task_id=7)
        record_runtime_event("case.failed", task_id=7)
        record_runtime_event("assistant.failed", task_id=8)
        data = query_runtime_events(limit=1)
        self.assertEqual(len(data["results"]), 1)
        self.assertTrue(data["hasMore"])
        self.assertFalse(data["scanTruncated"])
        filtered = query_runtime_events(task_id=7, level="warning", since=stamp)
        self.assertEqual([item["event"] for item in filtered["results"]], ["case.rejected"])
        self.assertEqual(query_runtime_events(task_id=99)["results"], [])
        self.assertEqual(query_runtime_events(since=timezone.now())["results"], [])

    def test_missing_store_is_empty_and_does_not_create_it(self):
        missing = Path(self.directory.name) / "not-created"
        with override_settings(RUNTIME_LOG_DIR=missing):
            self.assertEqual(query_runtime_events()["results"], [])
        self.assertFalse(missing.exists())

    def test_rotation_bounds_disk_and_query_marks_a_partial_window(self):
        with patch("config.runtime_logs.FILE_BYTES", 700), patch("config.runtime_logs.SCAN_BYTES", 600):
            for task_id in range(1, 31):
                self.assertTrue(record_runtime_event("case.failed", task_id=task_id))
            files = list(Path(self.directory.name).glob("events.jsonl*"))
            self.assertEqual(len(files), 4)
            self.assertLessEqual(sum(path.stat().st_size for path in files), 2800)
            data = query_runtime_events()
        self.assertTrue(data["scanTruncated"])
        self.assertEqual(data["results"][0]["taskId"], 30)
        self.assertEqual(query_runtime_events(task_id=1)["results"], [])

    def test_malformed_and_extra_fields_are_not_returned(self):
        record_runtime_event("case.failed", task_id=10)
        path = Path(self.directory.name) / "events.jsonl"
        raw = json.loads(path.read_text())
        raw.update(message=SECRET, traceback=SECRET, password=SECRET, frames=[{"module": SECRET + "/private", "function": "handler", "line": 1}])
        path.write_text(json.dumps(raw) + '\n{"event": []}\nnot-json\n')
        data = query_runtime_events()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["skippedRecords"], 2)
        self.assertNotIn(SECRET, json.dumps(data))
        self.assertEqual(data["results"][0]["frames"], [])

    def test_private_modes_and_symlink_refusal(self):
        record_runtime_event("case.failed", task_id=1)
        path = Path(self.directory.name) / "events.jsonl"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        path.unlink()
        target = Path(self.directory.name) / "private.txt"
        target.write_text(SECRET)
        path.symlink_to(target)
        self.assertFalse(record_runtime_event("case.failed", task_id=2))
        from config.runtime_logs import RuntimeLogUnavailable
        with self.assertRaises(RuntimeLogUnavailable):
            query_runtime_events()
        self.assertEqual(target.read_text(), SECRET)

    def test_lock_wait_is_bounded_and_writer_failure_does_not_raise(self):
        import fcntl
        lock = Path(self.directory.name) / ".lock"
        with lock.open("w") as output:
            fcntl.flock(output, fcntl.LOCK_EX)
            with patch("config.runtime_logs.LOCK_TIMEOUT", 0):
                self.assertFalse(record_runtime_event("case.failed", task_id=1))

    def test_parallel_writers_produce_complete_lines(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            stored = list(pool.map(lambda task_id: record_runtime_event("case.failed", task_id=task_id), range(1, 41)))
        self.assertTrue(all(stored))
        data = query_runtime_events()
        self.assertEqual({row["taskId"] for row in data["results"]}, set(range(1, 41)))
        self.assertEqual(data["skippedRecords"], 0)


class RuntimeLogAPITests(TemporaryLogsMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.researcher = users.objects.create_user(username="runtime-reader")
        cls.staff = users.objects.create_user(username="runtime-staff", is_staff=True)
        cls.staff.user_permissions.add(*Permission.objects.all())
        cls.root = users.objects.create_superuser(username="runtime-root", email="runtime@example.test")

    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.url = reverse("admin-runtime-logs")

    def test_anonymous_researcher_staff_inactive_and_nonstaff_superusers_are_denied(self):
        with patch("apps.core.views.runtime_logs.query_runtime_events") as read:
            self.assertEqual(self.api.get(self.url).status_code, 401)
            for user in (self.researcher, self.staff):
                self.api.force_authenticate(user)
                self.assertEqual(self.api.get(self.url).status_code, 403)
            for overrides in ({"is_active": False}, {"is_staff": False}):
                with patch.multiple(self.root, **overrides):
                    self.api.force_authenticate(self.root)
                    self.assertEqual(self.api.get(self.url).status_code, 403)
            read.assert_not_called()

    def test_admin_session_can_query_filtered_json_and_access_is_audited(self):
        self.api.force_login(self.root)
        record_runtime_event("case.failed", task_id=7)
        record_runtime_event("case.failed", task_id=8)
        response = self.api.get(self.url, {"task_id": 7, "limit": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual([item["taskId"] for item in response.data["results"]], [7])
        self.assertIn("no-store", response["Cache-Control"])
        audit = SensitiveAccessEvent.objects.get(operation="runtime_logs.query")
        self.assertEqual(audit.actor_id, self.root.pk)
        self.assertEqual(str(audit.request_id), response["X-Request-ID"])
        self.assertEqual(audit.resources, [])
        self.assertNotIn("task_id", json.dumps(audit.resources))
        home = self.api.get(reverse("admin:index"))
        self.assertContains(home, self.url)

    def test_invalid_unknown_duplicate_and_path_parameters_are_rejected_before_io(self):
        self.api.force_authenticate(self.root)
        with patch("apps.core.views.runtime_logs.query_runtime_events") as read:
            for query in ("limit=0", "limit=101", "limit=bad", "task_id=-1", "task_id=9223372036854775808", "request_id=bad", "since=bad", "level=debug", "path=../../.env", "limit=1&limit=2"):
                with self.subTest(query=query):
                    self.assertEqual(self.api.get(self.url + "?" + query).status_code, 400)
            read.assert_not_called()

    def test_mutating_methods_do_not_touch_the_store(self):
        self.api.force_authenticate(self.root)
        with patch("apps.core.views.runtime_logs.query_runtime_events") as read:
            for method in (self.api.post, self.api.put, self.api.patch, self.api.delete):
                self.assertEqual(method(self.url, {}, format="json").status_code, 405)
            read.assert_not_called()

    def test_disk_failure_is_safe_503_and_audit_failure_withholds_payload(self):
        self.api.force_authenticate(self.root)
        from config.runtime_logs import RuntimeLogUnavailable
        with patch("apps.core.views.runtime_logs.query_runtime_events", side_effect=RuntimeLogUnavailable(SECRET)):
            response = self.api.get(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(SECRET, response.content.decode())
        record_runtime_event("case.failed", task_id=7)
        with patch("config.access_audit.SensitiveAccessEvent.objects.create", side_effect=DatabaseError(SECRET)):
            response = self.api.get(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "ACCESS_AUDIT_UNAVAILABLE")
        self.assertNotIn('"taskId"', response.content.decode())
        self.assertNotIn(SECRET, response.content.decode())

    def test_worker_failure_is_correlated_without_changing_failed_task_behavior(self):
        task = AnalysisTask.objects.create(owner=self.researcher, task_type="case_link", status="queued")
        with patch("apps.core.tasks.run_case_analysis", side_effect=RuntimeError(SECRET)):
            result = run_case_analysis_task(task.pk)
        self.assertEqual(result["status"], "failed")
        task.refresh_from_db()
        self.assertNotIn(SECRET, task.error_summary)
        self.assertEqual(query_runtime_events(task_id=task.pk)["results"][0]["event"], "case.failed")
        # Diagnostic storage failure never prevents the existing task state update.
        task.status = "queued"
        task.save(update_fields=["status"])
        with patch("config.runtime_logs._locked", side_effect=OSError(SECRET)), patch("apps.core.tasks.run_case_analysis", side_effect=RuntimeError(SECRET)):
            self.assertEqual(run_case_analysis_task(task.pk)["status"], "failed")

    def test_proteomics_and_dispatch_failures_are_correlated_without_external_calls(self):
        from apps.core.exceptions import TaskQueueUnavailable
        from apps.core.services.external_analysis import _enqueue
        from apps.proteomics.tasks import run_proteomics_task

        task = AnalysisTask.objects.create(owner=self.researcher, task_type="proteomics", status="queued")
        with patch("apps.proteomics.tasks.run_proteomics_analysis", side_effect=RuntimeError(SECRET)):
            self.assertEqual(run_proteomics_task(task.pk)["status"], "failed")
        self.assertEqual(query_runtime_events(task_id=task.pk)["results"][0]["event"], "proteomics.failed")
        with patch("apps.core.tasks.run_external_analysis_task.apply_async", side_effect=OSError(SECRET)):
            with self.assertRaises(TaskQueueUnavailable):
                _enqueue(task)
        self.assertEqual(query_runtime_events(task_id=task.pk)["results"][0]["event"], "task.queue_unavailable")
        self.assertNotIn(SECRET, (Path(self.directory.name) / "events.jsonl").read_text())

    @override_settings(ROOT_URLCONF="apps.core.tests.test_framework_hardening")
    def test_api_failure_records_one_event_and_returns_only_safe_public_error(self):
        self.api.raise_request_exception = False
        response = self.api.get("/api/broken/?password=" + SECRET)
        self.assertEqual(response.status_code, 500)
        request_id = response["X-Request-ID"]
        events = query_runtime_events(request_id=request_id)["results"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "api.unhandled")
        self.assertEqual(events[0]["exceptionType"], "RuntimeError")
        self.assertNotIn(SECRET, json.dumps(events))
        self.assertNotIn("SYNTHETIC_PRIVATE_EXCEPTION", json.dumps(events))
