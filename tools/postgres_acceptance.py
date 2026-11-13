"""Run the isolated local acceptance profile; never rewrite the preview .env.

Requires a private profile and a PostgreSQL 17 runtime provisioned under var.
Use separate terminals for postgres, api, worker and web. Credentials and data
remain in the ignored acceptance directory. External models/schedules are off.
"""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote

import environ


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "python_app"
VAR = APP / "var/postgres-acceptance"
PG_BIN = VAR / "runtime/root/usr/lib/postgresql/17/bin"


def environment():
    profile = json.loads((VAR / "profile.json").read_text())
    if profile["host"] != "127.0.0.1" or profile["port"] != 55439 or profile["database"] != "tcm_acceptance":
        raise SystemExit("Refusing an unexpected acceptance database profile.")
    environ.Env.read_env(APP / ".env", overwrite=False)
    uri = f"postgresql://{quote(profile['user'])}:{quote(profile['password'])}@127.0.0.1:55439/tcm_acceptance"
    os.environ.update(DJANGO_SETTINGS_MODULE="config.settings", DJANGO_DEBUG="true", DATABASE_URL=uri,
        DJANGO_SECRET_KEY="isolated-acceptance-" + profile["password"],
        MEDIA_ROOT=str(VAR / "media"), SQLITE_SOURCE_ROOT=str(VAR / "source-databases"),
        CELERY_BROKER_URL="redis://127.0.0.1:6389/4", CACHE_URL="redis://127.0.0.1:6389/5",
        SOURCE_SCHEDULED_PREVIEWS_ENABLED="false", CASE_MODEL_BASE_URL="", CASE_MODEL_API_KEY="",
        # The provided HERB workbook has 869,380 rows. Keep this local profile
        # bounded at one million; production settings retain their own limit.
        SQLITE_SOURCE_MAX_ROWS="1000000",
        # Explicit local lookup scope for the previously verified HIT source.
        COMPOUND_SOURCE_ALIASES='{"HIT":["sqlite-9576c61feff9"]}',
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DJANGO_ALLOWED_HOSTS="127.0.0.1,localhost,testserver",
        CSRF_TRUSTED_ORIGINS="http://127.0.0.1:5174,http://127.0.0.1:8021",
        DJANGO_SESSION_COOKIE_NAME="tcm_pg_session", DJANGO_CSRF_COOKIE_NAME="tcm_pg_csrf",
        DJANGO_SECURE_SSL_REDIRECT="false", DJANGO_SESSION_COOKIE_SECURE="false", DJANGO_CSRF_COOKIE_SECURE="false",
        TCM_API_PROXY_TARGET="http://127.0.0.1:8021",
        LD_LIBRARY_PATH=str(VAR / "runtime/root/usr/lib/x86_64-linux-gnu"))
    return profile


def execute(args, cwd=ROOT):
    os.chdir(cwd)
    os.execv(str(args[0]), [str(item) for item in args])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=["postgres", "api", "worker", "web", "manage"])
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    profile = environment()
    if args.service == "postgres":
        execute([PG_BIN / "postgres", "-D", VAR / "data", "-h", "127.0.0.1", "-p", "55439",
                 "-k", profile["socket"], "-c", "max_connections=40", "-c", "shared_buffers=32MB", "-c", "jit=off"])
    elif args.service == "api":
        # runserver creates request threads; keeping their DB connections alive
        # can exhaust this isolated profile's 40 slots during browser acceptance.
        # Leave persistent-connection policy for workers/production unchanged.
        os.environ["DATABASE_CONN_MAX_AGE"] = "0"
        execute([sys.executable, APP / "manage.py", "runserver", "127.0.0.1:8021", "--noreload"])
    elif args.service == "worker":
        # Keep a parent process for interruption and hard-timeout callbacks.
        execute([APP / ".venv/bin/celery", "-A", "config", "worker", "--loglevel=INFO", "--pool=prefork",
                 "--concurrency=1", "--queues=celery,r_visualization", "--hostname=pg-acceptance@%h"], APP)
    elif args.service == "web":
        node = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
        execute([node, ROOT / "web/node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "5174", "--strictPort"], ROOT / "web")
    else:
        if not args.arguments:
            parser.error("manage requires a Django management command")
        execute([sys.executable, APP / "manage.py", *args.arguments])


if __name__ == "__main__":
    main()
