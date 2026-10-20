"""Bounded localhost load test with independent PG, Redis, TLS and synthetic data.

All services bind loopback. Existing previews and acceptance data are untouched.
No model, external biological service, email or background analysis is invoked.
Private state remains under ignored python_app/var/loadtest; published metrics
contain no session credentials. Run with the project virtual environment.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import ssl
import statistics
import subprocess
import sys
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "python_app"
VAR = APP / "var/loadtest"
PGROOT = APP / "var/postgres-acceptance/runtime/root"
PGBIN = PGROOT / "usr/lib/postgresql/17/bin"
REDISROOT = APP / "var/local-runtime/root"
NGINX = APP / "var/framework-audit/runtime/root/usr/sbin/nginx"
DOMAIN = "loadtest.example.test"
PGPORT, REDISPORT, APIPORT, HTTPPORT, TLSPORT = 55441, 6391, 8024, 8086, 8446
PROCESSES = {}
PHASE = "setup"
MONITOR_STOP = threading.Event()
RESOURCES = []
RESULT_SUFFIX = ""


def state():
    VAR.mkdir(parents=True, exist_ok=True)
    path = VAR / "private-state.json"
    if not path.exists():
        path.write_text(json.dumps({"database": "tcm_loadtest", "password": secrets.token_urlsafe(32),
                                   "redis_password": secrets.token_hex(24), "secret": secrets.token_urlsafe(64)}))
        path.chmod(0o600)
    return json.loads(path.read_text())


def environment(mode="capacity"):
    private = state()
    env = dict(os.environ)
    env.update(
        DJANGO_SETTINGS_MODULE="config.settings", DJANGO_DEBUG="false", DJANGO_SECRET_KEY=private["secret"],
        DJANGO_ALLOWED_HOSTS=f"127.0.0.1,localhost,{DOMAIN},testserver",
        DATABASE_URL=f"postgresql://tcm_load:{private['password']}@127.0.0.1:{PGPORT}/tcm_loadtest",
        CACHE_URL=f"redis://:{private['redis_password']}@127.0.0.1:{REDISPORT}/1",
        CELERY_BROKER_URL=f"redis://:{private['redis_password']}@127.0.0.1:{REDISPORT}/0",
        DJANGO_USER_RATE="600/min" if mode == "limits" else "600000/min",
        DJANGO_RESEARCH_SUBMISSION_RATE="120/hour", MEDIA_ROOT=str(VAR / "media"),
        SOURCE_SCHEDULED_PREVIEWS_ENABLED="false", CASE_MODEL_BASE_URL="", CASE_MODEL_API_KEY="",
        R_VIZ_BASE_URL="", R_VIZ_API_TOKEN="", S3_STORAGE_ENABLED="false",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DJANGO_SECURE_SSL_REDIRECT="true", DJANGO_USE_X_FORWARDED_PROTO="true",
        DJANGO_SESSION_COOKIE_SECURE="true", DJANGO_CSRF_COOKIE_SECURE="true",
        DJANGO_SESSION_COOKIE_NAME="tcm_load_session", DJANGO_CSRF_COOKIE_NAME="tcm_load_csrf",
        CSRF_TRUSTED_ORIGINS=f"https://{DOMAIN}:{TLSPORT}", PUBLIC_BASE_URL=f"https://{DOMAIN}:{TLSPORT}",
        DJANGO_SECURE_HSTS_SECONDS="31536000", GUNICORN_BIND=f"127.0.0.1:{APIPORT}", GUNICORN_WORKERS="3",
        LD_LIBRARY_PATH=f"{PGROOT}/usr/lib/x86_64-linux-gnu:{REDISROOT}/usr/lib/x86_64-linux-gnu",
    )
    return env


def wait_port(port, process, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Test service on port {port} exited; inspect ignored local logs")
        try:
            with socket.create_connection(("127.0.0.1", port), .3):
                return
        except OSError:
            time.sleep(.1)
    raise RuntimeError(f"Test service on port {port} did not become ready")


def launch(name, command, *, cwd=ROOT, env=None):
    log = (VAR / f"{name}.log").open("ab")
    process = subprocess.Popen(list(map(str, command)), cwd=cwd, env=env or environment(), stdout=log, stderr=log)
    log.close()
    PROCESSES[name] = process
    return process


def stop(name):
    process = PROCESSES.get(name)
    if process and process.poll() is None:
        process.send_signal(signal.SIGINT if name == "postgres" else signal.SIGTERM)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def infrastructure():
    env = environment()
    # Never adopt a server that was already listening on the reserved test ports.
    for port in (PGPORT, REDISPORT, APIPORT, HTTPPORT, TLSPORT):
        try:
            with socket.create_connection(("127.0.0.1", port), .2):
                raise RuntimeError(f"Reserved load-test port {port} is occupied")
        except ConnectionRefusedError:
            pass
    data = VAR / "pgdata"
    if not (data / "PG_VERSION").exists():
        password = VAR / "pg-password"
        password.write_text(state()["password"])
        password.chmod(0o600)
        subprocess.run([str(PGBIN / "initdb"), "-D", str(data), "-U", "tcm_load", "--pwfile", str(password),
                        "--auth-host=scram-sha-256", "--auth-local=trust", "--no-locale", "-E", "UTF8"],
                       env=env, check=True, stdout=(VAR / "initdb.log").open("w"), stderr=subprocess.STDOUT)
        password.unlink()
    socket_dir = Path("/tmp") / ("tcm-load-" + hashlib.sha256(str(VAR).encode()).hexdigest()[:10])
    socket_dir.mkdir(mode=0o700, exist_ok=True)
    postgres = launch("postgres", [PGBIN / "postgres", "-D", data, "-h", "127.0.0.1", "-p", PGPORT,
        "-k", socket_dir, "-c", "shared_buffers=128MB", "-c", "max_connections=64", "-c", "jit=off"])
    wait_port(PGPORT, postgres)
    redis_dir = VAR / "redis"
    redis_dir.mkdir(exist_ok=True)
    config = VAR / "redis.conf"
    config.write_text(f"bind 127.0.0.1\nport {REDISPORT}\nprotected-mode yes\nsave \"\"\nappendonly no\ndir {redis_dir}\nrequirepass {state()['redis_password']}\n")
    config.chmod(0o600)
    redis = launch("redis", [REDISROOT / "usr/bin/redis-server", config])
    wait_port(REDISPORT, redis)


def seed():
    import psycopg
    env = environment()
    with psycopg.connect(host="127.0.0.1", port=PGPORT, user="tcm_load", password=state()["password"], dbname="postgres", autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname='tcm_loadtest'").fetchone():
            conn.execute("CREATE DATABASE tcm_loadtest")
    subprocess.run([sys.executable, str(APP / "manage.py"), "migrate", "--noinput"], env=env, check=True,
                   stdout=(VAR / "migrate.log").open("w"), stderr=subprocess.STDOUT)
    os.environ.update(env)
    sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.contrib.sessions.backends.db import SessionStore
    from django.db import connection, transaction
    from django.utils import timezone
    from django.utils.crypto import get_random_string
    from apps.core.models import DataSource, SourceRelease, ResearcherProfile, ResearchDataset, MedicalCase

    if (VAR / "seeded.json").exists():
        return json.loads((VAR / "seeded.json").read_text())
    user_model = get_user_model()
    if user_model.objects.exists():
        raise RuntimeError("Unrecognized nonempty load-test database; refusing to overwrite it")
    accounts = []
    with transaction.atomic():
        users = [user_model(username=f"loadtest-{i:03d}", is_active=True) for i in range(100)]
        for user in users:
            user.set_unusable_password()
        user_model.objects.bulk_create(users)
        ResearcherProfile.objects.bulk_create([ResearcherProfile(user=user, email_verified_at=timezone.now()) for user in users])
        source = DataSource.objects.create(slug="synthetic-load-source", name="SYNTHETIC LOAD TEST", access_mode="manual")
        release = SourceRelease.objects.create(source=source, version="synthetic-1")
        ResearchDataset.objects.bulk_create([ResearchDataset(owner=users[i % 100], name=f"Synthetic dataset {i}", metadata={"synthetic": True}) for i in range(1000)])
        MedicalCase.objects.bulk_create([MedicalCase(owner=users[i % 100], title=f"Synthetic case {i}",
            deidentified_text="SYNTHETIC LOAD TEST. No patient or clinical information.", source_reference="SYNTHETIC_LOAD_ONLY") for i in range(1000)])
        with connection.cursor() as cursor:
            cursor.execute("""INSERT INTO core_analysistask
                (id,owner_id,created_by_id,task_type,status,input_parameters,progress,result,error_summary,created_at,finished_at)
                SELECT n,1+(n%100),1+(n%100),
                    CASE (n/100)%3 WHEN 0 THEN 'proteomics' WHEN 1 THEN 'network' ELSE 'visualization' END,
                    'succeeded',jsonb_build_object('synthetic',true,'name','Synthetic load task','analysisKind','load_fixture'),100,
                    jsonb_build_object('synthetic',true,'summary','Synthetic fixture; not a research conclusion','payload',
                        (SELECT string_agg(md5(n::text||':'||s::text),'') FROM generate_series(1,256) s)),
                    '',now()-(n*interval '1 second'),now() FROM generate_series(1,30000) n""")
            cursor.execute("INSERT INTO core_analysistask_source_releases (analysistask_id,sourcerelease_id) SELECT id,%s FROM core_analysistask", [release.pk])
            cursor.execute("SELECT setval(pg_get_serial_sequence('core_analysistask','id'),30000,true)")
            cursor.execute("ANALYZE core_analysistask")
        for user in users:
            session = SessionStore()
            session["_auth_user_id"] = str(user.pk)
            session["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
            session["_auth_user_hash"] = user.get_session_auth_hash()
            session.create()
            accounts.append({"id": user.pk, "cookie": f"tcm_load_session={session.session_key}; tcm_load_csrf={get_random_string(32)}"})
    private_accounts = VAR / "accounts.json"
    private_accounts.write_text(json.dumps(accounts))
    private_accounts.chmod(0o600)
    metadata = {"synthetic": True, "users": 100, "tasks": 30000, "datasets": 1000, "cases": 1000,
                "resultPayloadCharacters": 8192, "taskSourceLinks": 30000}
    (VAR / "seeded.json").write_text(json.dumps(metadata, indent=2))
    return metadata


def render_proxy(mode):
    cert = VAR / "certs"
    cert.mkdir(exist_ok=True)
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3", "-subj", f"/CN={DOMAIN}",
        "-addext", f"subjectAltName=DNS:{DOMAIN}", "-keyout", str(cert / "privkey.pem"), "-out", str(cert / "fullchain.pem")],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (cert / "privkey.pem").chmod(0o600)
    folder = VAR / "nginx"
    folder.mkdir(exist_ok=True)
    for name in ("body", "proxy", "fastcgi", "uwsgi", "scgi"):
        (folder / name).mkdir(exist_ok=True)
    for name in ("default.conf.template", "proxy-api.conf", "security-headers.conf", "rate-limits.conf"):
        text = (ROOT / "deploy/nginx" / name).read_text()
        substitutions = {"${PUBLIC_DOMAIN}": DOMAIN, "listen 80": f"listen 127.0.0.1:{HTTPPORT}",
            "listen 443": f"listen 127.0.0.1:{TLSPORT}", "https://$host$request_uri": f"https://$host:{TLSPORT}$request_uri",
            "/etc/nginx/snippets/": f"{folder}/", "/etc/nginx/certs/": f"{cert}/",
            "/usr/share/nginx/html": str(ROOT / "web/dist"), "/srv/django-static/": f"{APP}/staticfiles/",
            "/var/log/nginx/access.log": str(VAR / "nginx-access.log"), "http://api:8020": f"http://127.0.0.1:{APIPORT}"}
        for before, after in substitutions.items():
            text = text.replace(before, after)
        if name == "rate-limits.conf" and mode == "capacity":
            text = text.replace("zone=platform_api:10m rate=600r/m", "zone=platform_api:10m rate=600000r/m")
        (folder / name.replace(".template", "")).write_text(text)
    (folder / "nginx.conf").write_text(f"""worker_processes 1;
pid {folder}/nginx.pid;
error_log {VAR}/nginx-error.log warn;
events {{ worker_connections 512; }}
http {{
 default_type application/octet-stream;
 client_body_temp_path {folder}/body;
 proxy_temp_path {folder}/proxy;
 fastcgi_temp_path {folder}/fastcgi;
 uwsgi_temp_path {folder}/uwsgi;
 scgi_temp_path {folder}/scgi;
 include {folder}/rate-limits.conf;
 include {folder}/default.conf;
}}
""")
    subprocess.run([str(NGINX), "-p", f"{folder}/", "-c", str(folder / "nginx.conf"), "-t"], check=True)


def application(mode):
    from django.core.cache import cache
    # This Redis instance is private to this run; no shared cache is cleared.
    cache.clear()
    render_proxy(mode)
    api = launch("api", [sys.executable, "-m", "gunicorn", "--config", "python:config.gunicorn", "config.wsgi:application"], cwd=APP, env=environment(mode))
    wait_port(APIPORT, api)
    proxy = launch("nginx", [NGINX, "-p", f"{VAR}/nginx/", "-c", VAR / "nginx/nginx.conf", "-g", "daemon off;"])
    wait_port(TLSPORT, proxy)


class Connection(http.client.HTTPSConnection):
    context = None

    def connect(self):
        self.sock = self.context.wrap_socket(socket.create_connection(("127.0.0.1", TLSPORT), self.timeout), server_hostname=DOMAIN)


def monitor():
    import psutil
    known = {}
    while not MONITOR_STOP.wait(.5):
        sample = {"time": time.time(), "phase": PHASE, "availableMemoryMiB": psutil.virtual_memory().available / 1048576}
        groups = {"client": [psutil.Process()], **{name: [psutil.Process(proc.pid)] for name, proc in PROCESSES.items() if proc.poll() is None}}
        for name, roots in groups.items():
            current = []
            for root in roots:
                try:
                    current.extend([root] + (root.children(recursive=True) if name != "client" else []))
                except psutil.Error:
                    continue
            cpu, rss = 0., 0
            for process in current:
                try:
                    handle = known.setdefault(process.pid, process)
                    cpu += handle.cpu_percent()
                    rss += handle.memory_info().rss
                except psutil.Error:
                    continue
            sample[name + "CpuPercent"] = cpu
            sample[name + "RssMiB"] = rss / 1048576
        RESOURCES.append(sample)


def percentile(values, fraction):
    values = sorted(values)
    return values[min(len(values)-1, max(0, int(len(values)*fraction+.999999)-1))] if values else None


def warmup_and_guards(accounts):
    def read(number):
        account = accounts[number % len(accounts)]
        client = Connection(DOMAIN, TLSPORT, timeout=10)
        client.request("GET", "/api/v1/research/analysis-tasks/summaries/", headers={"Cookie": account["cookie"]})
        response = client.getresponse()
        value = json.loads(response.read())
        assert response.status == 200 and value["count"] == 300
        assert all(row["owner_id"] == account["id"] for row in value["results"])
        client.close()
    began = time.perf_counter()
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(read, range(6)))
    for path, cookie, expected in [
        ("/api/v1/research/analysis-tasks/summaries/", "", 401),
        ("/api/v1/research/analysis-tasks/1/", accounts[0]["cookie"], 404),
    ]:
        client = Connection(DOMAIN, TLSPORT, timeout=5)
        client.request("GET", path, headers={"Cookie": cookie})
        response = client.getresponse()
        response.read()
        assert response.status == expected
        client.close()
    return round(time.perf_counter()-began,3)


def write_counts():
    from apps.core.models import MedicalCase, MedicalCaseAuditEvent, ResearchDataset, ResearchDatasetAuditEvent
    return {"cases": MedicalCase.objects.count(), "caseAuditEvents": MedicalCaseAuditEvent.objects.count(),
            "datasets": ResearchDataset.objects.count(), "datasetAuditEvents": ResearchDatasetAuditEvent.objects.count()}


def verify_writes(before):
    from apps.core.models import MedicalCase, ResearchDataset
    from django.core.files.storage import default_storage
    counts = Counter()
    ids = {"write": [], "upload": []}
    with (VAR / f"requests{RESULT_SUFFIX}.jsonl").open() as source:
        for line in source:
            record = json.loads(line)
            if record["createdId"] is not None and record["valid"]:
                ids[record["workload"]].append(record["createdId"])
    for kind, model in [("write", MedicalCase), ("upload", ResearchDataset)]:
        assert len(set(ids[kind])) == len(ids[kind])
        assert model.objects.filter(pk__in=ids[kind]).count() == len(ids[kind])
    for upload in ResearchDataset.objects.filter(pk__in=ids["upload"]):
        with default_storage.open(upload.storage_key,"rb") as source:
            assert hashlib.sha256(source.read()).hexdigest() == UPLOAD_SHA
    after = write_counts()
    assert after["cases"] - before["cases"] == len(ids["write"])
    assert after["caseAuditEvents"] - before["caseAuditEvents"] == len(ids["write"])
    assert after["datasets"] - before["datasets"] == len(ids["upload"])
    assert after["datasetAuditEvents"] - before["datasetAuditEvents"] == len(ids["upload"])
    return {"before": before, "after": after, "caseWrites": len(ids["write"]), "uploads": len(ids["upload"]),
            "duplicateIds": 0, "missingRecords": 0, "auditCountMatches": True, "uploadHashesMatch": True}


def phase(name, workload, concurrency, seconds, accounts, *, total_per_user=None):
    global PHASE
    PHASE = name
    records = []
    barrier = threading.Barrier(concurrency + 1)
    start = time.monotonic()
    deadline = start + seconds
    def worker(number):
        account = accounts[number % len(accounts)]
        client = Connection(DOMAIN, TLSPORT, timeout=5)
        csrf = account["cookie"].split("tcm_load_csrf=",1)[1]
        headers = {"Cookie": account["cookie"], "X-CSRFToken": csrf, "Origin": f"https://{DOMAIN}:{TLSPORT}", "Content-Type": "application/json"}
        detail_id = 1 + ((account["id"] - 2) % 100)
        barrier.wait()
        count = 0
        while (count < total_per_user if total_per_user else time.monotonic() < deadline):
            kind = workload
            if workload in {"mixed", "soak"}:
                slot = count % 20
                kind = "summary" if slot < 12 else "detail" if slot < 16 else "datasets" if slot < 18 else "dashboard" if slot == 18 else "write"
            path = {"summary": "/api/v1/research/analysis-tasks/summaries/", "legacy": "/api/v1/research/analysis-tasks/",
                "detail": f"/api/v1/research/analysis-tasks/{detail_id}/", "datasets": "/api/v1/research/datasets/",
                "dashboard": "/api/v1/research/dashboard/", "write": "/api/v1/research/cases/", "upload": "/api/v1/research/datasets/"}[kind]
            method, body = "GET", None
            request_headers = dict(headers)
            expected = 200
            if kind == "write":
                method, expected = "POST", 201
                body = json.dumps({"title": f"Synthetic pressure {name} {number} {count}", "deidentified_text": "SYNTHETIC ONLY. No patient data.", "source_reference": "SYNTHETIC_LOAD_WRITE"}).encode()
            elif kind == "upload":
                method, expected, body = "POST", 201, UPLOAD
                request_headers["Content-Type"] = "multipart/form-data; boundary=LoadTestSyntheticBoundary"
            began = time.perf_counter()
            status, size, valid, error, created_id = 0, 0, False, "", None
            try:
                client.request(method, path, body=body, headers=request_headers)
                response = client.getresponse()
                payload = response.read()
                size, status = len(payload), response.status
                value = json.loads(payload)
                if status == expected:
                    valid = "no-store" in response.headers.get("Cache-Control", "")
                    rows = value.get("results") if kind in {"summary", "legacy", "datasets"} else [value] if kind != "dashboard" else []
                    if rows is not None and rows:
                        valid = valid and all(row.get("owner_id") == account["id"] for row in rows)
                    if kind in {"write", "upload"}:
                        created_id = value.get("id")
                        valid = valid and isinstance(created_id, int)
                    if kind == "upload":
                        valid = valid and value.get("content_sha256") == UPLOAD_SHA and value.get("row_count") == 1000
                elif status == 429:
                    valid = value.get("error", {}).get("code") == "RATE_LIMITED"
            except Exception as exc:
                error = type(exc).__name__
                client.close()
            records.append({"phase": name, "workload": kind, "vu": number, "status": status,
                            "latencyMs": (time.perf_counter()-began)*1000, "bytes": size,
                            "valid": valid, "error": error, "createdId": created_id, "time": time.time()})
            count += 1
        client.close()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(worker, number) for number in range(concurrency)]
        start = time.monotonic()
        deadline = start + seconds
        barrier.wait()
        for future in futures:
            future.result()
    elapsed = time.monotonic() - start
    good = [record for record in records if record["status"] in {200,201} and record["valid"]]
    failures = [record for record in records if record["status"] not in {200,201,429} or not record["valid"]]
    limited = [record for record in records if record["status"] == 429]
    latencies = [record["latencyMs"] for record in good]
    resource = [sample for sample in RESOURCES if sample["phase"] == name]
    summary = {"name": name, "workload": workload, "concurrency": concurrency, "seconds": round(elapsed,3),
        "requests": len(records), "successful": len(good), "errors": len(failures), "rateLimited": len(limited),
        "attemptsPerSecond": round(len(records)/elapsed,2), "successfulPerSecond": round(len(good)/elapsed,2),
        "p50Ms": percentile(latencies,.50), "p95Ms": percentile(latencies,.95), "p99Ms": percentile(latencies,.99),
        "maxMs": max(latencies) if latencies else None, "statuses": dict(Counter(record["status"] for record in records)),
        "workloadCounts": dict(Counter(record["workload"] for record in records)),
        "bytes": sum(record["bytes"] for record in records), "writes": sum(record["createdId"] is not None for record in records),
        "apiCpuMeanPercent": statistics.mean(sample.get("apiCpuPercent",0) for sample in resource) if resource else None,
        "apiRssPeakMiB": max((sample.get("apiRssMiB",0) for sample in resource),default=0),
        "clientCpuMeanPercent": statistics.mean(sample.get("clientCpuPercent",0) for sample in resource) if resource else None}
    with (VAR / f"requests{RESULT_SUFFIX}.jsonl").open("a") as output:
        output.writelines(json.dumps(record)+"\n" for record in records)
    print(json.dumps(summary), flush=True)
    if resource and min(sample["availableMemoryMiB"] for sample in resource) < 2048:
        raise RuntimeError("Stopped load escalation: host available memory below 2 GiB")
    return summary


CSV_FILE = b"Gene,Value,Note\n" + (b"SYNTHETIC,2," + b"x"*1024 + b"\n")*1000
UPLOAD_SHA = hashlib.sha256(CSV_FILE).hexdigest()
UPLOAD = (b'--LoadTestSyntheticBoundary\r\nContent-Disposition: form-data; name="name"\r\n\r\nSynthetic pressure upload\r\n'
          b'--LoadTestSyntheticBoundary\r\nContent-Disposition: form-data; name="file"; filename="synthetic.csv"\r\nContent-Type: text/csv\r\n\r\n'
          + CSV_FILE + b'\r\n--LoadTestSyntheticBoundary--\r\n')


def main():
    global RESULT_SUFFIX
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=15)
    parser.add_argument("--soak-seconds", type=int, default=60)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    RESULT_SUFFIX = "-smoke" if args.smoke else ""
    VAR.mkdir(parents=True, exist_ok=True)
    (VAR / f"requests{RESULT_SUFFIX}.jsonl").write_text("")
    if not 3 <= args.seconds <= 30 or not 10 <= args.soak_seconds <= 180:
        parser.error("Stage duration must be 3–30s and soak duration 10–180s")
    sys.path.append(str(APP / "var/loadtest-runtime"))
    import psutil
    report = {"synthetic": True, "commit": subprocess.check_output(["git","rev-parse","--short","HEAD"],cwd=ROOT,text=True).strip(),
              "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cpuLogical": psutil.cpu_count(),
              "memoryGiB": psutil.virtual_memory().total/1073741824, "gunicornWorkers": 3,
              "pgSharedBuffersMiB": 128, "phases": [], "externalCalls": False}
    monitor_thread = None
    try:
        print("Starting independent PostgreSQL and Redis...", flush=True)
        infrastructure()
        print("Migrating and preparing synthetic fixtures...", flush=True)
        report["fixtures"] = seed()
        before_writes = write_counts()
        accounts = json.loads((VAR / "accounts.json").read_text())
        application("capacity")
        Connection.context = ssl.create_default_context(cafile=str(VAR / "certs/fullchain.pem"))
        report["capacityWarmupSeconds"] = warmup_and_guards(accounts)
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        levels = [1,5] if args.smoke else [1,5,10,20,40,80]
        for workload in ("summary", "legacy"):
            for level in levels:
                result = phase(f"{workload}-{level}", workload, level, args.seconds, accounts)
                report["phases"].append(result)
                if result["errors"] > max(2,result["requests"]*.1) or (result["p99Ms"] or 0) > 5000:
                    print("Escalation stopped for workload due to error/latency threshold",flush=True)
                    break
        for level in ([5] if args.smoke else [5,20,40,80]):
            report["phases"].append(phase(f"mixed-{level}","mixed",level,args.seconds,accounts))
        report["phases"].append(phase("soak-20","soak",20,args.soak_seconds,accounts))
        report["phases"].append(phase("upload-5","upload",5,60,accounts,total_per_user=3))
        stop("nginx")
        stop("api")
        application("limits")
        Connection.context = ssl.create_default_context(cafile=str(VAR / "certs/fullchain.pem"))
        report["limitsWarmupSeconds"] = warmup_and_guards(accounts)
        report["phases"].append(phase("production-limits-20","summary",20,args.seconds,accounts))
        report["writeIntegrity"] = verify_writes(before_writes)
        report["completed"] = True
    except Exception as exc:
        report["completed"] = False
        report["setupOrRunError"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        MONITOR_STOP.set()
        if monitor_thread:
            monitor_thread.join(timeout=2)
        (VAR / f"metrics{RESULT_SUFFIX}.json").write_text(json.dumps(report,indent=2))
        (VAR / f"resources{RESULT_SUFFIX}.json").write_text(json.dumps(RESOURCES))
        try:
            from django.db import connections
            connections.close_all()
        except ImportError:
            pass
        for name in ("nginx","api","redis","postgres"):
            stop(name)
        print("Test services stopped; private synthetic database retained locally.",flush=True)


if __name__ == "__main__":
    main()
