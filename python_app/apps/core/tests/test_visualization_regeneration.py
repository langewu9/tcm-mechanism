"""Explicit R reruns retain historical tasks, files and verified downloads."""
import base64
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, VisualizationArtifact
from apps.core.services.visualization import FORMAT_MIME_TYPES
from apps.core.tasks import run_visualization_task


OMITTED = object()


@override_settings(R_VIZ_BASE_URL="http://synthetic-r.test", R_VIZ_API_TOKEN="synthetic-token", SECURE_SSL_REDIRECT=False)
class VisualizationRegenerationTests(APITestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        storage = override_settings(MEDIA_ROOT=self.directory.name, STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": self.directory.name}},
        })
        storage.enable()
        self.addCleanup(storage.disable)
        enqueue = patch("apps.core.tasks.run_visualization_task.apply_async")
        self.enqueue = enqueue.start()
        self.addCleanup(enqueue.stop)
        users = get_user_model()
        self.owner = users.objects.create_user(username="rerun-owner")
        self.other = users.objects.create_user(username="rerun-other")
        self.parent = AnalysisTask.objects.create(owner=self.owner, created_by=self.owner,
            task_type="network", status="succeeded", result={"charts": {"overlap": [{"name": "Synthetic targets", "value": 2}]}})
        self.client.force_authenticate(self.owner)
        self.url = reverse("analysis-task-visualizations", args=[self.parent.pk])

    def submit(self, regenerate=OMITTED, **extra):
        data = {"chartKey": "overlap", **extra}
        if regenerate is not OMITTED:
            data["regenerate"] = regenerate
        return self.client.post(self.url, data, format="json")

    def provider(self, version):
        def render(payload):
            content = {"svg": b"<svg>" + version.encode() + b"</svg>",
                       "pdf": b"%PDF-1.7\n" + version.encode(),
                       "png": b"\x89PNG\r\n\x1a\n" + version.encode(),
                       "html": b"<!doctype html><html>" + version.encode() + b"</html>"}
            return {"rendererVersion": version, "inputSha256": payload["inputSha256"], "artifacts": [
                {"format": fmt, "mimeType": mime, "bytesBase64": base64.b64encode(content[fmt]).decode()}
                for fmt, mime in FORMAT_MIME_TYPES.items()]}
        return render

    def complete(self, job_id, version="r-viz-0.3.0"):
        with patch("apps.core.services.visualization._request_r_visualization", side_effect=self.provider(version)) as render:
            outcome = run_visualization_task.run(job_id)
        self.assertEqual(outcome["status"], "succeeded")
        render.assert_called_once()
        return AnalysisTask.objects.get(pk=job_id)

    def old_success(self):
        response = self.submit()
        self.assertEqual(response.status_code, 202, response.data)
        return self.complete(response.data["id"])

    def file_bytes(self, job):
        return {artifact.storage_key: Path(self.directory.name, artifact.storage_key).read_bytes()
                for artifact in job.rendered_artifacts.all()}

    def test_omitted_and_false_flags_reuse_success_without_contacting_r(self):
        old = self.old_success()
        with patch("apps.core.services.visualization._request_r_visualization") as render:
            for flag in (OMITTED, False):
                response = self.submit(flag)
                self.assertEqual((response.status_code, response.data["id"]), (200, old.pk))
        render.assert_not_called()
        self.assertEqual(self.enqueue.call_count, 1)

    def test_multiple_real_worker_generations_keep_old_files_and_unchanged_input_hash(self):
        old = self.old_success()
        old_result, old_files = old.result, self.file_bytes(old)
        old_records = list(old.rendered_artifacts.order_by("pk").values())
        self.parent.refresh_from_db()
        parent_result = self.parent.result
        previous = old
        for expected_count in (8, 12):
            response = self.submit(True, previousRenderTaskId=999999)
            self.assertEqual(response.status_code, 202, response.data)
            params = response.data["input_parameters"]
            self.assertTrue(params["regenerate"])
            self.assertEqual(params["previousRenderTaskId"], previous.pk)
            self.assertEqual(params["inputSha256"], old.input_parameters["inputSha256"])
            history = self.client.get(reverse("analysis-task-detail", args=[params["previousRenderTaskId"]]))
            self.assertEqual(history.status_code, 200)
            self.assertEqual(history.data["result"], previous.result)
            new = self.complete(response.data["id"], "r-viz-0.4.2")
            self.assertEqual(new.result["rendererVersion"], "r-viz-0.4.2")
            self.assertEqual(VisualizationArtifact.objects.count(), expected_count)
            self.assertTrue(set(old_files).isdisjoint(self.file_bytes(new)))
            previous = new
        old.refresh_from_db()
        self.parent.refresh_from_db()
        self.assertEqual(old.result, old_result)
        self.assertEqual(self.parent.result, parent_result)
        self.assertEqual(list(old.rendered_artifacts.order_by("pk").values()), old_records)
        self.assertEqual(self.file_bytes(old), old_files)
        for artifact in VisualizationArtifact.objects.all():
            with default_storage.open(artifact.storage_key, "rb") as stream:
                data = stream.read()
            self.assertEqual((len(data), hashlib.sha256(data).hexdigest()), (artifact.byte_size, artifact.content_sha256))
            response = self.client.get(reverse("analysis-artifact-download", args=[artifact.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), data)
        self.assertEqual(self.enqueue.call_count, 3)
        self.assertEqual(self.submit().data["id"], previous.pk)

    def test_queued_and_running_rerun_is_reused_before_older_success(self):
        old = self.old_success()
        response = self.submit(True)
        self.assertEqual(response.status_code, 202)
        pending = AnalysisTask.objects.get(pk=response.data["id"])
        parameters = pending.input_parameters
        for state in ("queued", "running"):
            AnalysisTask.objects.filter(pk=pending.pk).update(status=state)
            for flag in (OMITTED, False, True):
                with self.subTest(state=state, flag=flag):
                    repeat = self.submit(flag)
                    self.assertEqual((repeat.status_code, repeat.data["id"]), (200, pending.pk))
                    self.assertEqual(repeat.data["input_parameters"], parameters)
        self.assertEqual(parameters["previousRenderTaskId"], old.pk)
        self.assertEqual(self.enqueue.call_count, 2)
        self.assertEqual(AnalysisTask.objects.filter(parent_task=self.parent).count(), 2)

    def test_first_explicit_rerun_has_no_previous_success_and_pending_is_shared(self):
        response = self.submit(True)
        self.assertEqual(response.status_code, 202)
        self.assertIsNone(response.data["input_parameters"]["previousRenderTaskId"])
        self.assertEqual(self.submit(True).data["id"], response.data["id"])
        self.assertEqual(self.enqueue.call_count, 1)

    def test_history_pointer_survives_a_changed_adapter_payload_hash(self):
        old = self.old_success()
        self.parent.result = {"charts": {"overlap": [{"name": "Different immutable fixture", "value": 3}]}}
        self.parent.save(update_fields=["result"])
        response = self.submit(True)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["input_parameters"]["previousRenderTaskId"], old.pk)
        self.assertNotEqual(response.data["input_parameters"]["inputSha256"], old.input_parameters["inputSha256"])

    def test_only_pending_jobs_with_the_same_input_hash_are_reused(self):
        old = self.old_success()
        stale = self.submit(True)
        self.assertEqual(stale.status_code, 202)
        self.parent.result = {"charts": {"overlap": [{"name": "Changed adapter input", "value": 3}]}}
        self.parent.save(update_fields=["result"])
        current = self.submit(True)
        self.assertEqual(current.status_code, 202)
        self.assertNotEqual(current.data["id"], stale.data["id"])
        self.assertNotEqual(current.data["input_parameters"]["inputSha256"], stale.data["input_parameters"]["inputSha256"])
        self.assertEqual(current.data["input_parameters"]["previousRenderTaskId"], old.pk)
        for flag in (OMITTED, False, True):
            repeated = self.submit(flag)
            self.assertEqual((repeated.status_code, repeated.data["id"]), (200, current.data["id"]))
        self.assertEqual(self.enqueue.call_count, 3)

    def test_failed_rerun_retry_creates_another_job_and_keeps_success(self):
        old = self.old_success()
        old_files = self.file_bytes(old)
        response = self.submit(True)
        with patch("apps.core.services.visualization._request_r_visualization", side_effect=RuntimeError("Synthetic R unavailable")):
            self.assertEqual(run_visualization_task.run(response.data["id"])["status"], "failed")
        retry = self.submit(True)
        self.assertEqual(retry.status_code, 202)
        self.assertNotEqual(retry.data["id"], response.data["id"])
        self.assertEqual(retry.data["input_parameters"]["previousRenderTaskId"], old.pk)
        self.assertEqual(self.file_bytes(old), old_files)
        self.assertEqual(VisualizationArtifact.objects.count(), 4)

    def test_partial_new_storage_failure_only_removes_new_files(self):
        old = self.old_success()
        old_files = self.file_bytes(old)
        response = self.submit(True)
        save = default_storage.save
        writes = 0
        def fail_second(*args, **kwargs):
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("Synthetic storage failure")
            return save(*args, **kwargs)
        with patch("apps.core.services.visualization._request_r_visualization", side_effect=self.provider("r-viz-0.4.2")), \
                patch("apps.core.services.visualization.default_storage.save", side_effect=fail_second):
            self.assertEqual(run_visualization_task.run(response.data["id"])["status"], "failed")
        self.assertEqual(VisualizationArtifact.objects.count(), 4)
        self.assertEqual(self.file_bytes(old), old_files)
        self.assertEqual({str(path.relative_to(self.directory.name)) for path in Path(self.directory.name).rglob("*") if path.is_file()}, set(old_files))

    def test_cancelled_new_generation_never_publishes_or_changes_old_generation(self):
        old = self.old_success()
        old_result, old_files = old.result, self.file_bytes(old)
        response = self.submit(True)
        new_id = response.data["id"]
        def cancelled(payload):
            AnalysisTask.objects.filter(pk=new_id, status="running").update(status="cancelled")
            return self.provider("r-viz-0.4.2")(payload)
        with patch("apps.core.services.visualization._request_r_visualization", side_effect=cancelled), \
                patch("apps.core.services.visualization.default_storage.save") as save:
            self.assertEqual(run_visualization_task.run(new_id)["status"], "skipped")
        save.assert_not_called()
        self.assertEqual(AnalysisTask.objects.get(pk=new_id).status, "cancelled")
        self.assertEqual(run_visualization_task.run(new_id)["status"], "skipped")
        old.refresh_from_db()
        self.assertEqual(old.result, old_result)
        self.assertEqual(self.file_bytes(old), old_files)
        self.assertEqual(VisualizationArtifact.objects.count(), 4)

    def test_rerun_respects_authentication_and_owner_scope(self):
        old = self.old_success()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.submit(True).status_code, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.submit(True).status_code, 401)
        self.assertEqual(AnalysisTask.objects.filter(parent_task=self.parent).count(), 1)
        self.assertEqual(VisualizationArtifact.objects.filter(render_task=old).count(), 4)
        self.assertEqual(self.enqueue.call_count, 1)

    def test_admin_rerun_keeps_parent_owner_and_records_actual_creator(self):
        old = self.old_success()
        admin = get_user_model().objects.create_superuser(username="rerun-admin", email="rerun-admin@example.test")
        self.client.force_authenticate(admin)
        response = self.submit(True)
        self.assertEqual(response.status_code, 202)
        job = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertEqual((job.owner_id, job.created_by_id), (self.owner.pk, admin.pk))
        self.assertEqual(job.input_parameters["previousRenderTaskId"], old.pk)

    def test_invalid_regenerate_values_are_rejected_without_creating_a_job(self):
        for flag in (None, "sometimes", [], {}, 2):
            with self.subTest(flag=flag):
                response = self.submit(flag)
                self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(AnalysisTask.objects.filter(parent_task=self.parent).exists())
        self.enqueue.assert_not_called()


class VisualizationArtifactIdentityMigrationTests(TransactionTestCase):
    old_target = [("core", "0029_merge_platform_and_snapshots")]
    new_target = [("core", "0030_visualization_render_artifact_identity")]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_migration_keeps_legacy_rows_hashes_and_allows_another_render_generation(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.old_target)
        old_apps = executor.loader.project_state(self.old_target).apps
        User, Task, Artifact = [old_apps.get_model(app, name) for app, name in (
            ("auth", "User"), ("core", "AnalysisTask"), ("core", "VisualizationArtifact"))]
        owner = User.objects.create(username="artifact-migration-owner")
        parent = Task.objects.create(owner_id=owner.pk, task_type="network", status="succeeded")
        render = Task.objects.create(owner_id=owner.pk, parent_task_id=parent.pk, task_type="visualization", status="succeeded")
        for fmt, mime in FORMAT_MIME_TYPES.items():
            Artifact.objects.create(task_id=parent.pk, render_task_id=render.pk, owner_id=owner.pk,
                chart_key="overlap", file_format=fmt, filename=f"legacy.{fmt}", mime_type=mime,
                storage_key=f"legacy/{fmt}", input_sha256="a" * 64, content_sha256="b" * 64,
                byte_size=123, renderer_version="r-viz-0.3.0")
        before = list(Artifact.objects.order_by("pk").values())
        executor = MigrationExecutor(connection)
        executor.migrate(self.new_target)
        new_apps = executor.loader.project_state(self.new_target).apps
        Task, Artifact = [new_apps.get_model("core", name) for name in ("AnalysisTask", "VisualizationArtifact")]
        self.assertEqual(list(Artifact.objects.order_by("pk").values()), before)
        later = Task.objects.create(owner_id=owner.pk, parent_task_id=parent.pk, task_type="visualization", status="succeeded")
        for fmt, mime in FORMAT_MIME_TYPES.items():
            Artifact.objects.create(task_id=parent.pk, render_task_id=later.pk, owner_id=owner.pk,
                chart_key="overlap", file_format=fmt, filename=f"rerun.{fmt}", mime_type=mime,
                storage_key=f"later/{fmt}", input_sha256="a" * 64, content_sha256="c" * 64,
                byte_size=124, renderer_version="r-viz-0.4.2")
        self.assertEqual(Artifact.objects.count(), 8)
        self.assertEqual(list(Artifact.objects.filter(render_task_id=render.pk).order_by("pk").values()), before)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Artifact.objects.create(task_id=parent.pk, render_task_id=later.pk, owner_id=owner.pk,
                chart_key="overlap", file_format="svg", filename="duplicate.svg", mime_type="image/svg+xml",
                storage_key="later/duplicate", input_sha256="d" * 64, content_sha256="e" * 64,
                byte_size=124, renderer_version="r-viz-0.4.2")
