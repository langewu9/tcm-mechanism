"""Real localhost no-match disease task through session/CSRF and Celery.

Success/large exports use disposable synthetic DB tests. This smoke never adds
synthetic catalogue data to the workspace DB; it retains ONE clearly labelled
failed no-match task and checks that no partial snapshot is published.
"""
import argparse
import json
from pathlib import Path
import sys
import time

from postgres_acceptance import APP, VAR, environment
from smoke_local_workspace import LocalClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Refusing to overwrite a prior smoke report.")
    environment()
    sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.core.serializers.json import DjangoJSONEncoder
    from django.db import connection
    from apps.core.models import AnalysisTask, EvidenceRelation, KnowledgeEntity
    from apps.core.services.complete_evidence import digest
    assert connection.settings_dict["NAME"] == "tcm_acceptance"

    def research_state():
        return {row["id"]: digest(row) for row in AnalysisTask.objects.values("id", "owner_id", "created_by_id", "status", "input_parameters", "result")}
    def catalogue_state():
        result = {"entities": list(KnowledgeEntity.objects.order_by("pk").values()),
                  "relations": list(EvidenceRelation.objects.order_by("pk").values())}
        return digest(json.loads(json.dumps(result, cls=DjangoJSONEncoder)))
    before, catalogue_before = research_state(), catalogue_state()
    accounts = json.loads((VAR / "accounts.json").read_text())
    clients = {key: LocalClient(value, base_url="http://127.0.0.1:5174", csrf_cookie_name="tcm_pg_csrf") for key, value in accounts.items()}
    query = "SYNTHETIC_NOT_IN_CATALOG_DISEASE_20261021"
    _, preview = clients["a"].request(f"/api/v1/catalog/diseases/evidence-search/?query={query}")
    assert preview["matches"] == [] and not preview["truncated"] and len(preview["resultSha256"]) == 64
    _, queued = clients["a"].request("/api/v1/catalog/diseases/evidence-analyses/", method="POST", expected=202,
                                   data={"query": query, "expectedResultSha256": preview["resultSha256"]})
    task_id = queued["id"]
    base = f"/api/v1/research/analysis-tasks/{task_id}"
    for _ in range(80):
        _, task = clients["a"].request(base + "/")
        if task["status"] not in {"queued", "running"}:
            break
        time.sleep(0.25)
    assert task["status"] == "failed" and "没有匹配疾病" in task["error_summary"]
    assert task["result"] == {} and task["owner_id"] == accounts["a"]["id"]
    assert not AnalysisTask.objects.get(pk=task_id).snapshot_rows.exists()
    clients["a"].request(base + "/snapshot-rows/", expected=404)
    clients["a"].request(base + "/snapshot-export/", expected=404)
    clients["b"].request(base + "/", expected=404)
    after = research_state()
    assert all(after.get(pk) == value for pk, value in before.items())
    assert catalogue_state() == catalogue_before
    report = {"scope": __doc__, "taskId": task_id, "status": task["status"], "errorSummary": task["error_summary"],
              "sourceDataInserted": False, "noPartialSnapshot": True, "otherAccountDenied": True,
              "preExistingTasksUnchanged": True, "catalogueUnchanged": True,
              "retainedTaskIds": sorted(set(after) - set(before)), "modelsOrProvidersCalled": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
