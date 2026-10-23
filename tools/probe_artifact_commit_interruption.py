"""Opt-in real process-exit probe using only a disposable SQLite DB and media.

The real chart persistence is executed; only R output is synthetic. Abrupt exit
after the first artifact INSERT skips Python cleanup and rolls back its DB
transaction, leaving a file for the read-only audit to identify. No work DB,
Redis, live API, model, scientific service or existing process is touched.
"""
import argparse
import base64
from datetime import timedelta
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "python_app"
SYNTHETIC = {"svg": b'<svg xmlns="http://www.w3.org/2000/svg"><text>SYNTHETIC CRASH PROBE</text></svg>',
    "pdf": b"%PDF-1.4\nSYNTHETIC SOFTWARE CHECK ONLY", "png": b"SYNTHETIC PNG BYTES", "html": b"<html>SYNTHETIC SOFTWARE CHECK ONLY</html>"}


def configure(directory):
    directory = Path(directory).resolve()
    if not (directory / "owned.json").is_file() or directory.name[:19] != "tcm-artifact-probe-":
        raise RuntimeError("Only this invocation's owned temporary workspace is allowed.")
    os.environ.update(DJANGO_SETTINGS_MODULE="config.settings", DJANGO_DEBUG="true",
        DJANGO_SECRET_KEY="synthetic-artifact-process-probe", DATABASE_URL="sqlite:///" + str(directory / "probe.sqlite3"),
        MEDIA_ROOT=str(directory / "media"), CACHE_URL="", CELERY_BROKER_URL="memory://",
        SOURCE_SCHEDULED_PREVIEWS_ENABLED="false", S3_STORAGE_ENABLED="false", CASE_MODEL_BASE_URL="",
        CASE_MODEL_API_KEY="", R_VIZ_BASE_URL="", R_VIZ_API_TOKEN="", DJANGO_ALLOWED_HOSTS="testserver,127.0.0.1",
        DJANGO_SECURE_SSL_REDIRECT="false", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        RUNTIME_LOG_DIR=str(directory / "runtime-logs"))
    sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.conf import settings
    if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3" or Path(settings.DATABASES["default"]["NAME"]) != directory / "probe.sqlite3":
        raise RuntimeError("Refusing any non-probe database.")


def r_response(payload):
    from apps.core.services.visualization import FORMAT_MIME_TYPES
    return {"rendererVersion": "synthetic-process-probe", "artifacts": [
        {"format": fmt, "mimeType": FORMAT_MIME_TYPES[fmt], "bytesBase64": base64.b64encode(content).decode()}
        for fmt, content in SYNTHETIC.items()]}


def crash_child(directory, task_id):
    configure(directory)
    from apps.core.models import AnalysisTask, VisualizationArtifact
    from apps.core.services.visualization import execute_visualization_task
    real_create = VisualizationArtifact.objects.create

    def inserted_then_exit(**fields):
        real_create(**fields)
        # Real process exit: no except/finally cleanup and no DB COMMIT.
        os._exit(73)

    with patch("urllib.request.urlopen", side_effect=AssertionError("No network in this probe")), patch(
            "apps.core.services.visualization._request_r_visualization", side_effect=r_response), patch.object(
            VisualizationArtifact.objects, "create", side_effect=inserted_then_exit):
        execute_visualization_task(AnalysisTask.objects.get(pk=task_id))
    raise RuntimeError("The child unexpectedly returned without the exit injection.")


def run_probe(directory):
    configure(directory)
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.db import connections
    from django.urls import reverse
    from django.utils import timezone
    from rest_framework.test import APIClient
    from apps.core.models import AnalysisTask, VisualizationArtifact
    from apps.core.services.result_file_audit import audit_result_files
    from apps.core.services.visualization import build_chart_payload, execute_visualization_task
    output = StringIO()
    call_command("migrate", interactive=False, verbosity=0, stdout=output)
    owner = get_user_model().objects.create_user(username="synthetic-probe-owner")
    other = get_user_model().objects.create_user(username="synthetic-probe-other")
    parent = AnalysisTask.objects.create(owner=owner, task_type="network", status="succeeded",
        result={"charts": {"overlap": [{"name": "SYNTHETIC", "value": 1}]}})
    payload = build_chart_payload(parent, "overlap")

    def new_render():
        return AnalysisTask.objects.create(owner=owner, task_type="visualization", parent_task=parent,
            status="running", started_at=timezone.now() - timedelta(minutes=2),
            input_parameters={"analysisKind": "r_visualization", "chartKey": "overlap",
                "parentTaskId": parent.pk, "inputSha256": payload["inputSha256"]})

    interrupted = new_render()
    connections.close_all()
    child = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child-crash", str(directory), str(interrupted.pk)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
    if child.returncode != 73:
        raise RuntimeError("Owned crash child did not reach the expected process-exit point.")
    interrupted.refresh_from_db()
    files = [path for path in (directory / "media").rglob("*") if path.is_file()]
    client = APIClient(); client.force_authenticate(owner)
    crash_report = audit_result_files()
    assertions = {
        "real_child_exit_73": child.returncode == 73,
        "artifact_insert_rolled_back": VisualizationArtifact.objects.count() == 0,
        "render_not_falsely_published": interrupted.status == "running" and interrupted.result == {},
        "one_unregistered_file_remains": len(files) == 1,
        "unregistered_file_not_downloadable_as_artifact": client.get(reverse("analysis-artifact-download", args=[1])).status_code == 404,
        "audit_reports_active_path_candidate": any(item["reason"] == "unregistered_path_with_active_task_id" for item in crash_report["findings"]),
    }
    orphan_sha = hashlib.sha256(files[0].read_bytes()).hexdigest() if len(files) == 1 else None
    cutoff = (timezone.now() - timedelta(seconds=1)).isoformat()
    preview = StringIO(); call_command("fail_interrupted_tasks", before=cutoff, kind="analysis", stdout=preview)
    interrupted.refresh_from_db()
    assertions["maintenance_preview_does_not_change_task"] = interrupted.status == "running" and json.loads(preview.getvalue())["updated"] == 0
    apply = StringIO(); call_command("fail_interrupted_tasks", before=cutoff, kind="analysis", apply=True, workers_stopped=True, stdout=apply)
    interrupted.refresh_from_db()
    assertions["explicit_maintenance_marks_failed_without_requeue"] = interrupted.status == "failed" and json.loads(apply.getvalue())["updated"] == 1
    assertions["maintenance_does_not_remove_or_change_file"] = bool(files and files[0].exists() and hashlib.sha256(files[0].read_bytes()).hexdigest() == orphan_sha)
    success = new_render()
    with patch("urllib.request.urlopen", side_effect=AssertionError("No network in this probe")), patch(
            "apps.core.services.visualization._request_r_visualization", side_effect=r_response):
        execute_visualization_task(success)
    success.refresh_from_db()
    assertions["success_control_commits_four_records"] = success.status == "succeeded" and VisualizationArtifact.objects.count() == 4
    for artifact in VisualizationArtifact.objects.all():
        response = client.get(reverse("analysis-artifact-download", args=[artifact.pk]), {"inline": "1"})
        content = b"".join(response.streaming_content) if response.status_code == 200 else b""
        assertions[f"verified_{artifact.file_format}_download"] = content == SYNTHETIC[artifact.file_format]
    client.force_authenticate(other)
    assertions["other_account_denied"] = client.get(reverse("analysis-artifact-download", args=[VisualizationArtifact.objects.first().pk])).status_code == 404
    final_audit = audit_result_files()
    assertions["final_inventory_complete_with_only_one_candidate"] = (final_audit["complete"] and final_audit["counters"]["unregisteredCandidates"] == 1
        and {item["reason"] for item in final_audit["findings"]} == {"unregistered_file_candidate"})
    connections.close_all()
    return {"schemaVersion": "artifact-commit-crash-probe-1", "synthetic": True, "passed": all(assertions.values()),
        "assertions": assertions, "childExitCode": child.returncode, "crashAudit": crash_report, "finalAudit": final_audit,
        "boundaries": {"workDatabaseAccess": False, "externalRequests": False, "existingProcessesStopped": False,
            "automaticRequeue": False, "workFilesDeleted": False}, "temporaryWorkspaceRemoved": False}


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--child-crash":
        crash_child(Path(sys.argv[2]), int(sys.argv[3]))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.run:
        parser.error("Use --run to create only this probe's disposable workspace.")
    output = args.output or APP / "var/result-file-integrity-2026-10-23" / ("probe-" + uuid.uuid4().hex[:12] + ".json")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output.exists() or output.parent.stat().st_mode & 0o077:
        parser.error("Use a new output filename in a private directory.")
    os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory(prefix="tcm-artifact-probe-") as temp:
            directory = Path(temp)
            (directory / "owned.json").write_text('{"ownedByProbe":true}')
            result = run_probe(directory)
        result["temporaryWorkspaceRemoved"] = not directory.exists()
    except Exception as error:
        # Do not echo potential library paths, settings or research contents.
        result = {"passed": False, "failureType": type(error).__name__, "synthetic": True,
            "temporaryWorkspaceRemoved": not directory.exists() if "directory" in locals() else True}
    with output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"passed": result["passed"], "assertions": result.get("assertions", {}),
        "temporaryWorkspaceRemoved": result["temporaryWorkspaceRemoved"], "failureType": result.get("failureType")}))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
