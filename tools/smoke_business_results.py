"""Real local HTTP/worker/R verification of the two result corrections.

Uses the already imported HIT sample and explicitly synthetic numeric input.
Retains new acceptance records and never calls models or biological APIs.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys

from postgres_acceptance import APP, VAR, environment
from smoke_local_workspace import LocalClient, wait_task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=VAR/"business-http-acceptance-20261020.json")
    args = parser.parse_args()
    destination = args.output.resolve()
    if destination.parent != VAR.resolve() or destination.suffix != ".json" or destination.exists():
        parser.error("Choose a new JSON report directly under the private acceptance directory before rerunning.")
    environment(); sys.path.insert(0, str(APP))
    import django
    django.setup()
    from apps.core.models import AnalysisTask
    before = dict(AnalysisTask.objects.values_list("id", "result"))
    accounts = json.loads((VAR / "accounts.json").read_text())
    clients = {key: LocalClient(value, base_url="http://127.0.0.1:5174", csrf_cookie_name="tcm_pg_csrf") for key,value in accounts.items()}
    owner, other = clients["a"], clients["b"]
    _, searched = owner.request("/api/v1/catalog/herb-evidence/batch/", method="POST", data={"queryType":"herb","queries":["石榴皮"]})
    page = searched["results"][0]
    assert len(page["targets"]) == 29 and len(page["relations"]) == 58
    _, graph = owner.request("/api/v1/catalog/herb-evidence/analyses/", method="POST", expected=201,
        data={"queryType":"herb","queries":["石榴皮"],"expectedResultSha256":searched["resultSha256"]})
    assert graph["input_parameters"]["algorithmVersion"] == "catalog-evidence-0.4"
    assert graph["result"]["counts"]["nodes"] == 31 and graph["result"]["counts"]["evidenceRecords"] == 58
    _, network = owner.request("/api/v1/analysis/network-pharmacology/", method="POST", data={"herb":"石榴皮","disease":"NO_MATCH_SYNTHETIC"})
    assert network["summary"]["herbTargetCount"] == 29 and not network["targets"]
    assert len(network["raw"]["herbLinks"]) == 29
    assert all(row["sourceRecordId"].split(":")[1] == row["herbSourceRecordId"].split(":")[1] for row in network["raw"]["herbLinks"])
    (VAR / "business-network-http-result.json").write_text(json.dumps(network,ensure_ascii=False,indent=2))
    artifacts = 0
    def render(task_id, key):
        nonlocal artifacts
        _, queued = owner.request(f"/api/v1/research/analysis-tasks/{task_id}/visualizations/", method="POST", expected=202, data={"chartKey":key})
        task = wait_task(owner, queued["id"])
        for item in task["result"]["artifacts"]:
            _, content = owner.request(item["downloadUrl"])
            assert hashlib.sha256(content).hexdigest() == item["sha256"]
            other.request(item["downloadUrl"],expected=404)
            artifacts += 1
        assert {item["format"] for item in task["result"]["artifacts"]} == {"svg","png","pdf","html"}
        return task["id"]
    graph_render = render(graph["id"], "evidence_network")
    content = b"Gene,log2FC,PValue,FDR\nMAPK1,2,.001,-.2\nMMP9,2,1.2,.01\nBcl2l1,2,.01,\nMAPK1,2,.9,.01\n"
    boundary = "BusinessResultSyntheticStatistics"
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n合成统计边界验收（非实验数据）\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic-statistics.csv"\r\nContent-Type: text/csv\r\n\r\n').encode() + content + f"\r\n--{boundary}--\r\n".encode()
    _, dataset = owner.request("/api/v1/research/datasets/", method="POST", expected=201, raw=body,content_type=f"multipart/form-data; boundary={boundary}")
    _, queued = owner.request(f'/api/v1/research/datasets/{dataset["id"]}/analyze/',method="POST",expected=202,data={
        "thresholds":{"log2FcMin":1,"pValueMax":.05,"fdrMax":.05},"externalReactome":False,"externalString":False,"externalGProfiler":False})
    task = wait_task(owner,queued["id"])
    assert task["result"]["algorithmVersion"] == "proteomics-py-1.9"
    assert task["result"]["qc"]["invalidNumericValueRowCount"] == 2 and task["result"]["summary"]["selectedRowCount"] == 2
    url = f'/api/v1/research/analysis-tasks/{task["id"]}/'
    _, page = owner.request(url + "rows/")
    assert [row["selected"] for row in sorted(page["results"],key=lambda r:r["row_index"])] == [False,False,True,True]
    assert all(row["mapping_status"] == "unverified" for row in page["results"])
    for kind, signature in [("csv", None),("xlsx",b"PK"),("pdf",b"%PDF")]:
        _, exported = owner.request(url + f"export/?file_format={kind}")
        if signature:
            assert exported.startswith(signature)
        else:
            rows = list(csv.DictReader(io.StringIO(exported.decode("utf-8-sig"))))
            assert len(rows) == 4 and "invalid_numeric_value" in exported.decode()
        other.request(url + f"export/?file_format={kind}",expected=404)
    volcano_render = render(task["id"], "proteomics_volcano")
    other.request(f'/api/v1/research/analysis-tasks/{graph["id"]}/',expected=404)
    assert before == dict(AnalysisTask.objects.filter(pk__in=before).values_list("id","result"))
    report = {"passed":True,"herb":"石榴皮","targets":29,"sourceRecords":58,"graphNodes":31,"networkRawRows":29,
              "graphTaskId":graph["id"],"graphRenderTaskId":graph_render,"networkTaskId":network["taskId"],
              "datasetId":dataset["id"],"proteomicsTaskId":task["id"],"volcanoRenderTaskId":volcano_render,
              "syntheticNumericRows":4,"invalidRowsExcluded":2,"selectedRows":2,"artifactsVerified":artifacts,
              "privateExportsVerified":["csv","xlsx","pdf"],"historicalResultsUnchanged":True,"externalCalls":False}
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
