"""Real PostgreSQL/HTTP/queue/R acceptance with bounded historical source rows.

Uploads explicitly synthetic numeric measurements, never clinical data. Source
IDs are preserved as unverified assertions, not official cross-database matches.
Creates retained local acceptance records; never operates on the SQLite preview.
"""
import csv
import hashlib
import io
import json
from pathlib import Path
import secrets
import sys
import time

from postgres_acceptance import ROOT, APP, VAR, environment
from smoke_local_workspace import LocalClient, wait_task


def credentials():
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from apps.core.models import ResearcherProfile
    path = VAR / "accounts.json"
    if path.exists():
        return json.loads(path.read_text())
    accounts = {}
    for key, username in [("admin", "pg-local-admin"), ("a", "pg-researcher-a"), ("b", "pg-researcher-b")]:
        if get_user_model().objects.filter(username=username).exists():
            raise RuntimeError("Acceptance username already exists without its credential file; inspect before changing it.")
        password = secrets.token_urlsafe(24)
        user = get_user_model().objects.create_user(username=username, password=password,
            is_staff=key == "admin", is_superuser=key == "admin", is_active=True,
            email=f"{username}@example.test")
        if key != "admin":
            ResearcherProfile.objects.get_or_create(user=user, defaults={"email_verified_at": timezone.now()})
        accounts[key] = {"id": user.pk, "username": username, "password": password}
    path.write_text(json.dumps(accounts, indent=2)); path.chmod(0o600)
    return accounts


def wait_sync(client, source_id, run_id):
    for _ in range(120):
        _, page = client.request(f"/api/v1/admin/sync-runs/?sourceId={source_id}")
        run = next(item for item in page["results"] if item["id"] == run_id)
        if run["status"] == "succeeded":
            return run
        assert run["status"] != "failed", run["error_summary"]
        time.sleep(0.5)
    raise AssertionError("Source acceptance task timed out.")


def main():
    environment()
    sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.conf import settings
    from apps.core.models import DataSource, EntityIdentifier, EvidenceRelation, KnowledgeEntity
    from apps.proteomics.services import ALGORITHM_VERSION
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
    assert settings.DATABASES["default"]["NAME"] == "tcm_acceptance"
    accounts = credentials()
    clients = {key: LocalClient(value, base_url="http://127.0.0.1:5174", csrf_cookie_name="tcm_pg_csrf")
               for key, value in accounts.items()}
    owner, other, admin = clients["a"], clients["b"], clients["admin"]
    source = DataSource.objects.filter(configuration__databaseFile="hit-identity-first100.sqlite3").first()
    if source is None:
        _, created = admin.request("/api/v1/admin/sources/", method="POST", expected=201, data={
            "name": "HIT 原始编号样本（100 行，仅本地验收）", "description": "Historical source assertions; organism unrecorded; not canonical mapping.",
            "databaseFile": "hit-identity-first100.sqlite3", "table": "herb_component_target", "herbColumn": "herb",
            "compoundColumn": "component", "targetColumn": "target", "targetCellMode": "single", "rowMetadataColumn": "extra"})
        source = DataSource.objects.get(pk=created["id"])
    owner.request("/api/v1/admin/sources/", expected=403)
    _, connection = admin.request(f"/api/v1/admin/sources/{source.pk}/test/", method="POST", data={})
    assert connection["rowCount"] == 100
    _, queued = admin.request(f"/api/v1/admin/sources/{source.pk}/sync/", method="POST", data={}, expected=202)
    preview = wait_sync(admin, source.pk, queued["run"]["id"])
    _, applied = admin.request(f'/api/v1/admin/sync-runs/{preview["id"]}/apply/', method="POST", data={}, expected=202)
    run = wait_sync(admin, source.pk, applied["run"]["id"])
    admin.request(f'/api/v1/admin/sync-runs/{preview["id"]}/apply/', method="POST", data={}, expected=400)

    original = json.loads((APP / "var/hit-first100-identity-input.json").read_text())
    headers = original["headers"]
    rows = {item["sourceRow"]: dict(zip(headers, item["values"])) for item in original["rows"]}
    entities = list(KnowledgeEntity.objects.filter(source_release__source=source, is_active=True))
    before_ids = {item.stable_id: item.pk for item in entities}
    assert len(entities) == 63
    assert {item.metadata["sourceEntityId"] for item in entities if item.entity_type == "protein"} == {row["Target ID"] for row in rows.values()}
    assert all(not item.organism for item in entities)
    assert EntityIdentifier.objects.filter(entity__source_release__source=source).count() == 0
    relations = list(EvidenceRelation.objects.filter(source_release=run["release"], is_active=True))
    assert len(relations) == 200
    for edge in relations:
        number = edge.metadata["sourceOrigin"]["sourceRow"]
        assert edge.metadata["sourceOrigin"]["workbookSha256"] == original["sourceSha256"]
        assert edge.metadata["rawFields"] == rows[number]
        assert edge.metadata["sourceIdentity"]["uniprot"] == rows[number]["Uniprot"]
    # Repeat through the same real preview/apply path and preserve all entity PKs.
    _, queued = admin.request(f"/api/v1/admin/sources/{source.pk}/sync/", method="POST", data={}, expected=202)
    repeated = wait_sync(admin, source.pk, queued["run"]["id"])
    _, applied = admin.request(f'/api/v1/admin/sync-runs/{repeated["id"]}/apply/', method="POST", data={}, expected=202)
    repeated = wait_sync(admin, source.pk, applied["run"]["id"])
    assert repeated["preview_summary"]["entitiesUnchanged"] == 63
    assert before_ids == dict(KnowledgeEntity.objects.filter(pk__in=before_ids.values()).values_list("stable_id", "pk"))

    herbs = list(dict.fromkeys(row["Chinese Character"] for row in rows.values()))
    query = {"queryType": "herb", "queries": herbs}
    _, searched = owner.request("/api/v1/catalog/herb-evidence/batch/", method="POST", data=query)
    _, saved = owner.request("/api/v1/catalog/herb-evidence/analyses/", method="POST", data={
        **query, "expectedResultSha256": searched["resultSha256"]}, expected=201)
    assert saved["result"]["counts"]["nodes"] == 63 and saved["result"]["counts"]["evidenceRecords"] == 200
    assert all(item["sourceOrigin"] and item["sourceIdentity"] for item in saved["result"]["evidenceRecords"])
    assert all(item["sourceEntityId"] for item in saved["result"]["network"]["nodes"])
    base = f'/api/v1/research/analysis-tasks/{saved["id"]}/'
    other.request(base, expected=404)
    _, admin_view = admin.request(base)
    assert admin_view["owner_id"] == accounts["a"]["id"]
    (VAR / "saved-historical-evidence.json").write_text(json.dumps(saved, ensure_ascii=False, indent=2))

    artifact_count = 0
    def render(parent_url, chart_key):
        nonlocal artifact_count
        _, queued = owner.request(parent_url + "visualizations/", method="POST", data={"chartKey": chart_key}, expected=202)
        rendered = wait_task(owner, queued["id"])
        assert {item["format"] for item in rendered["result"]["artifacts"]} == {"svg", "png", "pdf", "html"}
        for item in rendered["result"]["artifacts"]:
            _, content = owner.request(item["downloadUrl"])
            assert hashlib.sha256(content).hexdigest() == item["sha256"]
            other.request(item["downloadUrl"], expected=404)
            artifact_count += 1
        return rendered
    graph = render(base, "evidence_network")

    symbols = ["MAPK1", "MMP9", "Bcl2l1"]
    assert set(symbols) <= {row["Symbol"] for row in rows.values()}
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["Gene", "log2FC", "PValue", "FDR"])
    for symbol in symbols:
        writer.writerow([symbol, 2, 0.001, 0.01])
    content = output.getvalue().encode()
    boundary = "IsolatedPgSyntheticNumbers"
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n合成数值验收（HIT 标签，非实验数据）\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic-hit.csv"\r\nContent-Type: text/csv\r\n\r\n').encode() + content + f"\r\n--{boundary}--\r\n".encode()
    _, dataset = owner.request("/api/v1/research/datasets/", method="POST", raw=body,
                              content_type=f"multipart/form-data; boundary={boundary}", expected=201)
    dataset_url = f'/api/v1/research/datasets/{dataset["id"]}/'
    _, queued = owner.request(dataset_url + "analyze/", method="POST", data={
        "thresholds": {"log2FcMin": 1, "fdrMax": 0.05, "pValueMax": 0.05},
        "externalReactome": False, "externalString": False, "externalGProfiler": False}, expected=202)
    task = wait_task(owner, queued["id"])
    assert task["result"]["algorithmVersion"] == ALGORITHM_VERSION
    assert task["result"]["summary"]["databaseMappedCount"] == 0
    assert task["result"]["summary"]["unverifiedSymbolCount"] == 3
    task_url = f'/api/v1/research/analysis-tasks/{task["id"]}/'
    _, page = owner.request(task_url + "rows/")
    for row in page["results"]:
        assert row["mapping_status"] == "unverified"
        namespaces = {item["namespace"] for item in row["external_identifiers"]}
        assert {"source_entity", "source_reported_uniprot"} <= namespaces and "uniprot" not in namespaces
    for file_format, signature in [("csv", None), ("xlsx", b"PK"), ("pdf", b"%PDF")]:
        _, exported = owner.request(task_url + f"export/?file_format={file_format}")
        if signature:
            assert exported.startswith(signature)
        else:
            assert b"source_reported_uniprot" in exported and b"T79WXA" in exported
        other.request(task_url + f"export/?file_format={file_format}", expected=404)
    volcano = render(task_url, "proteomics_volcano")
    owner.request(dataset_url, method="DELETE", expected=204)
    _, kept = owner.request(dataset_url + "download/")
    assert kept == content
    other.request(dataset_url + "restore/", method="POST", expected=404)
    _, restored = admin.request(dataset_url + "restore/", method="POST")
    assert restored["owner_id"] == accounts["a"]["id"] and restored["archived_at"] is None
    other.request(task_url + "rows/", expected=404)
    report = {"database": "PostgreSQL 17.11", "sourceId": source.pk, "sourceRows": 100,
              "entityCount": 63, "sourceRelations": 200, "graphCounts": saved["result"]["counts"],
              "graphTaskId": saved["id"], "graphRenderTaskId": graph["id"], "datasetId": dataset["id"],
              "proteomicsTaskId": task["id"], "volcanoRenderTaskId": volcano["id"], "artifactsVerified": artifact_count,
              "sourceAssertionsAreUnverified": True, "rawRowsAndIdsPreserved": True, "repeatImportIdempotent": True,
              "syntheticNumericMeasurements": True, "crossOwnerDenied": True, "archiveRestoreOriginalPreserved": True,
              "externalModelOrBiologicalApiCalls": False, "baseUrl": "http://127.0.0.1:5174"}
    (VAR / "acceptance-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
