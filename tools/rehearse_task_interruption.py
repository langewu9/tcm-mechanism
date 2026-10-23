"""Opt-in real Celery interruption rehearsal in a disposable PostgreSQL database.

No acceptance database rows or existing Redis server are changed. A new database,
private Unix-socket Redis process, queue and worker are owned by this invocation.
The real research-assistant task entry is used; only its service body is patched
inside the disposable worker to pause/return an explicitly synthetic result.

Run with python_app/.venv/bin/python and --run --phase baseline|require-fix.
The fixed phase invokes fail_interrupted_tasks only against this disposable DB,
while every worker consuming its unique queue is stopped. No automatic retry.
"""
from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
import types
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "python_app"
JOB = APP / "var/task-interruption-2026-10-23"
PREFIX = "tcm_task_rehearsal_"


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    path.chmod(0o600)


def append_event(directory, value):
    descriptor = os.open(directory / "events.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, (json.dumps({"time": datetime.now(timezone.utc).isoformat(), **value}) + "\n").encode())
    finally:
        os.close(descriptor)


def events(directory, kind=None):
    path = directory / "events.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [row for row in rows if kind is None or row["kind"] == kind]


def wait_for(predicate, label, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.1)
    raise RuntimeError(f"Timed out waiting for {label}; inspect private evidence logs.")


def isolated_environment(directory, database, socket_path, queue):
    if not re.fullmatch(PREFIX + "[a-f0-9]{12}", database):
        raise RuntimeError("Refusing unexpected disposable database name.")
    if queue != database or socket_path != Path("/tmp") / (database + ".sock"):
        raise RuntimeError("Refusing inconsistent isolated queue or Redis socket.")
    from postgres_acceptance import environment
    profile = environment()
    # Replace DATABASE_URL immediately; nothing imports Django before this point.
    parts = urlsplit(os.environ["DATABASE_URL"])
    os.environ["DATABASE_URL"] = urlunsplit(parts._replace(path="/" + database))
    os.environ.update(
        CELERY_BROKER_URL="redis+socket://" + str(socket_path) + "?virtual_host=0",
        CACHE_URL="", MEDIA_ROOT=str(directory / "media"),
        SQLITE_SOURCE_ROOT=str(directory / "source-databases"),
        RUNTIME_LOG_DIR=str(directory / "runtime-logs"),
        SOURCE_SCHEDULED_PREVIEWS_ENABLED="false", CASE_MODEL_BASE_URL="", CASE_MODEL_API_KEY="",
        R_VIZ_BASE_URL="", R_VIZ_API_TOKEN="", S3_STORAGE_ENABLED="false",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        TASK_REHEARSAL_DATABASE=database, TASK_REHEARSAL_QUEUE=queue,
        TASK_REHEARSAL_DIRECTORY=str(directory), TASK_REHEARSAL_SOCKET=str(socket_path),
        LD_LIBRARY_PATH=os.environ.get("LD_LIBRARY_PATH", "") + ":" + str(APP / "var/local-runtime/root/usr/lib/x86_64-linux-gnu"),
    )
    return profile


def configure_app(queue):
    from config.celery import app
    app.conf.update(task_default_queue=queue, task_queues=None,
                    broker_transport_options={"visibility_timeout": 3, "polling_interval": .2},
                    result_backend=None, task_soft_time_limit=None,
                    worker_cancel_long_running_tasks_on_connection_loss=True)
    return app


def worker():
    os.umask(0o077)
    directory = Path(os.environ["TASK_REHEARSAL_DIRECTORY"]).resolve()
    database = os.environ["TASK_REHEARSAL_DATABASE"]
    queue = os.environ["TASK_REHEARSAL_QUEUE"]
    socket_path = Path(os.environ["TASK_REHEARSAL_SOCKET"])
    if directory.parent != JOB.resolve() or not (directory / "owned.json").is_file():
        raise RuntimeError("Worker requires a private owned rehearsal directory.")
    isolated_environment(directory, database, socket_path, queue)
    sys.path.insert(0, str(APP))
    # Apply the probe's disabled soft limit before the task is first bound;
    # Celery caches task defaults during binding, independent of later conf.
    configure_app(queue)
    import django
    django.setup()
    from django.db import connection
    if connection.settings_dict["NAME"] != database:
        raise RuntimeError("Worker database isolation failed.")
    baseline = directory / "baseline_tasks.py"
    if baseline.is_file():
        # Only this disposable process loads the exact frozen original task
        # module. The checkout and live acceptance worker remain untouched.
        import apps.core
        tasks = types.ModuleType("apps.core.tasks")
        tasks.__file__ = str(baseline)
        tasks.__package__ = "apps.core"
        sys.modules["apps.core.tasks"] = tasks
        apps.core.tasks = tasks
        exec(compile(baseline.read_text(), str(baseline), "exec"), tasks.__dict__)
    else:
        from apps.core import tasks
    from celery.signals import task_postrun, task_received, worker_ready

    def synthetic_service(task):
        parameters = task.input_parameters
        if parameters.get("synthetic") is not True or parameters.get("rehearsalDatabase") != database:
            raise RuntimeError("Probe refuses a non-rehearsal task.")
        label = parameters["rehearsalLabel"]
        if not re.fullmatch("[a-z_]+", label):
            raise RuntimeError("Invalid synthetic task label.")
        append_event(directory, {"kind": "service_enter", "taskId": task.pk, "pid": os.getpid(), "label": label})
        if parameters.get("pause"):
            wait_for(lambda: (directory / (label + ".release")).exists(), "synthetic pause release", timeout=180)
        return {"synthetic": True, "notResearch": True, "label": label, "probeVersion": 1}

    # No model, scientific service, storage or acceptance account is called here.
    tasks.run_research_assistant = synthetic_service
    tasks.run_research_assistant_task.soft_time_limit = None

    @worker_ready.connect(weak=False)
    def on_ready(**kwargs):
        append_event(directory, {"kind": "worker_ready", "pid": os.getpid()})

    @task_received.connect(weak=False)
    def on_received(request=None, **kwargs):
        append_event(directory, {"kind": "task_received", "celeryId": request.id,
                                 "timeLimits": request.time_limits})

    @task_postrun.connect(weak=False)
    def on_postrun(task_id=None, retval=None, **kwargs):
        append_event(directory, {"kind": "task_postrun", "celeryId": task_id, "return": retval})

    configure_app(queue).worker_main(["worker", "--loglevel=INFO", "--pool=prefork", "--concurrency=1",
        "--soft-time-limit=0",
        "--without-mingle", "--without-gossip", "--without-heartbeat", "--queues=" + queue,
        "--hostname=" + queue + "@%h"])


def main(args):
    if not args.run:
        raise SystemExit("No action taken. Supply --run --phase baseline or --run --phase require-fix explicitly.")
    os.umask(0o077)
    token = secrets.token_hex(6)
    database = PREFIX + token
    queue = database
    socket_path = Path("/tmp") / (database + ".sock")
    JOB.mkdir(parents=True, exist_ok=True, mode=0o700)
    JOB.chmod(0o700)
    directory = JOB / (args.phase + "-" + token)
    directory.mkdir(mode=0o700)
    write_json(directory / "owned.json", {"database": database, "queue": queue, "syntheticOnly": True,
                                         "phase": args.phase, "acceptanceDatabaseChanged": False})
    if socket_path.exists():
        raise RuntimeError("Unique Redis socket already exists; refusing to adopt a service.")
    if args.phase == "baseline":
        frozen_commit = subprocess.check_output(["git", "rev-parse", "1aebfa3^{commit}"], cwd=ROOT, text=True).strip()
        frozen = subprocess.check_output(["git", "show", frozen_commit + ":python_app/apps/core/tasks.py"], cwd=ROOT)
        baseline = directory / "baseline_tasks.py"
        baseline.write_bytes(frozen)
        baseline.chmod(0o600)
        write_json(directory / "baseline-source.json", {"commit": frozen_commit,
                   "path": "python_app/apps/core/tasks.py", "sha256": hashlib.sha256(frozen).hexdigest()})
    profile = isolated_environment(directory, database, socket_path, queue)
    import psycopg
    from psycopg import sql
    processes = {}
    created_database = False
    checks = {}
    task_states = []
    admin = None
    redis_client = None

    def launch(name, command, cwd=ROOT):
        with (directory / (name + ".log")).open("ab") as output:
            process = subprocess.Popen([str(part) for part in command], cwd=cwd, env=dict(os.environ),
                                       stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        processes[name] = process
        return process

    def stop(name, hard=False):
        process = processes.get(name)
        if not process or process.poll() is not None:
            return
        os.killpg(process.pid, signal.SIGKILL if hard else signal.SIGTERM)
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)

    def start_worker(number):
        old_ready = len(events(directory, "worker_ready"))
        process = launch("worker-" + str(number), [sys.executable, Path(__file__).resolve(), "--_worker"])
        wait_for(lambda: len(events(directory, "worker_ready")) > old_ready if process.poll() is None else False,
                 "isolated worker ready")
        return process

    try:
        # The only connection to an existing database is cluster administration in
        # postgres. No query or connection is made to tcm_acceptance itself.
        admin = psycopg.connect(host="127.0.0.1", port=55439, user=profile["user"],
                               password=profile["password"], dbname="postgres", autocommit=True)
        if admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone():
            raise RuntimeError("Disposable database already exists; refusing to adopt it.")
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database)))
        created_database = True
        redis_binary = shutil.which("redis-server") or APP / "var/local-runtime/root/usr/bin/redis-server"
        redis_process = launch("redis", [redis_binary, "--port", "0", "--unixsocket", socket_path,
            "--unixsocketperm", "700", "--protected-mode", "yes", "--save", "", "--appendonly", "no",
            "--dir", directory])
        import redis
        redis_client = redis.Redis(unix_socket_path=str(socket_path), socket_timeout=1)
        def redis_ready():
            if redis_process.poll() is not None:
                raise RuntimeError("Isolated Redis exited; inspect its private log.")
            try:
                return redis_client.ping()
            except redis.ConnectionError:
                return False
        wait_for(redis_ready, "isolated Redis socket")
        with (directory / "migrate.log").open("w") as output:
            subprocess.run([sys.executable, APP / "manage.py", "migrate", "--noinput"], cwd=APP,
                           stdout=output, stderr=subprocess.STDOUT, check=True, env=dict(os.environ))
        sys.path.insert(0, str(APP))
        import django
        django.setup()
        from django.contrib.auth import get_user_model
        from django.db import connection
        from apps.core.models import AnalysisTask
        if connection.settings_dict["NAME"] != database:
            raise RuntimeError("Producer database isolation failed.")
        if get_user_model().objects.exists() or AnalysisTask.objects.exists():
            raise RuntimeError("New database unexpectedly contains accounts/tasks.")
        owner = get_user_model().objects.create(username="synthetic-interruption-only", password="!")
        app = configure_app(queue)

        def new_task(label, pause):
            return AnalysisTask.objects.create(owner=owner, created_by=owner,
                task_type=AnalysisTask.TaskType.RESEARCH_ASSISTANT, input_parameters={
                    "synthetic": True, "rehearsalDatabase": database, "rehearsalLabel": label, "pause": pause})

        def state(task):
            task.refresh_from_db()
            result = {"taskId": task.pk, "status": task.status, "progress": task.progress,
                      "result": task.result, "errorSummary": task.error_summary,
                      "startedAt": task.started_at, "finishedAt": task.finished_at}
            task_states.append(result)
            return result

        def publish(task, suffix, **options):
            celery_id = database + "-" + suffix
            app.send_task("core.research_assistant", args=[task.pk], queue=queue, task_id=celery_id, **options)
            return celery_id

        def wait_postrun(celery_id, timeout=30):
            return wait_for(lambda: next((row for row in events(directory, "task_postrun")
                                         if row.get("celeryId") == celery_id), None), "task postrun", timeout)

        # Control: normal work succeeds once; repeated delivery cannot overwrite it.
        start_worker(1)
        normal = new_task("normal", False)
        wait_postrun(publish(normal, "normal"))
        normal_before = state(normal)
        wait_postrun(publish(normal, "normal-duplicate"))
        normal_after = state(normal)
        checks["normalSucceeded"] = normal_before["status"] == "succeeded"
        checks["successfulDuplicateUnchanged"] = normal_before == normal_after
        checks["normalServiceCalls"] = sum(row["taskId"] == normal.pk for row in events(directory, "service_enter")) == 1

        # Kill only the prefork pool child after the genuine entry claims RUNNING.
        child_task = new_task("child_loss", True)
        publish(child_task, "child-loss")
        entered = wait_for(lambda: next((row for row in events(directory, "service_enter")
            if row["taskId"] == child_task.pk), None), "paused pool child")
        if os.getpgid(entered["pid"]) != processes["worker-1"].pid:
            raise RuntimeError("Refusing to signal a process outside the owned worker group.")
        checks["childWasRunning"] = state(child_task)["status"] == "running"
        os.kill(entered["pid"], signal.SIGKILL)
        expected = "failed" if args.phase == "require-fix" else "running"
        if args.phase == "require-fix":
            wait_for(lambda: AnalysisTask.objects.get(pk=child_task.pk).status == "failed", "child-loss failure state")
        else:
            time.sleep(2)
        child_after_loss = state(child_task)
        wait_postrun(publish(child_task, "child-loss-duplicate"))
        child_after_duplicate = state(child_task)
        checks["childLossExpectedState"] = child_after_loss["status"] == expected
        checks["childDuplicateCannotExecute"] = sum(row["taskId"] == child_task.pk for row in events(directory, "service_enter")) == 1
        checks["childDuplicateUnchanged"] = child_after_loss == child_after_duplicate
        stop("worker-1")
        if args.phase == "require-fix":
            start_worker(4)
            hard_task = new_task("hard_timeout", True)
            hard_started = time.monotonic()
            publish(hard_task, "hard-timeout", time_limit=2, soft_time_limit=None)
            wait_for(lambda: any(row["taskId"] == hard_task.pk for row in events(directory, "service_enter")), "hard-limit probe entered")
            wait_for(lambda: AnalysisTask.objects.get(pk=hard_task.pk).status == "failed", "hard-limit failure state", timeout=15)
            hard_elapsed = time.monotonic() - hard_started
            hard_after_loss = state(hard_task)
            wait_postrun(publish(hard_task, "hard-timeout-duplicate"))
            hard_after_duplicate = state(hard_task)
            checks["hardLimitExpectedState"] = hard_after_loss["status"] == "failed"
            checks["hardLimitEnforcedInSeconds"] = 1.5 <= hard_elapsed <= 15
            checks["hardLimitWorkerLog"] = "Hard time limit (2s) exceeded" in (directory / "worker-4.log").read_text()
            checks["hardLimitDuplicateCannotExecute"] = sum(row["taskId"] == hard_task.pk for row in events(directory, "service_enter")) == 1
            checks["hardLimitDuplicateUnchanged"] = hard_after_loss == hard_after_duplicate
            write_json(directory / "hard-timeout.json", {"timeLimitSeconds": 2, "softTimeLimit": None,
                       "elapsedSeconds": hard_elapsed, "taskId": hard_task.pk, "status": hard_after_loss["status"]})
            stop("worker-4")

        # Kill parent and pool together. Recovery is explicit, while this isolated
        # queue has no live consumer; it never automatically resubmits research.
        start_worker(2)
        whole_task = new_task("whole_loss", True)
        publish(whole_task, "whole-loss")
        wait_for(lambda: any(row["taskId"] == whole_task.pk for row in events(directory, "service_enter")), "whole worker pause")
        checks["wholeWasRunning"] = state(whole_task)["status"] == "running"
        checks["wholeDeliveryWasUnacked"] = redis_client.hlen("unacked") >= 1
        stop("worker-2", hard=True)
        write_json(directory / "unacked-after-crash.json", {"unackedCount": redis_client.hlen("unacked"),
                   "index": [[tag.decode(), score] for tag, score in redis_client.zrange("unacked_index", 0, -1, withscores=True)]})
        before_recovery = state(whole_task)
        if args.phase == "require-fix":
            before = datetime.now(timezone.utc).isoformat()
            with (directory / "recover-dry-run.log").open("w") as output:
                subprocess.run([sys.executable, APP / "manage.py", "fail_interrupted_tasks", "--before", before],
                    cwd=APP, env=dict(os.environ), stdout=output, stderr=subprocess.STDOUT, check=True)
            checks["dryRunUnchanged"] = state(whole_task) == before_recovery
            with (directory / "recover-apply.log").open("w") as output:
                subprocess.run([sys.executable, APP / "manage.py", "fail_interrupted_tasks", "--before", before,
                                "--apply", "--workers-stopped"], cwd=APP, env=dict(os.environ),
                               stdout=output, stderr=subprocess.STDOUT, check=True)
        recovered = state(whole_task)
        # Allow the deliberately short broker visibility interval to expire
        # before poll initialization, which performs its first real restore.
        # No message is manually copied, republished, or removed from Redis.
        time.sleep(4)
        start_worker(3)
        wait_postrun(publish(whole_task, "whole-loss-duplicate"))
        # Redis visibility restoration is periodic; let the original killed
        # delivery return, then require it to be skipped rather than executed.
        wait_postrun(database + "-whole-loss", timeout=45)
        final_whole = state(whole_task)
        checks["wholeLossExpectedState"] = recovered["status"] == expected
        checks["wholeOriginalAndDuplicateCannotExecute"] = sum(row["taskId"] == whole_task.pk for row in events(directory, "service_enter")) == 1
        checks["wholeResultUnchangedAfterRedelivery"] = recovered == final_whole
        checks["noUnexpectedTasks"] = AnalysisTask.objects.count() == (4 if args.phase == "require-fix" else 3)
        checks["noSnapshotRows"] = all(task.snapshot_rows.count() == 0 for task in AnalysisTask.objects.all())
        checks["noArtifactRows"] = all(task.rendered_artifacts.count() == 0 for task in AnalysisTask.objects.all())
        outcome = {"passed": all(checks.values()), "phase": args.phase, "database": database,
                   "queue": queue, "checks": checks, "states": task_states,
                   "syntheticOnly": True, "modelsCalled": False, "externalScientificServicesCalled": False,
                   "existingAcceptanceDataTouched": False, "automaticRetry": False}
        write_json(directory / "result.json", outcome)
        print(json.dumps({"passed": outcome["passed"], "phase": args.phase,
                          "checks": checks, "evidence": str(directory)}, ensure_ascii=False))
        if not outcome["passed"]:
            raise RuntimeError("Rehearsal assertions failed; inspect result.json.")
    except BaseException as exc:
        write_json(directory / "failure.json", {"errorType": type(exc).__name__,
                   "message": str(exc) if not isinstance(exc, psycopg.Error) else "Database error; details omitted to protect credentials.",
                   "phase": args.phase, "checks": checks, "states": task_states})
        raise
    finally:
        for name in list(processes):
            if name.startswith("worker-"):
                stop(name, hard=True)
        if redis_client is not None:
            redis_client.close()
        stop("redis")
        if socket_path.exists():
            socket_path.unlink()
        if created_database and admin is not None:
            try:
                if "django.db" in sys.modules:
                    from django.db import connections
                    connections.close_all()
                # Termination is scoped to the exact newly-created database.
                admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", (database,))
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
                write_json(directory / "cleaned.json", {"databaseDropped": database, "ownedProcessesStopped": True})
            finally:
                admin.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Explicit consent to create disposable local services and SIGKILL their owned worker processes.")
    parser.add_argument("--phase", choices=["baseline", "require-fix"], default="baseline")
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    options = parser.parse_args()
    if options._worker:
        worker()
    else:
        main(options)
