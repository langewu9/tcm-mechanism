"""Bounded local TLS/WSGI acceptance, using existing synthetic PG accounts.

Run only with tools/framework_acceptance.py api and proxy. Creates login
sessions, but does not upload data, enqueue tasks or contact external services.
"""
from concurrent.futures import ThreadPoolExecutor
import http.client
from http.cookies import SimpleCookie
import json
from pathlib import Path
import socket
import ssl
import statistics
import sys
import time

from framework_acceptance import APP, DOMAIN, ROOT, VAR, configure


CONTEXT = ssl.create_default_context(cafile=str(VAR / "certs/fullchain.pem"))


class LocalTLS(http.client.HTTPSConnection):
    def connect(self):
        self.sock = CONTEXT.wrap_socket(
            socket.create_connection(("127.0.0.1", 8444), self.timeout), server_hostname=DOMAIN,
        )


class Client:
    def __init__(self, cookies=None):
        self.cookies = dict(cookies or {})

    def request(self, path, *, method="GET", data=None, raw=None, headers=None, expected=200):
        assert path.startswith("/") and not path.startswith("//")
        connection = LocalTLS(DOMAIN, 8444, timeout=15)
        request_headers = {
            "Content-Type": "application/json", "Origin": f"https://{DOMAIN}:8444",
            "Referer": f"https://{DOMAIN}:8444/",
            "Cookie": "; ".join(f"{key}={value}" for key, value in self.cookies.items()),
            "X-CSRFToken": self.cookies.get("tcm_framework_csrf", ""),
        }
        request_headers.update(headers or {})
        body = json.dumps(data).encode() if data is not None else raw
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            payload = response.read()
            response_headers = dict(response.getheaders())
            for name, value in response.getheaders():
                if name.lower() == "set-cookie":
                    parsed = SimpleCookie()
                    parsed.load(value)
                    self.cookies.update({key: item.value for key, item in parsed.items()})
            assert response.status == expected, (path, response.status, expected)
            return response_headers, payload
        finally:
            connection.close()

    def login(self, account):
        self.request("/api/v1/auth/csrf/")
        headers, body = self.request("/api/v1/auth/session/", method="POST", data={
            "username": account["username"], "password": account["password"],
        })
        assert json.loads(body)["authenticated"]
        session = headers["Set-Cookie"]
        assert "HttpOnly" in session and "Secure" in session and "SameSite=Lax" in session


def envelope(headers, body, code):
    value = json.loads(body)["error"]
    assert value["code"] == code
    assert value["requestId"] == headers["X-Request-ID"]
    assert "no-store" in headers["Cache-Control"]


def security_headers(headers):
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Strict-Transport-Security"] == "max-age=31536000"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


def query_budgets(account):
    configure()
    sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.db import connection, transaction
    from django.test.utils import CaptureQueriesContext
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(get_user_model().objects.get(pk=account["id"]))
    result = {}
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
        for key, path in (
            ("tasks", "/api/v1/research/analysis-tasks/"),
            ("datasets", "/api/v1/research/datasets/"),
        ):
            with CaptureQueriesContext(connection) as captured:
                response = client.get(path, SERVER_NAME=DOMAIN, HTTP_X_FORWARDED_PROTO="https")
            assert response.status_code == 200
            result[key] = {"queries": len(captured), "records": response.data["count"], "bytes": len(response.content)}
    return result


def main():
    if "--unavailable" in sys.argv:
        headers, body = Client().request("/api/v1/health/", expected=503)
        envelope(headers, body, "SERVICE_UNAVAILABLE")
        security_headers(headers)
        print("PASS: stopped upstream yields safe JSON 503 with security headers and request ID")
        return

    plain = http.client.HTTPConnection("127.0.0.1", 8084, timeout=5)
    plain.request("GET", "/research", headers={"Host": DOMAIN})
    response = plain.getresponse()
    assert response.status == 301 and response.getheader("Location") == f"https://{DOMAIN}:8444/research"
    response.read()
    plain.close()
    plain = http.client.HTTPConnection("127.0.0.1", 8084, timeout=5)
    plain.request("GET", "/", headers={"Host": "untrusted.example.test"})
    try:
        plain.getresponse()
    except http.client.RemoteDisconnected:
        pass
    else:
        raise AssertionError("Unknown HTTP Host was accepted")
    finally:
        plain.close()
    try:
        with socket.create_connection(("127.0.0.1", 8444), 5) as raw_socket:
            with ssl._create_unverified_context().wrap_socket(raw_socket, server_hostname="untrusted.example.test"):
                raise AssertionError("Unknown TLS SNI was accepted")
    except ssl.SSLError:
        pass

    anonymous = Client()
    headers, _ = anonymous.request("/research?token=SYNTHETIC_SECRET")
    security_headers(headers)
    assert "no-cache" in headers["Cache-Control"]
    assert headers.get("Server", "") == "nginx"
    anonymous.request("/assets/missing.js", expected=404)
    anonymous.request("/media/private.csv", expected=404)
    asset = next((ROOT / "web/dist/assets").glob("index-*.js"))
    headers, compressed = anonymous.request(f"/assets/{asset.name}", headers={"Accept-Encoding": "gzip"})
    assert "max-age=31536000" in headers["Cache-Control"] and headers["Content-Encoding"] == "gzip"
    assert len(compressed) < asset.stat().st_size
    headers, body = anonymous.request("/api/v1/research/datasets/", expected=401)
    envelope(headers, body, "AUTHENTICATION_REQUIRED")

    accounts = json.loads((APP / "var/postgres-acceptance/accounts.json").read_text())
    owner, other = Client(), Client()
    owner.login(accounts["a"])
    other.login(accounts["b"])
    headers, body = owner.request("/api/v1/research/datasets/?audit=SYNTHETIC_PRIVATE_QUERY")
    private_request_id = headers["X-Request-ID"]
    security_headers(headers)
    assert "private" in headers["Cache-Control"] and "no-store" in headers["Cache-Control"]
    datasets = json.loads(body)["results"]
    assert datasets and all(item["owner_id"] == accounts["a"]["id"] for item in datasets)
    headers, body = other.request(f'/api/v1/research/datasets/{datasets[0]["id"]}/', expected=404)
    envelope(headers, body, "NOT_FOUND")
    headers, body = owner.request("/api/v1/auth/session/", method="DELETE", headers={"X-CSRFToken": ""}, expected=403)
    envelope(headers, body, "CSRF_FAILED")
    headers, body = owner.request("/api/v1/research/cases/", method="POST", raw=b"{bad", expected=400)
    envelope(headers, body, "VALIDATION_ERROR")
    headers, body = owner.request("/api/v1/research/cases/", method="POST", raw=b"x" * (2 * 1024 * 1024), expected=413)
    envelope(headers, body, "PAYLOAD_TOO_LARGE")
    security_headers(headers)

    # Five concurrent clients, fifty bounded reads of existing isolated fixtures.
    def read_one(index):
        started = time.perf_counter()
        path = "/api/v1/research/analysis-tasks/" if index % 2 else "/api/v1/research/datasets/"
        headers, data = Client(owner.cookies).request(path)
        assert "no-store" in headers["Cache-Control"]
        return (time.perf_counter() - started) * 1000, len(data)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=5) as pool:
        samples = list(pool.map(read_one, range(50)))
    elapsed = time.perf_counter() - started
    times = sorted(item[0] for item in samples)

    # A changing client-supplied forwarding chain cannot evade the edge IP limit.
    throttled = 0
    for index in range(12):
        connection = LocalTLS(DOMAIN, 8444, timeout=5)
        connection.request("POST", "/api/v1/auth/session/", body=b"{}", headers={
            "Content-Type": "application/json", "X-Forwarded-For": f"192.0.2.{index + 1}",
        })
        response = connection.getresponse()
        body = response.read()
        headers = dict(response.getheaders())
        assert response.status in {403, 429}, response.status
        if response.status == 429:
            throttled += 1
            envelope(headers, body, "RATE_LIMITED")
            security_headers(headers)
        connection.close()
    assert throttled > 0

    queries = query_budgets(accounts["a"])
    for name in ("nginx-access.log", "gunicorn.log"):
        log = (VAR / name).read_text()
        assert "SYNTHETIC_SECRET" not in log and "SYNTHETIC_PRIVATE_QUERY" not in log, name
        assert private_request_id in log, (name, "response request ID missing from access log")
    report = {
        "externalModelOrDatabaseCalls": False, "tls": "self-signed localhost test only",
        "checks": ["HTTPS redirect", "unknown Host and SNI rejected", "secure session cookie", "CSRF enforced",
                   "owner isolation", "private no-store", "static gzip/cache", "SPA no-cache",
                   "JSON 400/401/403/404/413/429 envelopes", "IP edge limit ignores spoofed forwarding chain",
                   "query strings excluded from proxy and WSGI logs"],
        "performance": {"workers": 2, "concurrency": 5, "requests": len(samples), "failures": 0,
                        "elapsedSeconds": round(elapsed, 3), "p50Ms": round(statistics.median(times), 2),
                        "p95Ms": round(times[47], 2), "maxMs": round(times[-1], 2)},
        "queryBudgets": queries,
    }
    (VAR / "http-acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
