"""Explicitly requested external Reactome enrichment and STRING PPI queries."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

from apps.core.exceptions import TaskQueueUnavailable
from apps.core.models import AnalysisTask, SourceRelease
from apps.proteomics.external_reactome import (
    ExternalEnrichmentError,
    analyze_reactome_human_pathways,
    resolve_human_identifiers,
)


STRING_NETWORK_URL = "https://string-db.org/api/json/network"
MAX_STRING_IDENTIFIERS = 200


class ExternalAnalysisError(RuntimeError):
    """Safe external service error without response bodies or user identifiers."""


def _deduplicate_labels(labels: list[str]) -> list[str]:
    return list(dict.fromkeys(label.strip() for label in labels if label.strip()))


def enqueue_reactome_enrichment(user, labels: list[str]) -> AnalysisTask:
    unique_labels = _deduplicate_labels(labels)
    if len(unique_labels) < 2:
        raise ValueError("至少需要 2 个基因/蛋白标识。")
    task = AnalysisTask.objects.create(
        owner=user,
        created_by=user,
        task_type=AnalysisTask.TaskType.NETWORK,
        status=AnalysisTask.Status.QUEUED,
        input_parameters={
            "analysisKind": "reactome_enrichment",
            "rawTargets": unique_labels[:500],
            "maxExternalIdentifiers": 500,
            "consentRecorded": True,
        },
    )
    return _enqueue(task)


def enqueue_string_network(user, labels: list[str], required_score: int) -> AnalysisTask:
    unique_labels = _deduplicate_labels(labels)
    if len(unique_labels) < 2:
        raise ValueError("至少需要 2 个基因/蛋白标识。")
    if len(unique_labels) > MAX_STRING_IDENTIFIERS:
        raise ValueError(f"STRING 单次最多接收 {MAX_STRING_IDENTIFIERS} 个标识。")
    task = AnalysisTask.objects.create(
        owner=user,
        created_by=user,
        task_type=AnalysisTask.TaskType.NETWORK,
        status=AnalysisTask.Status.QUEUED,
        input_parameters={
            "analysisKind": "string_ppi",
            "rawTargets": unique_labels,
            "organism": "Homo sapiens",
            "taxonId": 9606,
            "requiredScore": required_score,
            "networkType": "physical",
            "sourceVersion": settings.STRING_DB_VERSION or None,
            "consentRecorded": True,
        },
    )
    return _enqueue(task)


def _enqueue(task: AnalysisTask) -> AnalysisTask:
    try:
        from apps.core.tasks import run_external_analysis_task

        run_external_analysis_task.apply_async(args=[task.pk])
    except Exception as exc:
        task.status = AnalysisTask.Status.FAILED
        task.progress = 100
        task.error_summary = "分析任务队列暂不可用，请稍后重试。"
        task.finished_at = timezone.now()
        task.save(update_fields=["status", "progress", "error_summary", "finished_at"])
        raise TaskQueueUnavailable() from exc
    return task


def _run_reactome(labels: list[str]) -> tuple[dict, str | None]:
    try:
        resolution = resolve_human_identifiers(labels[:500])
        symbols = [item["symbol"] for item in resolution["mappings"]]
        enrichment = analyze_reactome_human_pathways(symbols)
    except ExternalEnrichmentError as exc:
        raise ExternalAnalysisError("Reactome 或 MyGene.info 暂时无法完成查询。") from exc
    result = {
        "analysisKind": "reactome_enrichment",
        "organism": "Homo sapiens",
        "inputCount": len(labels),
        "mappedCount": len(symbols),
        "mappings": resolution["mappings"],
        "ambiguous": resolution["ambiguous"],
        "unmapped": resolution["unmapped"],
        "rejected": resolution["rejected"],
        "truncatedCount": resolution["truncatedCount"],
        "source": "Reactome Analysis Service",
        "sourceVersion": enrichment["sourceVersion"],
        "sourceToken": enrichment["token"],
        "identifiersNotFound": enrichment["identifiersNotFound"],
        "pathways": enrichment["pathways"],
        "retrievedAt": timezone.now().isoformat(),
    }
    return result, enrichment["sourceVersion"]


def _request_string_network(labels: list[str], required_score: int) -> list[dict]:
    params = urlencode({
        "identifiers": "\r".join(labels),
        "species": "9606",
        "required_score": str(required_score),
        "network_type": "physical",
        "network_flavor": "confidence",
        "add_nodes": "0",
        "caller_identity": "tcm_mechanism_platform",
    }).encode("utf-8")
    request = Request(
        STRING_NETWORK_URL,
        data=params,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "TCM-Mechanism-Research/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ExternalAnalysisError(f"STRING 返回 HTTP {exc.code}。") from None
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ExternalAnalysisError("STRING 服务暂时无法连接或返回了无效数据。") from None
    if not isinstance(payload, list):
        raise ExternalAnalysisError("STRING 返回的数据格式无效。")
    return [item for item in payload if isinstance(item, dict)]


def _run_string(labels: list[str], required_score: int) -> tuple[dict, str | None]:
    records = _request_string_network(labels, required_score)
    nodes = {}
    edges = []
    for record in records:
        left_id = str(record.get("stringId_A") or "").strip()
        right_id = str(record.get("stringId_B") or "").strip()
        left = str(record.get("preferredName_A") or left_id).strip()
        right = str(record.get("preferredName_B") or right_id).strip()
        try:
            score = float(record.get("score", 0))
        except (TypeError, ValueError):
            continue
        if not left_id or not right_id or not 0 <= score <= 1:
            continue
        nodes[left_id] = {"id": left_id, "label": left, "type": "protein"}
        nodes[right_id] = {"id": right_id, "label": right, "type": "protein"}
        edges.append({
            "source": left_id,
            "target": right_id,
            "score": score,
            "scoreOutOf1000": round(score * 1000),
        })
    version = settings.STRING_DB_VERSION or None
    return {
        "analysisKind": "string_ppi",
        "organism": "Homo sapiens",
        "taxonId": 9606,
        "requiredScore": required_score,
        "networkType": "physical",
        "source": "STRING",
        "sourceVersion": version,
        "sourceVersionKnown": bool(version),
        "inputCount": len(labels),
        "interactionCount": len(edges),
        "nodes": list(nodes.values()),
        "edges": edges,
        "retrievedAt": timezone.now().isoformat(),
        "note": "该网络来自 STRING 物理互作评分；数据库关联不单独证明因果关系。",
    }, version


def query_string_physical_network(labels: list[str], required_score: int) -> tuple[dict, str | None]:
    """Query STRING for a bounded, explicitly consented human identifier set."""
    unique_labels = _deduplicate_labels(labels)
    if len(unique_labels) < 2:
        raise ValueError("STRING 查询至少需要 2 个不同的基因/蛋白标识。")
    if len(unique_labels) > MAX_STRING_IDENTIFIERS:
        raise ValueError(f"STRING 单次最多接收 {MAX_STRING_IDENTIFIERS} 个标识。")
    if not 0 <= required_score <= 1000:
        raise ValueError("STRING 置信度阈值必须介于 0 到 1000。")
    return _run_string(unique_labels, required_score)


def _attach_source_release(task: AnalysisTask, slug: str, version: str | None) -> None:
    if version:
        release = SourceRelease.objects.filter(source__slug=slug, version=version).first()
        if release:
            task.source_releases.add(release)


def execute_external_analysis(task: AnalysisTask) -> dict:
    params = task.input_parameters or {}
    kind = params.get("analysisKind")
    labels = params.get("rawTargets", [])
    try:
        if kind == "reactome_enrichment":
            result, version = _run_reactome(labels)
            _attach_source_release(task, "reactome", version)
        elif kind == "string_ppi":
            result, version = _run_string(labels, int(params["requiredScore"]))
            _attach_source_release(task, "string", version)
        else:
            raise ExternalAnalysisError("不支持的外部分析类型。")
        task.status = AnalysisTask.Status.SUCCEEDED
        task.progress = 100
        task.result = result
        task.finished_at = timezone.now()
        task.save(update_fields=["status", "progress", "result", "finished_at"])
        return {"status": task.status, "taskId": task.pk}
    except ExternalAnalysisError as exc:
        task.status = AnalysisTask.Status.FAILED
        task.progress = 100
        task.error_summary = str(exc)
        task.finished_at = timezone.now()
        task.save(update_fields=["status", "progress", "error_summary", "finished_at"])
        return {"status": task.status, "taskId": task.pk}
    except Exception:
        task.status = AnalysisTask.Status.FAILED
        task.progress = 100
        task.error_summary = "外部分析失败，请联系管理员并提供任务编号。"
        task.finished_at = timezone.now()
        task.save(update_fields=["status", "progress", "error_summary", "finished_at"])
        return {"status": task.status, "taskId": task.pk}
