"""Explicitly requested external Reactome enrichment and STRING PPI queries."""

from __future__ import annotations

import json
import hashlib
from copy import deepcopy
import re
import time
from collections import deque
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from config.runtime_logs import record_runtime_event

from apps.core.exceptions import TaskQueueUnavailable
from apps.core.models import AnalysisTask, DataSource, MedicalCase, ResearchDataset, SourceRelease
from apps.proteomics.external_reactome import (
    ExternalEnrichmentError,
    analyze_reactome_human_pathways,
    resolve_human_identifiers,
)


STRING_VERSION_URL = "https://string-db.org/api/json/version"
STRING_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")
MAX_STRING_IDENTIFIERS = 200
MAX_STRING_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_STRING_INTERACTIONS = MAX_STRING_IDENTIFIERS * (MAX_STRING_IDENTIFIERS - 1) // 2
MAX_STRING_NODES = MAX_STRING_IDENTIFIERS * 2


class ExternalAnalysisError(RuntimeError):
    """Safe external service error without response bodies or user identifiers."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def _open_string(request: Request, timeout: int):
    """Refuse redirects so submitted identifiers cannot be forwarded elsewhere."""
    return build_opener(_NoRedirect).open(request, timeout=timeout)


def _deduplicate_labels(labels: list[str]) -> list[str]:
    return list(dict.fromkeys(label.strip() for label in labels if label.strip()))


def _snapshot_sha256(value) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _network_candidate_labels(parent: AnalysisTask, user) -> list[str]:
    parameters = parent.input_parameters
    result = parent.result
    if (
        parent.owner_id != user.pk
        or parent.task_type != AnalysisTask.TaskType.NETWORK
        or parent.status != AnalysisTask.Status.SUCCEEDED
        or not isinstance(parameters, dict)
        or parameters.get("analysisKind")
        or not isinstance(parameters.get("herbs"), list)
        or not isinstance(parameters.get("disease"), str)
        or not isinstance(result, dict)
        or not isinstance(result.get("summary"), dict)
        or not isinstance(result.get("targets"), list)
        or not isinstance(result.get("network"), dict)
    ):
        raise ValueError("只能关联当前账号下已成功完成的本地网络药理查询。")
    if (
        parent.medical_case_id
        and not MedicalCase.objects.filter(pk=parent.medical_case_id, owner=user).exists()
    ) or (
        parent.dataset_id
        and not ResearchDataset.objects.filter(pk=parent.dataset_id, owner=user).exists()
    ):
        raise ValueError("来源任务的医案或数据集归属不一致，不能创建关联分析。")
    rows = result["targets"]
    limits = result.get("limits") or {}
    candidate_count = result["summary"].get("candidateTargetCount", len(rows))
    if (
        not isinstance(limits, dict)
        or limits.get("targetsTruncated")
        or not isinstance(candidate_count, int)
        or isinstance(candidate_count, bool)
        or candidate_count != len(rows)
    ):
        raise ValueError("来源任务的候选靶点结果不完整；请使用完整候选集创建分析。")
    if any(
        not isinstance(row, dict)
        or not isinstance(row.get("target"), str)
        or not row["target"].strip()
        or len(row["target"].strip()) > 120
        for row in rows
    ):
        raise ValueError("来源任务的候选靶点标识格式无效。")
    return _deduplicate_labels([row["target"] for row in rows])


def _create_external_task(*, user, labels, source_task, parameters, max_identifiers) -> AnalysisTask:
    # Lock the parent while freezing the input and provenance. Historical tasks
    # remain unassociated; a new standalone request never infers a parent.
    with transaction.atomic():
        parent = None
        releases = []
        if source_task is not None:
            try:
                parent = AnalysisTask.objects.select_for_update().get(pk=source_task.pk, owner=user)
            except AnalysisTask.DoesNotExist as exc:
                raise ValueError("没有找到当前账号下的来源任务。") from exc
            unique_labels = _network_candidate_labels(parent, user)
            if labels is not None and set(_deduplicate_labels(labels)) != set(unique_labels):
                raise ValueError("提交的靶点必须与来源任务保存的完整候选集一致。")
            releases = list(parent.source_releases.select_related("source").order_by("pk"))
            parent_parameters = parent.input_parameters
            parameters["sourceTaskId"] = parent.pk
            parameters["parentProvenance"] = {
                "taskId": parent.pk,
                "ownerId": parent.owner_id,
                "datasetId": parent.dataset_id,
                "medicalCaseId": parent.medical_case_id,
                "inputParameters": deepcopy({
                    key: parent_parameters[key]
                    for key in (
                        "herbs", "requestedNames", "formulas", "disease", "rowLimit",
                        "statisticsVersion", "rawEvidenceVersion", "sourceCaseId",
                        "sourceCandidateId", "caseContentSha256", "sourceFormulaStableId",
                    ) if key in parent_parameters
                }),
                "inputParametersSha256": _snapshot_sha256(parent_parameters),
                "resultSha256": _snapshot_sha256(parent.result),
                "rawTargetsSha256": _snapshot_sha256(unique_labels),
                "candidateCount": len(parent.result["targets"]),
                "uniqueTargetCount": len(unique_labels),
                "finishedAt": parent.finished_at.isoformat() if parent.finished_at else None,
                "sourceReleases": [{
                    "id": release.pk,
                    "sourceId": release.source_id,
                    "sourceSlug": release.source.slug,
                    "version": release.version,
                    "checksumSha256": release.checksum_sha256,
                } for release in releases],
            }
        else:
            unique_labels = _deduplicate_labels(labels or [])
        if len(unique_labels) < 2:
            raise ValueError("至少需要 2 个不同的基因/蛋白标识。")
        if len(unique_labels) > max_identifiers:
            raise ValueError(f"本次外部分析最多接收 {max_identifiers} 个标识；不会自动截断来源候选集。")
        parameters["rawTargets"] = unique_labels
        task = AnalysisTask.objects.create(
            owner=user,
            created_by=user,
            task_type=AnalysisTask.TaskType.NETWORK,
            status=AnalysisTask.Status.QUEUED,
            parent_task=parent,
            dataset_id=parent.dataset_id if parent else None,
            medical_case_id=parent.medical_case_id if parent else None,
            input_parameters=parameters,
        )
        if releases:
            task.source_releases.set(releases)
    return task


def enqueue_reactome_enrichment(
    user, labels: list[str] | None = None, *, source_task: AnalysisTask | None = None
) -> AnalysisTask:
    task = _create_external_task(
        user=user, labels=labels, source_task=source_task, max_identifiers=500,
        parameters={
            "analysisKind": "reactome_enrichment",
            "maxExternalIdentifiers": 500,
            "consentRecorded": True,
        },
    )
    return _enqueue(task)


def enqueue_string_network(
    user, labels: list[str] | None, required_score: int, *, source_task: AnalysisTask | None = None
) -> AnalysisTask:
    if not 0 <= required_score <= 1000:
        raise ValueError("STRING 置信度阈值必须介于 0 到 1000。")
    task = _create_external_task(
        user=user, labels=labels, source_task=source_task, max_identifiers=MAX_STRING_IDENTIFIERS,
        parameters={
            "analysisKind": "string_ppi",
            "organism": "Homo sapiens",
            "taxonId": 9606,
            "requiredScore": required_score,
            "networkType": "physical",
            "stringVersionOverride": settings.STRING_DB_VERSION or None,
            "consentRecorded": True,
        },
    )
    return _enqueue(task)


def _enqueue(task: AnalysisTask) -> AnalysisTask:
    try:
        from apps.core.tasks import run_external_analysis_task

        run_external_analysis_task.apply_async(args=[task.pk])
    except Exception as exc:
        record_runtime_event("task.queue_unavailable", task_id=task.pk, exception=exc)
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


def _request_string_network(
    labels: list[str], required_score: int, api_base: str, discovered: bool
) -> list[dict]:
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
        f"{api_base}/json/network",
        data=params,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "TCM-Mechanism-Research/1.0",
        },
        method="POST",
    )
    try:
        if discovered:
            # STRING requests at least one second between API calls.
            time.sleep(1)
        with _open_string(request, timeout=30) as response:
            raw = response.read(MAX_STRING_RESPONSE_BYTES + 1)
        if len(raw) > MAX_STRING_RESPONSE_BYTES:
            raise ExternalAnalysisError("STRING 互作响应超过安全大小限制。")
        payload = json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        raise ExternalAnalysisError(f"STRING 返回 HTTP {exc.code}。") from None
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ExternalAnalysisError("STRING 服务暂时无法连接或返回了无效数据。") from None
    if not isinstance(payload, list):
        raise ExternalAnalysisError("STRING 返回的数据格式无效。")
    if len(payload) > MAX_STRING_INTERACTIONS:
        raise ExternalAnalysisError("STRING 返回的互作数量超过本次输入上限。")
    return [item for item in payload if isinstance(item, dict)]


def calculate_unweighted_betweenness(node_ids: list[str], edges: list[dict]) -> dict[str, dict[str, float | int]]:
    """Calculate neighbor degree and normalized Brandes betweenness on an undirected PPI graph."""
    adjacency = {node_id: set() for node_id in node_ids}
    for edge in edges:
        left = edge.get("source")
        right = edge.get("target")
        if left in adjacency and right in adjacency and left != right:
            adjacency[left].add(right)
            adjacency[right].add(left)

    node_count = len(adjacency)
    raw_betweenness = dict.fromkeys(adjacency, 0.0)
    for source in adjacency:
        predecessors = {node_id: [] for node_id in adjacency}
        shortest_path_count = dict.fromkeys(adjacency, 0)
        shortest_path_count[source] = 1
        distance = dict.fromkeys(adjacency, -1)
        distance[source] = 0
        queue = deque([source])
        stack = []

        while queue:
            node = queue.popleft()
            stack.append(node)
            for neighbor in sorted(adjacency[node]):
                if distance[neighbor] < 0:
                    distance[neighbor] = distance[node] + 1
                    queue.append(neighbor)
                if distance[neighbor] == distance[node] + 1:
                    shortest_path_count[neighbor] += shortest_path_count[node]
                    predecessors[neighbor].append(node)

        dependency = dict.fromkeys(adjacency, 0.0)
        while stack:
            node = stack.pop()
            for predecessor in predecessors[node]:
                dependency[predecessor] += (
                    shortest_path_count[predecessor]
                    / shortest_path_count[node]
                    * (1.0 + dependency[node])
                )
            if node != source:
                raw_betweenness[node] += dependency[node]

    normalizer = (node_count - 1) * (node_count - 2)
    normalized = {
        node_id: round(value / normalizer, 6) if normalizer > 0 else 0.0
        for node_id, value in raw_betweenness.items()
    }
    return {
        node_id: {"degree": len(adjacency[node_id]), "betweenness": normalized[node_id]}
        for node_id in adjacency
    }


def _string_api_release() -> tuple[str, str, bool]:
    """Resolve an immutable versioned STRING endpoint or use an explicit pin."""
    configured_version = str(settings.STRING_DB_VERSION or "").strip()
    discovered = not configured_version
    if configured_version:
        version = configured_version
    else:
        request = Request(
            STRING_VERSION_URL,
            headers={"Accept": "application/json", "User-Agent": "TCM-Mechanism-Research/1.0"},
        )
        try:
            with _open_string(request, timeout=15) as response:
                raw = response.read(64 * 1024 + 1)
            if len(raw) > 64 * 1024:
                raise ExternalAnalysisError("STRING 版本响应超过安全大小限制。")
            payload = json.loads(raw.decode("utf-8"))
        except ExternalAnalysisError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise ExternalAnalysisError("无法获取 STRING 数据库版本，请稍后重试。") from None
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise ExternalAnalysisError("STRING 版本响应格式无效。")
        version = str(payload[0].get("string_version") or "").strip()
        stable_address = str(payload[0].get("stable_address") or "").strip()
        parsed_address = urlsplit(stable_address)
        if parsed_address.scheme != "https" or parsed_address.hostname not in {"string-db.org", "www.string-db.org"}:
            raise ExternalAnalysisError("STRING 版本响应提供了不受信任的地址。")

    if len(version) > 20 or not STRING_VERSION_RE.fullmatch(version):
        raise ExternalAnalysisError("STRING 数据库版本格式无效，拒绝使用非固定地址。")
    version_host = "version-" + version.replace(".", "-") + ".string-db.org"
    api_base = f"https://{version_host}/api"
    return version, api_base, discovered


def _run_string(labels: list[str], required_score: int) -> tuple[dict, str | None]:
    version, api_base, discovered = _string_api_release()
    records = _request_string_network(labels, required_score, api_base, discovered)
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
        if len(nodes) > MAX_STRING_NODES:
            raise ExternalAnalysisError("STRING 返回的节点数量超过本次输入上限。")
        edges.append({
            "source": left_id,
            "target": right_id,
            "score": score,
            "scoreOutOf1000": round(score * 1000),
        })
    centrality = calculate_unweighted_betweenness(list(nodes), edges)
    for node in nodes.values():
        node.update(centrality[node["id"]])
    return {
        "analysisKind": "string_ppi",
        "organism": "Homo sapiens",
        "taxonId": 9606,
        "requiredScore": required_score,
        "networkType": "physical",
        "source": "STRING",
        "sourceVersion": version,
        "sourceVersionKnown": True,
        "sourceEndpoint": api_base,
        "inputCount": len(labels),
        "interactionCount": len(edges),
        "nodes": list(nodes.values()),
        "edges": edges,
        "centralityMethod": "degree=unique_neighbors; betweenness=normalized_unweighted_brandes",
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


def _attach_source_release(task: AnalysisTask, slug: str, version: str | None, metadata: dict | None = None) -> None:
    if version:
        if slug == "string":
            source, _ = DataSource.objects.get_or_create(
                slug="string",
                defaults={
                    "name": "STRING",
                    "description": "按使用者明确请求提供的蛋白互作与功能网络分析服务。",
                    "access_mode": DataSource.AccessMode.API,
                    "documentation_url": "https://string-db.org/help/api/",
                    "license_note": "请在发布平台前审查 STRING 的引用与使用条款。",
                    "enabled": True,
                },
            )
            release, _ = SourceRelease.objects.get_or_create(
                source=source,
                version=version,
                defaults={"metadata": metadata or {}},
            )
            task.source_releases.add(release)
        else:
            release = SourceRelease.objects.filter(source__slug=slug, version=version).first()
            if release:
                task.source_releases.add(release)


def execute_external_analysis(task: AnalysisTask) -> dict:
    params = task.input_parameters or {}
    kind = params.get("analysisKind")
    labels = params.get("rawTargets", [])
    try:
        if task.parent_task_id is not None:
            snapshot = params.get("parentProvenance")
            if (
                not isinstance(snapshot, dict)
                or snapshot.get("taskId") != task.parent_task_id
                or params.get("sourceTaskId") != task.parent_task_id
                or snapshot.get("ownerId") != task.owner_id
                or task.parent_task.owner_id != task.owner_id
                or snapshot.get("datasetId") != task.dataset_id
                or snapshot.get("medicalCaseId") != task.medical_case_id
                or snapshot.get("rawTargetsSha256") != _snapshot_sha256(labels)
            ):
                raise ExternalAnalysisError("关联任务的输入或溯源信息不一致，已停止外部提交。")
        if kind == "reactome_enrichment":
            result, version = _run_reactome(labels)
            _attach_source_release(task, "reactome", version)
        elif kind == "string_ppi":
            if DataSource.objects.filter(slug="string", enabled=False).exists():
                raise ExternalAnalysisError("管理员已停用 STRING 外部分析服务。")
            result, version = _run_string(labels, int(params["requiredScore"]))
            _attach_source_release(
                task,
                "string",
                version,
                {
                    "endpoint": result.get("sourceEndpoint"),
                    "retrievedAt": result.get("retrievedAt"),
                    "networkType": "physical",
                },
            )
        else:
            raise ExternalAnalysisError("不支持的外部分析类型。")
        if task.parent_task_id is not None:
            result["inputProvenance"] = {
                "sourceTaskId": task.parent_task_id,
                "parentProvenance": deepcopy(params["parentProvenance"]),
            }
        task.status = AnalysisTask.Status.SUCCEEDED
        task.progress = 100
        task.result = result
        task.finished_at = timezone.now()
        task.save(update_fields=["status", "progress", "result", "finished_at"])
        return {"status": task.status, "taskId": task.pk}
    except ExternalAnalysisError as exc:
        record_runtime_event("external.rejected", task_id=task.pk, exception=exc)
        task.status = AnalysisTask.Status.FAILED
        task.progress = 100
        task.error_summary = str(exc)
        task.finished_at = timezone.now()
        task.save(update_fields=["status", "progress", "error_summary", "finished_at"])
        return {"status": task.status, "taskId": task.pk}
    except Exception as exc:
        record_runtime_event("external.failed", task_id=task.pk, exception=exc)
        task.status = AnalysisTask.Status.FAILED
        task.progress = 100
        task.error_summary = "外部分析失败，请联系管理员并提供任务编号。"
        task.finished_at = timezone.now()
        task.save(update_fields=["status", "progress", "error_summary", "finished_at"])
        return {"status": task.status, "taskId": task.pk}
