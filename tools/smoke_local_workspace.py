"""Exercise real localhost HTTP/Redis/Celery/R with explicitly synthetic data.

Requires the local-preview setup; creates retained synthetic records, not mock tasks.
Run with python_app/.venv/bin/python tools/smoke_local_workspace.py.
"""
import hashlib
import http.cookiejar
import io
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:5173"
VAR = ROOT / "python_app/var"


class LocalClient:
    def __init__(self, account, *, base_url=BASE, csrf_cookie_name="csrftoken"):
        assert base_url in {BASE, "http://127.0.0.1:5174", "http://127.0.0.1:8021"}, "Local acceptance endpoints only."
        self.base = base_url
        self.csrf_cookie_name = csrf_cookie_name
        self.cookies = http.cookiejar.CookieJar()
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.request("/api/v1/auth/csrf/")
        status, session = self.request("/api/v1/auth/session/", method="POST", data={"username": account["username"], "password": account["password"]})
        assert status == 200 and session["authenticated"]

    def request(self, path, *, method="GET", data=None, raw=None, content_type="application/json", expected=200):
        assert path.startswith("/") and not path.startswith("//"), "Only same-origin localhost requests are permitted."
        token = next((item.value for item in self.cookies if item.name == self.csrf_cookie_name), "")
        body = json.dumps(data).encode() if data is not None else raw
        request = urllib.request.Request(self.base + path, data=body, method=method, headers={"Content-Type": content_type, "Origin": self.base, "Referer": self.base + "/", "X-CSRFToken": token})
        try:
            response = self.http.open(request, timeout=25)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read()
            value = json.loads(body) if body and response.headers.get_content_type() == "application/json" else body
            assert response.status == expected, (path, response.status, value)
            return response.status, value


def wait_task(client, task_id):
    for _ in range(120):
        _, task = client.request(f"/api/v1/research/analysis-tasks/{task_id}/")
        if task["status"] == "succeeded":
            return task
        assert task["status"] != "failed", task.get("error_summary")
        time.sleep(0.5)
    raise AssertionError("Local task did not finish within 60 seconds.")


def main():
    import sys
    sys.path.insert(0, str(ROOT / "python_app"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()
    from django.conf import settings
    assert settings.DEBUG and settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3", "This smoke test is for the isolated local SQLite preview only."
    accounts = json.loads((VAR / "local-acceptance-users.json").read_text())
    owner, other = LocalClient(accounts["a"]), LocalClient(accounts["b"])
    administrator = LocalClient(json.loads((VAR / "local-preview-login.json").read_text()))
    content = b"Gene,log2FC,PValue,FDR\nTP53,2,0.001,0.01\nEGFR,-1.7,0.002,0.02\nGAPDH,0.2,0.3,0.5\nSYNTHETIC_BAD,invalid,0.1,0.2\n"
    boundary = "LocalSyntheticAcceptanceBoundary"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n本地合成验收样例（非科研数据）\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="description"\r\n\r\nSYNTHETIC: local queue, retention and R acceptance only.\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic-acceptance.csv"\r\nContent-Type: text/csv\r\n\r\n'
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    _, dataset = owner.request("/api/v1/research/datasets/", method="POST", raw=body, content_type=f"multipart/form-data; boundary={boundary}", expected=201)
    dataset_url = f'/api/v1/research/datasets/{dataset["id"]}/'
    assert dataset["content_sha256"] == hashlib.sha256(content).hexdigest()
    assert dataset["owner_id"] == accounts["a"]["id"]
    _, queued = owner.request(dataset_url + "analyze/", method="POST", data={
        "name": "本地合成验收分析（非科研结论）",
        "mapping": {"geneColumn": "Gene", "log2FcColumn": "log2FC", "pValueColumn": "PValue", "fdrColumn": "FDR"},
        "thresholds": {"log2FcMin": 1, "fdrMax": 0.05, "pValueMax": 0.05},
        "externalReactome": False, "externalString": False, "externalGProfiler": False,
    }, expected=202)
    task = wait_task(owner, queued["id"])
    assert task["result"]["qc"]["selectedRowCount"] == 2, task["result"]["qc"]
    task_url = f'/api/v1/research/analysis-tasks/{task["id"]}/'
    _, csv_bytes = owner.request(task_url + "export/?file_format=csv")
    _, xlsx_bytes = owner.request(task_url + "export/?file_format=xlsx")
    _, pdf_bytes = owner.request(task_url + "export/?file_format=pdf")
    assert b"TP53" in csv_bytes and xlsx_bytes.startswith(b"PK") and pdf_bytes.startswith(b"%PDF")
    from openpyxl import load_workbook
    workbook = load_workbook(io.BytesIO(xlsx_bytes), read_only=True)
    assert sum(1 for _ in workbook.active.iter_rows(values_only=True)) >= 5
    workbook.close()
    artifact_paths = []
    for key in ["proteomics_summary", "proteomics_volcano"]:
        _, job = owner.request(task_url + "visualizations/", method="POST", data={"chartKey": key}, expected=202)
        rendered = wait_task(owner, job["id"])
        assert rendered["parent_task"] == task["id"]
        artifacts = rendered["result"]["artifacts"]
        assert {item["format"] for item in artifacts} == {"svg", "png", "pdf", "html"}
        for artifact in artifacts:
            _, downloaded = owner.request(artifact["downloadUrl"])
            if isinstance(downloaded, str):
                downloaded = downloaded.encode()
            assert hashlib.sha256(downloaded).hexdigest() == artifact["sha256"]
            other.request(artifact["downloadUrl"], expected=404)
            artifact_paths.append(artifact["downloadUrl"])
    owner.request(dataset_url, method="DELETE", expected=204)
    _, original = owner.request(dataset_url + "download/")
    assert original == content
    _, archived = owner.request("/api/v1/research/datasets/?archived=true")
    assert any(item["id"] == dataset["id"] for item in archived["results"])
    for path in [dataset_url, dataset_url + "download/", dataset_url + "audit/", task_url, task_url + "rows/", task_url + "export/?file_format=csv"]:
        other.request(path, expected=404)
    other.request(dataset_url + "restore/", method="POST", expected=404)
    _, restored = administrator.request(dataset_url + "restore/", method="POST")
    assert restored["owner_id"] == accounts["a"]["id"] and restored["archived_at"] is None
    _, audit = owner.request(dataset_url + "audit/")
    assert [item["action"] for item in reversed(audit["results"])] == ["created", "archived", "restored"]
    _, case = owner.request("/api/v1/research/cases/", method="POST", data={"title": "本地合成医案验收（虚构）", "deidentified_text": "虚构测试文本，仅验证资料保留与权限。", "source_reference": "SYNTHETIC_ACCEPTANCE_ONLY"}, expected=201)
    case_url = f'/api/v1/research/cases/{case["id"]}/'
    owner.request(case_url, method="DELETE", expected=204)
    other.request(case_url + "audit/", expected=404)
    other.request(case_url + "restore/", method="POST", expected=404)
    _, case_restored = administrator.request(case_url + "restore/", method="POST")
    assert case_restored["deidentified_text"] == case["deidentified_text"]
    report = {"synthetic": True, "datasetId": dataset["id"], "caseId": case["id"], "taskId": task["id"], "selectedRows": 2, "rArtifacts": len(artifact_paths), "exports": ["csv", "xlsx", "pdf"], "checks": ["actual HTTP upload", "real Redis/Celery task", "real R summary and volcano", "private artifact hashes", "cross-owner access denied", "archive/restore preserves original", "administrator restore preserves owner"], "externalModelOrDatabaseCalls": False}
    (VAR / "local-acceptance-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
