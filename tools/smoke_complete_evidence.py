"""Real localhost session/CSRF + Celery complete snapshots; retain new test tasks.

Uses existing local HIT sample evidence. Preserves every pre-existing task and
all catalogue rows. No model/provider calls. Does not import new source data.
"""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys

from postgres_acceptance import APP, VAR, environment
from smoke_local_workspace import LocalClient, wait_task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Refusing to overwrite a prior report.")
    environment()
    sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.db import connection
    from django.core.serializers.json import DjangoJSONEncoder
    from apps.core.models import AnalysisTask, EvidenceRelation
    from apps.core.services.complete_evidence import canonical, digest
    from apps.core.services.herb_evidence import batch_herb_component_evidence
    assert connection.settings_dict["NAME"] == "tcm_acceptance"
    def tasks():
        return {row["id"]: digest(row) for row in AnalysisTask.objects.values("id", "owner_id", "created_by_id", "input_parameters", "result", "status")}
    before = tasks()
    def evidence_state():
        return digest(json.loads(json.dumps(list(EvidenceRelation.objects.order_by("id").values()), cls=DjangoJSONEncoder)))
    evidence_before = evidence_state()
    accounts = json.loads((VAR / "accounts.json").read_text())
    clients = {key: LocalClient(value, base_url="http://127.0.0.1:5174", csrf_cookie_name="tcm_pg_csrf") for key, value in accounts.items()}
    owner, other = clients["a"], clients["b"]
    _, preview = owner.request("/api/v1/catalog/herb-evidence/batch/", method="POST", data={"queryType": "herb", "queries": ["石榴皮"]})
    expected = batch_herb_component_evidence(query_type="herb", queries=["石榴皮"])
    assert preview["resultSha256"] == expected["resultSha256"]
    report = {"scope": __doc__, "tasks": [], "noExternalCalls": True}
    for url, data in (("/api/v1/catalog/herb-evidence/analyses/", {
        "queryType": "herb", "queries": ["石榴皮"], "expectedResultSha256": preview["resultSha256"], "complete": True}),
        ("/api/v1/analysis/network-pharmacology/", {"herb": "石榴皮、酸石榴", "disease": "NO_MATCH_COMPLETE_HTTP_SMOKE", "complete": True})):
        _, queued = owner.request(url, method="POST", data=data, expected=202)
        task = wait_task(owner, queued["id"])
        assert task["owner_id"] == accounts["a"]["id"] and task["requested_by_id"] == accounts["a"]["id"]
        manifest = task["result"]["snapshot"]
        assert manifest["complete"] is True
        base = f"/api/v1/research/analysis-tasks/{task['id']}"
        _, first = owner.request(base + "/snapshot-rows/?page=1&page_size=20")
        assert first["snapshotSha256"] == manifest["sha256"] and first["count"] == manifest["tables"]["evidenceRecords"]["count"]
        _, content = owner.request(base + "/snapshot-export/")
        lines = [json.loads(line) for line in content.decode().splitlines()]
        frozen = lines[0]
        sha = frozen["snapshot"].pop("sha256")
        assert sha == digest({"parameters": frozen["parameters"], "result": frozen["result"], "manifest": frozen["snapshot"]})
        for name, info in manifest["tables"].items():
            rows = [row["payload"] for row in lines[1:] if row["table"] == name]
            assert len(rows) == info["count"]
            assert hashlib.sha256("".join(canonical(row) + "\n" for row in rows).encode()).hexdigest() == info["sha256"]
        _, content = owner.request(base + "/snapshot-export/?table=evidenceRecords&file_format=csv")
        assert len(list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))) == first["count"]
        other.request(base + "/snapshot-rows/", expected=404)
        other.request(base + "/snapshot-export/", expected=404)
        item = {"id": task["id"], "analysisKind": task["input_parameters"]["analysisKind"],
                "counts": {name: table["count"] for name, table in manifest["tables"].items()},
                "snapshotSha256": sha, "allHashesMatch": True, "otherAccountDenied": True,
                "url": f"http://127.0.0.1:5174/research?catalogTask={task['id']}" if task["input_parameters"]["analysisKind"] == "catalog_evidence"
                       else f"http://127.0.0.1:5174/network-pharmacology?networkTask={task['id']}"}
        report["tasks"].append(item)
    after = tasks()
    assert all(after.get(key) == value for key, value in before.items())
    assert evidence_before == evidence_state()
    report.update(preExistingTasksUnchanged=True, catalogueUnchanged=True,
                  retainedNewTaskIds=sorted(set(after) - set(before)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
