"""Real local queue test of historical names versus normalized gene symbols.

The numeric measurements are explicitly synthetic. Catalogue labels are taken
from the already audited legacy sample; no external mapping service is called.
"""
import csv
import hashlib
import io
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
    assert settings.DEBUG and settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
    accounts = json.loads((VAR / "local-acceptance-users.json").read_text())
    owner, other = LocalClient(accounts["a"]), LocalClient(accounts["b"])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Gene", "log2FC", "PValue", "FDR"])
    historical_names = ["2-hydroxy-6-oxo-7-methylocta-2,4-dienoate hydrolase", "Acetylcholinesterase"]
    for label in [*historical_names, "TP53"]:
        writer.writerow([label, 2, 0.001, 0.01])
    content = output.getvalue().encode()
    boundary = "MappingConsistencySyntheticNumbers"
    header = (f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n合成映射验收（非实验数值）\r\n'
              f'--{boundary}\r\nContent-Disposition: form-data; name="description"\r\n\r\nSYNTHETIC measurements. Historical labels are not verified gene identities.\r\n'
              f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic-mapping-check.csv"\r\nContent-Type: text/csv\r\n\r\n').encode()
    _, dataset = owner.request("/api/v1/research/datasets/", method="POST", raw=header + content + f"\r\n--{boundary}--\r\n".encode(), content_type=f"multipart/form-data; boundary={boundary}", expected=201)
    assert dataset["content_sha256"] == hashlib.sha256(content).hexdigest()
    _, queued = owner.request(f'/api/v1/research/datasets/{dataset["id"]}/analyze/', method="POST", data={
        "thresholds": {"log2FcMin": 1, "fdrMax": 0.05, "pValueMax": 0.05},
        "externalReactome": False, "externalString": False, "externalGProfiler": False}, expected=202)
    task = wait_task(owner, queued["id"])
    from apps.proteomics.services import ALGORITHM_VERSION
    assert task["result"]["algorithmVersion"] == ALGORITHM_VERSION, "Restart the local worker before this test."
    summary = task["result"]["summary"]
    assert summary["selectedRowCount"] == 3 and summary["databaseMappedCount"] == 0
    assert summary["normalizedCount"] == 1 and summary["unverifiedSymbolCount"] == 1 and summary["unmappedCount"] == 2
    url = f'/api/v1/research/analysis-tasks/{task["id"]}/'
    _, page = owner.request(url + "rows/")
    rows = {row["original_label"]: row for row in page["results"]}
    for label in historical_names:
        assert rows[label]["normalized_symbol"] == "" and rows[label]["mapping_status"] == "unmapped"
        assert "local_target_name_only" in rows[label]["qc_warnings"]
        assert any(item["namespace"] == "platform_entity" for item in rows[label]["external_identifiers"])
    assert rows["TP53"]["mapping_status"] == "unverified"
    assert task["source_releases"]
    other.request(url, expected=404)
    _, exported = owner.request(url + "export/?file_format=csv")
    assert all(label.encode() in exported for label in historical_names)
    report = {"syntheticMeasurements": True, "datasetId": dataset["id"], "taskId": task["id"],
              "algorithmVersion": task["result"]["algorithmVersion"], "selectedRows": 3,
              "nameOnlyCatalogueHits": 2, "databaseMappedSymbols": 0, "unverifiedSymbols": 1,
              "originalLabelsAndProvenancePreserved": True, "crossOwnerDenied": True, "externalCalls": False}
    (VAR / "mapping-consistency-acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
