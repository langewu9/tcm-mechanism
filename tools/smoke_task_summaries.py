"""Compare private summary/detail HTTP responses on existing local PG fixtures."""
import hashlib
import json
import sys

from postgres_acceptance import APP, VAR, environment
from smoke_local_workspace import LocalClient


def fetch(client, path):
    assert path.startswith("/api/v1/research/analysis-tasks/")
    with client.http.open("http://127.0.0.1:5174" + path, timeout=15) as response:
        content = response.read()
        assert "no-store" in response.headers["Cache-Control"]
        return json.loads(content), len(content)


def main():
    environment()
    accounts = json.loads((VAR / "accounts.json").read_text())
    owner = LocalClient(accounts["a"], base_url="http://127.0.0.1:5174", csrf_cookie_name="tcm_pg_csrf")
    other = LocalClient(accounts["b"], base_url="http://127.0.0.1:5174", csrf_cookie_name="tcm_pg_csrf")
    base = "/api/v1/research/analysis-tasks/"
    full, full_bytes = fetch(owner, base)
    summaries, summary_bytes = fetch(owner, base + "summaries/")
    assert full["count"] == summaries["count"]
    assert [row["id"] for row in full["results"]] == [row["id"] for row in summaries["results"]]
    hashes = {}
    for saved, summary in zip(full["results"], summaries["results"]):
        assert not ({"result", "input_parameters", "source_releases"} & summary.keys())
        detail, _ = fetch(owner, base + f'{saved["id"]}/')
        assert detail == saved, "Summary optimization changed a full historical record"
        hashes[saved["id"]] = hashlib.sha256(json.dumps(detail["result"], sort_keys=True).encode()).hexdigest()
        other.request(base + f'{saved["id"]}/', expected=404)
    other_page, _ = fetch(other, base + "summaries/")
    assert all(row["owner_id"] == accounts["b"]["id"] for row in other_page["results"])
    assert full_bytes > summary_bytes

    sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.db import connection, transaction
    from django.test.utils import CaptureQueriesContext
    from rest_framework.test import APIClient

    api = APIClient()
    api.force_authenticate(get_user_model().objects.get(pk=accounts["a"]["id"]))
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
        with CaptureQueriesContext(connection) as captured:
            response = api.get(base + "summaries/")
        assert response.status_code == 200
    report = {"count": full["count"], "fullListBytes": full_bytes, "summaryListBytes": summary_bytes,
              "reductionPercent": round((1 - summary_bytes / full_bytes) * 100, 2),
              "summaryQueriesExcludingSession": len(captured), "historicalResultHashes": hashes,
              "checks": ["actual Vite/Django HTTP", "same task IDs/order/count", "full details unchanged",
                         "cross-owner access denied", "private responses not cacheable"],
              "externalCalls": False, "newResearchRecords": 0}
    output = APP / "var/database-performance-audit"
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary-http.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key != "historicalResultHashes"}, indent=2))


if __name__ == "__main__":
    main()
