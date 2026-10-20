"""Verify the existing local TCMSP sample -> saved query -> private R figures.

Uses the isolated local preview and acceptance accounts. Keeps the resulting
private task and figures for inspection; does not change catalogue records.
"""
import hashlib
import json
import os
import sys

from smoke_local_workspace import ROOT, VAR, LocalClient, wait_task


def main():
    sys.path.insert(0, str(ROOT / "python_app"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()
    from django.conf import settings
    from django.core.files.storage import default_storage
    from apps.core.models import AnalysisTask, VisualizationArtifact
    from apps.core.services.visualization import build_chart_payload
    assert settings.DEBUG and settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
    accounts = json.loads((VAR / "local-acceptance-users.json").read_text())
    owner, other = LocalClient(accounts["a"]), LocalClient(accounts["b"])
    administrator = LocalClient(json.loads((VAR / "local-preview-login.json").read_text()))
    query = {"queryType": "herb", "queries": ["矮地茶"]}
    _, searched = owner.request("/api/v1/catalog/herb-evidence/batch/", method="POST", data=query)
    records = {row["id"]: row for item in searched["results"] for row in item["relations"]}
    assert records, "Import the bounded historical TCMSP sample first."
    nodes = {pk for record in records.values() for pk in (record["subjectId"], record["objectId"])}
    _, saved = owner.request("/api/v1/catalog/herb-evidence/analyses/", method="POST",
                             data={**query, "expectedResultSha256": searched["resultSha256"]}, expected=201)
    result = saved["result"]
    assert saved["owner_id"] == accounts["a"]["id"]
    assert result["resultSha256"] == searched["resultSha256"]
    assert result["counts"]["nodes"] == len(nodes)
    assert result["counts"]["evidenceRecords"] == len(records)
    assert {record["id"] for record in result["evidenceRecords"]} == set(records)
    parent = AnalysisTask.objects.get(pk=saved["id"])
    payload = build_chart_payload(parent, "evidence_network")
    assert {node["id"] for node in payload["data"]} == {f"entity:{pk}" for pk in nodes}
    assert len(payload["edges"]) == result["counts"]["uniqueEdges"]
    parent_url = f'/api/v1/research/analysis-tasks/{saved["id"]}/'
    _, queued = owner.request(parent_url + "visualizations/", method="POST", data={"chartKey": "evidence_network"}, expected=202)
    rendered = wait_task(owner, queued["id"])
    assert rendered["result"]["inputSha256"] == payload["inputSha256"]
    artifacts = rendered["result"]["artifacts"]
    assert {artifact["format"] for artifact in artifacts} == {"svg", "png", "pdf", "html"}
    for artifact in artifacts:
        _, content = owner.request(artifact["downloadUrl"])
        assert hashlib.sha256(content).hexdigest() == artifact["sha256"]
        other.request(artifact["downloadUrl"], expected=404)
    _, reused = owner.request(parent_url + "visualizations/", method="POST", data={"chartKey": "evidence_network"})
    assert reused["id"] == rendered["id"]
    other.request(parent_url, expected=404)
    other.request(f'/api/v1/research/analysis-tasks/{rendered["id"]}/', expected=404)
    _, admin_view = administrator.request(parent_url)
    assert admin_view["owner_id"] == accounts["a"]["id"]
    _, conflict = owner.request("/api/v1/catalog/herb-evidence/analyses/", method="POST",
                               data={**query, "expectedResultSha256": "0" * 64}, expected=409)
    assert conflict["error"]["code"] == "CATALOG_RESULTS_CHANGED"
    png = VisualizationArtifact.objects.get(render_task_id=rendered["id"], file_format="png")
    report = {"historicalSampleOnly": True, "synthetic": False, "taskId": saved["id"],
              "renderTaskId": rendered["id"], "counts": result["counts"],
              "rNodes": len(payload["data"]), "rUniqueEdges": len(payload["edges"]),
              "rendererVersion": rendered["result"]["rendererVersion"], "artifacts": len(artifacts),
              "previewUrl": f'http://127.0.0.1:5173/research?catalogTask={saved["id"]}',
              "pngPath": default_storage.path(png.storage_key),
              "crossOwnerDenied": True, "administratorPreservesOwner": True,
              "searchSnapshotGuard": True, "externalCalls": False}
    (VAR / "catalog-figures-acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
