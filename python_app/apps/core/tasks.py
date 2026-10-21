import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from config.runtime_logs import record_runtime_event

from apps.core.models import AnalysisTask
from apps.core.services.external_analysis import execute_external_analysis
from apps.core.services.case_analysis import CaseAnalysisError, CaseModelUnavailable, run_case_analysis
from apps.core.services.research_assistant import ResearchAssistantError, run_research_assistant
from apps.core.services.visualization import VisualizationInputError, execute_visualization_task


logger = logging.getLogger(__name__)


@shared_task(name="core.complete_evidence")
def run_complete_evidence_task(task_id: int):
    claimed = AnalysisTask.objects.filter(
        pk=task_id, task_type=AnalysisTask.TaskType.NETWORK,
        input_parameters__complete=True, status=AnalysisTask.Status.QUEUED,
    ).update(status=AnalysisTask.Status.RUNNING, progress=5, started_at=timezone.now())
    if not claimed:
        return {"status": "skipped", "taskId": task_id}
    from .services.complete_evidence import CompleteEvidenceInputError, execute_complete_evidence
    from .services.catalog_analysis import CatalogSnapshotChanged
    from .services.network_pharmacology import NetworkPharmacologyInputError
    try:
        execute_complete_evidence(AnalysisTask.objects.select_related("owner").get(pk=task_id))
        return {"status": "succeeded", "taskId": task_id}
    except (CompleteEvidenceInputError, CatalogSnapshotChanged, NetworkPharmacologyInputError) as exc:
        message = str(exc)
        record_runtime_event("complete_evidence.rejected", task_id=task_id, exception=exc)
    except Exception as exc:
        message = "完整本地分析失败，请重试或联系管理员并提供任务编号。"
        record_runtime_event("complete_evidence.failed", task_id=task_id, exception=exc)
        logger.exception("Complete evidence task failed task_id=%s", task_id)
    AnalysisTask.objects.filter(pk=task_id, status=AnalysisTask.Status.RUNNING).update(
        status=AnalysisTask.Status.FAILED, progress=100, error_summary=message, finished_at=timezone.now())
    return {"status": "failed", "taskId": task_id}


@shared_task(name="core.analyze_medical_case")
def run_case_analysis_task(task_id: int) -> dict[str, str | int]:
    claimed = AnalysisTask.objects.filter(
        pk=task_id,
        task_type=AnalysisTask.TaskType.CASE_LINK,
        status=AnalysisTask.Status.QUEUED,
    ).update(status=AnalysisTask.Status.RUNNING, progress=5, started_at=timezone.now())
    if not claimed:
        return {"status": "skipped", "taskId": task_id}
    try:
        task = AnalysisTask.objects.select_related("medical_case").get(pk=task_id)
        result = run_case_analysis(task)
        AnalysisTask.objects.filter(pk=task_id, status=AnalysisTask.Status.RUNNING).update(
            result=result,
            status=AnalysisTask.Status.SUCCEEDED,
            progress=100,
            finished_at=timezone.now(),
        )
        return {"status": AnalysisTask.Status.SUCCEEDED, "taskId": task_id}
    except (CaseAnalysisError, CaseModelUnavailable) as exc:
        record_runtime_event("case.rejected", task_id=task_id, exception=exc)
        public_message = str(exc)
        logger.info("Medical case analysis rejected task_id=%s error_type=%s", task_id, type(exc).__name__)
    except Exception as exc:
        record_runtime_event("case.failed", task_id=task_id, exception=exc)
        public_message = "医案分析失败，请稍后重试或联系平台管理员并提供任务编号。"
        logger.error("Medical case analysis failed task_id=%s error_type=%s", task_id, type(exc).__name__)
    AnalysisTask.objects.filter(pk=task_id, status=AnalysisTask.Status.RUNNING).update(
        status=AnalysisTask.Status.FAILED,
        progress=100,
        error_summary=public_message,
        finished_at=timezone.now(),
    )
    return {"status": AnalysisTask.Status.FAILED, "taskId": task_id}


@shared_task(name="core.research_assistant")
def run_research_assistant_task(task_id: int) -> dict[str, str | int]:
    claimed = AnalysisTask.objects.filter(
        pk=task_id,
        task_type=AnalysisTask.TaskType.RESEARCH_ASSISTANT,
        status=AnalysisTask.Status.QUEUED,
    ).update(status=AnalysisTask.Status.RUNNING, progress=5, started_at=timezone.now())
    if not claimed:
        return {"status": "skipped", "taskId": task_id}
    try:
        task = AnalysisTask.objects.get(pk=task_id)
        result = run_research_assistant(task)
        AnalysisTask.objects.filter(pk=task_id, status=AnalysisTask.Status.RUNNING).update(
            result=result,
            status=AnalysisTask.Status.SUCCEEDED,
            progress=100,
            finished_at=timezone.now(),
        )
        return {"status": AnalysisTask.Status.SUCCEEDED, "taskId": task_id}
    except (ResearchAssistantError, CaseModelUnavailable) as exc:
        record_runtime_event("assistant.rejected", task_id=task_id, exception=exc)
        public_message = str(exc)
        logger.info("Research assistant task rejected task_id=%s error_type=%s", task_id, type(exc).__name__)
    except Exception as exc:
        record_runtime_event("assistant.failed", task_id=task_id, exception=exc)
        public_message = "科研助手分析失败，请稍后重试或联系平台管理员并提供任务编号。"
        logger.error("Research assistant task failed task_id=%s error_type=%s", task_id, type(exc).__name__)
    AnalysisTask.objects.filter(pk=task_id, status=AnalysisTask.Status.RUNNING).update(
        status=AnalysisTask.Status.FAILED,
        progress=100,
        error_summary=public_message,
        finished_at=timezone.now(),
    )
    return {"status": AnalysisTask.Status.FAILED, "taskId": task_id}


@shared_task(name="core.external_analysis")
def run_external_analysis_task(task_id: int) -> dict[str, str | int]:
    claimed = AnalysisTask.objects.filter(
        pk=task_id,
        status=AnalysisTask.Status.QUEUED,
    ).update(status=AnalysisTask.Status.RUNNING, progress=5, started_at=timezone.now())
    if not claimed:
        return {"status": "skipped", "taskId": task_id}
    try:
        task = AnalysisTask.objects.get(pk=task_id)
        return execute_external_analysis(task)
    except Exception as exc:
        record_runtime_event("external.failed", task_id=task_id, exception=exc)
        logger.exception("External analysis worker failed task_id=%s", task_id)
        with transaction.atomic():
            AnalysisTask.objects.filter(pk=task_id, status=AnalysisTask.Status.RUNNING).update(
                status=AnalysisTask.Status.FAILED,
                progress=100,
                error_summary="外部分析失败，请联系管理员并提供任务编号。",
                finished_at=timezone.now(),
            )
        return {"status": AnalysisTask.Status.FAILED, "taskId": task_id}


@shared_task(name="core.render_visualization")
def run_visualization_task(task_id: int) -> dict[str, str | int]:
    claimed = AnalysisTask.objects.filter(
        pk=task_id,
        task_type=AnalysisTask.TaskType.VISUALIZATION,
        status=AnalysisTask.Status.QUEUED,
    ).update(status=AnalysisTask.Status.RUNNING, progress=5, started_at=timezone.now())
    if not claimed:
        return {"status": "skipped", "taskId": task_id}
    try:
        task = AnalysisTask.objects.get(pk=task_id)
        result = execute_visualization_task(task)
        AnalysisTask.objects.filter(pk=task_id).update(
            result=result,
            status=AnalysisTask.Status.SUCCEEDED,
            progress=100,
            finished_at=timezone.now(),
        )
        return {"status": AnalysisTask.Status.SUCCEEDED, "taskId": task_id}
    except VisualizationInputError as exc:
        record_runtime_event("visualization.rejected", task_id=task_id, exception=exc)
        public_message = str(exc)
        logger.info("Visualization input rejected task_id=%s", task_id)
    except Exception as exc:
        record_runtime_event("visualization.failed", task_id=task_id, exception=exc)
        logger.exception("R visualization worker failed task_id=%s", task_id)
        public_message = "R 图表生成失败，请稍后重试或联系平台管理员并提供任务编号。"
    AnalysisTask.objects.filter(pk=task_id).update(
        status=AnalysisTask.Status.FAILED,
        progress=100,
        error_summary=public_message,
        finished_at=timezone.now(),
    )
    return {"status": AnalysisTask.Status.FAILED, "taskId": task_id}
