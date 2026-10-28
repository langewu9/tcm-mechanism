"""Exercise production HTTP configuration against the isolated local PG profile.

No system services, certificates, preview settings or production data are changed.
Requires the ignored PostgreSQL acceptance profile and an extracted Nginx binary.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys

from postgres_acceptance import APP, ROOT, environment


VAR = APP / "var/framework-audit"
RUNTIME = VAR / "runtime/root/usr/sbin/nginx"
DOMAIN = "platform.example.test"


def configure():
    environment()
    os.environ.update(
        DJANGO_DEBUG="false", DJANGO_ALLOWED_HOSTS=f"127.0.0.1,localhost,{DOMAIN}",
        DJANGO_SECURE_SSL_REDIRECT="true", DJANGO_USE_X_FORWARDED_PROTO="true",
        DJANGO_SESSION_COOKIE_SECURE="true", DJANGO_CSRF_COOKIE_SECURE="true",
        DJANGO_SECURE_HSTS_SECONDS="31536000",
        DJANGO_SESSION_COOKIE_NAME="tcm_framework_session", DJANGO_CSRF_COOKIE_NAME="tcm_framework_csrf",
        CSRF_TRUSTED_ORIGINS=f"https://{DOMAIN}:8444", PUBLIC_BASE_URL=f"https://{DOMAIN}:8444",
        CACHE_URL="redis://127.0.0.1:6389/6", GUNICORN_BIND="127.0.0.1:8022", GUNICORN_WORKERS="2",
    )


def prepare():
    certs = VAR / "certs"
    certs.mkdir(parents=True, exist_ok=True)
    key = certs / "privkey.pem"
    if not key.exists():
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3",
            "-subj", f"/CN={DOMAIN}", "-addext", f"subjectAltName=DNS:{DOMAIN}",
            "-keyout", str(key), "-out", str(certs / "fullchain.pem"),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        key.chmod(0o600)
    rendered = VAR / "nginx"
    rendered.mkdir(exist_ok=True)
    for name in ("body", "proxy", "fastcgi", "uwsgi", "scgi"):
        (rendered / name).mkdir(exist_ok=True)
    for name in ("default.conf.template", "proxy-api.conf", "security-headers.conf", "rate-limits.conf"):
        content = (ROOT / "deploy/nginx" / name).read_text()
        for before, after in {
            "${PUBLIC_DOMAIN}": DOMAIN,
            "listen 80": "listen 127.0.0.1:8084",
            "listen 443": "listen 127.0.0.1:8444",
            "https://$host$request_uri": "https://$host:8444$request_uri",
            "/etc/nginx/snippets/": f"{rendered}/",
            "/etc/nginx/certs/": f"{certs}/",
            "/usr/share/nginx/html": str(ROOT / "web/dist"),
            "/srv/django-static/": f"{APP}/staticfiles/",
            "/var/log/nginx/access.log": str(VAR / "nginx-access.log"),
            "http://api:8020": "http://127.0.0.1:8022",
        }.items():
            content = content.replace(before, after)
        (rendered / name.replace(".template", "")).write_text(content)
    mime = VAR / "runtime/root/etc/nginx/mime.types"
    # Use a minimal Nginx MIME map when only the executable package is present.
    if not mime.exists():
        mime = rendered / "mime.types"
        mime.write_text("types { text/html html; text/css css; application/javascript js; image/svg+xml svg; application/json json; }\n")
    (rendered / "nginx.conf").write_text(f"""worker_processes 1;
pid {rendered}/nginx.pid;
error_log {VAR}/nginx-error.log warn;
events {{ worker_connections 128; }}
http {{
  include {mime};
  client_body_temp_path {rendered}/body;
  proxy_temp_path {rendered}/proxy;
  fastcgi_temp_path {rendered}/fastcgi;
  uwsgi_temp_path {rendered}/uwsgi;
  scgi_temp_path {rendered}/scgi;
  include {rendered}/rate-limits.conf;
  include {rendered}/default.conf;
}}
""")
    subprocess.run([str(RUNTIME), "-p", f"{rendered}/", "-c", str(rendered / "nginx.conf"), "-t"], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "api", "proxy", "manage"])
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    configure()
    if args.command == "prepare":
        prepare()
        return
    os.chdir(APP)
    if args.command == "api":
        command = [sys.executable, "-m", "gunicorn", "--config", "python:config.gunicorn", *args.arguments, "config.wsgi:application"]
    elif args.command == "proxy":
        command = [str(RUNTIME), "-p", f"{VAR}/nginx/", "-c", str(VAR / "nginx/nginx.conf"), "-g", "daemon off;"]
    else:
        if not args.arguments:
            parser.error("manage requires a management command")
        command = [sys.executable, "manage.py", *args.arguments]
    os.execv(command[0], command)


if __name__ == "__main__":
    main()
