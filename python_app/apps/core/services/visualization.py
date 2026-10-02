"""Bounded chart-data adapter and private artifact persistence for R output."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from apps.core.models import AnalysisTask, VisualizationArtifact


logger = logging.getLogger(__name__)
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
FORMAT_MIME_TYPES = {
    "svg": "image/svg+xml",
    "pdf": "application/pdf",
    "png": "image/png",
    "html": "text/html; charset=utf-8",
}


class VisualizationInputError(ValueError):
    pass


class VisualizationUnavailable(RuntimeError):
    pass


def build_chart_payload(task: AnalysisTask, chart_key: str) -> dict:
    if task.status != AnalysisTask.Status.SUCCEEDED:
        raise VisualizationInputError("只有已完成的分析任务可以生成图表。")
    result = task.result or {}
    if task.task_type == AnalysisTask.TaskType.NETWORK:
        charts = result.get("charts") or {}
        if chart_key == "overlap":
            title = "中药—疾病靶点交集"
            rows = charts.get("overlap") or []
            data = [{"label": row.get("name"), "value": row.get("value")} for row in rows]
        elif chart_key in {"components", "pathways"}:
            title = "关联成分靶点数" if chart_key == "components" else "关联通路靶点数"
            rows = charts.get(chart_key) or []
            data = [{"label": row.get("name"), "value": row.get("targets")} for row in rows]
        else:
            raise VisualizationInputError("网络药理任务不支持该图表类型。")
    elif task.task_type == AnalysisTask.TaskType.PROTEOMICS:
        summary = result.get("summary") or {}
        if chart_key == "proteomics_summary":
            title = "蛋白组学分析概览"
            keys = ["selectedRowCount", "normalizedCount", "databaseMappedCount", "unmappedCount", "candidateOverlapCount", "pathwayCount"]
            labels = ["筛选行", "标准化", "本地映射", "未映射", "候选交集", "通路"]
            data = [
                {"label": label, "value": summary[key]}
                for key, label in zip(keys, labels)
                if isinstance(summary.get(key), (int, float)) and not isinstance(summary.get(key), bool)
            ]
        elif chart_key == "proteomics_top_nodes":
            title = "本地通路网络连接度"
            data = [
                {"label": row.get("symbol"), "value": row.get("degree")}
                for row in result.get("topNodes", [])[:30]
                if isinstance(row.get("degree"), (int, float)) and not isinstance(row.get("degree"), bool)
            ]
        elif chart_key == "proteomics_go_kegg_enrichment":
            enrichment = result.get("externalGProfiler") or {}
            if enrichment.get("status") != "succeeded":
                raise VisualizationInputError("GO/KEGG 富集没有可绘制的成功结果。")
            title = "GO / KEGG 功能富集"
            source_version = enrichment.get("sourceVersion")
            if isinstance(source_version, str):
                source_version = "".join(character for character in source_version if character.isprintable()).strip()[:120]
            else:
                source_version = ""
            terms = enrichment.get("terms") or []
            allowed_sources = {"GO:BP", "GO:CC", "GO:MF", "KEGG"}
            data = []
            for term in terms:
                if not isinstance(term, dict) or term.get("source") not in allowed_sources:
                    continue
                label = term.get("name")
                gene_ratio = term.get("geneRatio")
                adjusted_p_value = term.get("adjustedPValue")
                intersection_size = term.get("intersectionSize")
                if (
                    not isinstance(label, str)
                    or not label.strip()
                    or not isinstance(gene_ratio, (int, float))
                    or isinstance(gene_ratio, bool)
                    or not 0 <= gene_ratio <= 1
                    or not isinstance(adjusted_p_value, (int, float))
                    or isinstance(adjusted_p_value, bool)
                    or not 0 < adjusted_p_value <= 0.05
                    or not isinstance(intersection_size, int)
                    or isinstance(intersection_size, bool)
                    or intersection_size < 1
                ):
                    continue
                data.append({
                    "label": label.strip()[:140],
                    "source": term["source"],
                    "geneRatio": gene_ratio,
                    "adjustedPValue": adjusted_p_value,
                    "intersectionSize": intersection_size,
                })
                if len(data) == 100:
                    break
            if not data:
                raise VisualizationInputError("GO/KEGG 结果中没有符合绘图要求的富集条目。")
        else:
            raise VisualizationInputError("蛋白组学任务不支持该图表类型。")
    else:
        raise VisualizationInputError("当前任务类型没有已支持的 R 图表。")

    if not 1 <= len(data) <= 100:
        raise VisualizationInputError("该结果没有可供绘图的数据，或数据点超过上限。")
    if chart_key == "proteomics_go_kegg_enrichment":
        payload = {
            "chartType": "enrichment_bubble",
            "title": title,
            "subtitle": f"g:Profiler {source_version or '版本未返回'} · Homo sapiens · FDR ≤ 0.05",
            "xLabel": "GeneRatio",
            "colorLabel": "−log10(FDR)",
            "data": data,
        }
    else:
        if any(not isinstance(item.get("label"), str) or not isinstance(item.get("value"), (int, float)) for item in data):
            raise VisualizationInputError("分析结果中的图表数据格式无效。")
        payload = {"chartType": "bar", "title": title, "yLabel": "数量", "data": data}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    payload["inputSha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def _request_r_visualization(payload: dict) -> dict:
    base_url = settings.R_VIZ_BASE_URL.rstrip("/")
    token = settings.R_VIZ_API_TOKEN
    if not base_url or not token:
        raise VisualizationUnavailable("R 图表服务尚未配置。")
    try:
        request = urllib.request.Request(
            f"{base_url}/render",
            data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(request, timeout=90) as response:
            body = response.read(settings.R_VIZ_MAX_RESPONSE_BYTES + 1)
        if len(body) > settings.R_VIZ_MAX_RESPONSE_BYTES:
            raise VisualizationUnavailable("R 图表服务返回内容超过大小限制。")
        result = json.loads(body)
    except VisualizationUnavailable:
        raise
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("R visualization service request failed: %s", type(exc).__name__)
        raise VisualizationUnavailable("R 图表服务暂不可用，请稍后重试。") from exc
    if not isinstance(result, dict) or result.get("inputSha256") != payload["inputSha256"]:
        raise VisualizationUnavailable("R 图表服务返回结果与当前输入不匹配。")
    return result


def execute_visualization_task(task: AnalysisTask) -> dict:
    if task.task_type != AnalysisTask.TaskType.VISUALIZATION:
        raise VisualizationInputError("任务类型不是 R 图表任务。")
    parent_id = task.input_parameters.get("parentTaskId")
    chart_key = task.input_parameters.get("chartKey")
    parent = AnalysisTask.objects.get(pk=parent_id, owner_id=task.owner_id)
    payload = build_chart_payload(parent, chart_key)
    if payload["inputSha256"] != task.input_parameters.get("inputSha256"):
        raise VisualizationInputError("原分析结果已变化，请重新创建图表任务。")
    result = _request_r_visualization(payload)
    artifacts = result.get("artifacts")
    if result.get("rendererVersion") is None or not isinstance(artifacts, list):
        raise VisualizationUnavailable("R 图表服务返回结果格式无效。")
    artifact_by_format = {item.get("format"): item for item in artifacts if isinstance(item, dict)}
    if set(artifact_by_format) != set(FORMAT_MIME_TYPES):
        raise VisualizationUnavailable("R 图表服务没有返回完整的图表文件集。")

    saved_paths = []
    manifests = []
    try:
        with transaction.atomic():
            task.source_releases.set(parent.source_releases.all())
            for file_format, mime_type in FORMAT_MIME_TYPES.items():
                output = artifact_by_format[file_format]
                if output.get("mimeType") != mime_type or not isinstance(output.get("bytesBase64"), str):
                    raise VisualizationUnavailable("R 图表服务返回文件类型无效。")
                try:
                    content = base64.b64decode(output["bytesBase64"], validate=True)
                except (ValueError, base64.binascii.Error) as exc:
                    raise VisualizationUnavailable("R 图表服务返回的文件编码无效。") from exc
                if not content or len(content) > MAX_ARTIFACT_BYTES:
                    raise VisualizationUnavailable("R 图表服务返回的单个文件超过大小限制。")
                filename = f"task-{parent.pk}-{chart_key}-{payload['inputSha256'][:12]}.{file_format}"
                storage_key = f"analysis-artifacts/{task.owner_id}/{parent.pk}/{task.pk}/{filename}"
                saved_key = default_storage.save(storage_key, ContentFile(content))
                saved_paths.append(saved_key)
                artifact = VisualizationArtifact.objects.create(
                    task=parent,
                    render_task=task,
                    owner=task.owner,
                    chart_key=chart_key,
                    file_format=file_format,
                    filename=filename,
                    mime_type=mime_type,
                    storage_key=saved_key,
                    content_sha256=hashlib.sha256(content).hexdigest(),
                    input_sha256=payload["inputSha256"],
                    byte_size=len(content),
                    renderer_version=str(result["rendererVersion"])[:80],
                )
                manifests.append({
                    "id": artifact.pk,
                    "format": artifact.file_format,
                    "filename": artifact.filename,
                    "mimeType": artifact.mime_type,
                    "sha256": artifact.content_sha256,
                    "byteSize": artifact.byte_size,
                    "rendererVersion": artifact.renderer_version,
                    "downloadUrl": f"/api/v1/research/analysis-artifacts/{artifact.pk}/download/",
                })
    except Exception:
        for storage_key in saved_paths:
            default_storage.delete(storage_key)
        raise

    return {
        "status": AnalysisTask.Status.SUCCEEDED,
        "taskId": task.pk,
        "parentTaskId": parent.pk,
        "chartKey": chart_key,
        "inputSha256": payload["inputSha256"],
        "rendererVersion": result["rendererVersion"],
        "artifacts": manifests,
    }


def queue_visualization(*, parent_task: AnalysisTask, user, chart_key: str) -> tuple[AnalysisTask, bool]:
    payload = build_chart_payload(parent_task, chart_key)
    existing = AnalysisTask.objects.filter(
        owner=parent_task.owner,
        task_type=AnalysisTask.TaskType.VISUALIZATION,
        input_parameters__parentTaskId=parent_task.pk,
        input_parameters__chartKey=chart_key,
        input_parameters__inputSha256=payload["inputSha256"],
        status__in=[AnalysisTask.Status.QUEUED, AnalysisTask.Status.RUNNING, AnalysisTask.Status.SUCCEEDED],
    ).first()
    if existing:
        return existing, False
    with transaction.atomic():
        job = AnalysisTask.objects.create(
            owner=parent_task.owner,
            created_by=user,
            task_type=AnalysisTask.TaskType.VISUALIZATION,
            status=AnalysisTask.Status.QUEUED,
            dataset=parent_task.dataset,
            medical_case=parent_task.medical_case,
            input_parameters={
                "analysisKind": "r_visualization",
                "parentTaskId": parent_task.pk,
                "chartKey": chart_key,
                "inputSha256": payload["inputSha256"],
            },
        )
        job.source_releases.set(parent_task.source_releases.all())
    return job, True
