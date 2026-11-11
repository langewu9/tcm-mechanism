import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from config.background_tasks import RecoverableTask
from config.runtime_logs import record_runtime_event

from apps.core.models import AnalysisTask
from apps.core.services.task_recovery import TaskExecutionStopped, lock_running_analysis
from apps.proteomics.models import ProteomicsRowResult
from apps.proteomics.integrations import (
    run_opt_in_gprofiler,
    run_opt_in_reactome,
    run_opt_in_string,
)
from apps.proteomics.services import ProteomicsInputError, run_proteomics_analysis


logger = logging.getLogger(__name__)


def _set_progress(task_id: int, progress: int) -> None:
    if not AnalysisTask.objects.filter(pk=task_id, status=AnalysisTask.Status.RUNNING).update(progress=progress):
        raise TaskExecutionStopped("任务已停止，本次执行不再发布结果。")


@shared_task(name="proteomics.run_analysis", base=RecoverableTask)
def run_proteomics_task(task_id: int) -> dict[str, str | int]:
    """Run a queued analysis once and persist every row's QC/mapping outcome."""
    claimed = AnalysisTask.objects.filter(
        pk=task_id,
        task_type=AnalysisTask.TaskType.PROTEOMICS,
        status=AnalysisTask.Status.QUEUED,
    ).update(
        status=AnalysisTask.Status.RUNNING,
        progress=5,
        started_at=timezone.now(),
        error_summary="",
    )
    if not claimed:
        return {"status": "skipped", "taskId": task_id}

    try:
        task = AnalysisTask.objects.select_related("dataset").get(pk=task_id)
        result, row_results, release_ids = run_proteomics_analysis(task)
        _set_progress(task_id, 60)
        if task.input_parameters.get("externalReactome"):
            _set_progress(task_id, 70)
            external_release_ids, external_warnings = run_opt_in_reactome(task, result, row_results)
            release_ids.extend(external_release_ids)
            result.setdefault("warnings", []).extend(external_warnings)
            _set_progress(task_id, 90)
            external = result.get("externalReactome", {})
            if external.get("status") in {"unavailable", "no_mapped_identifiers"}:
                logger.warning(
                    "External proteomics service incomplete task_id=%s stage=%s",
                    task_id,
                    external.get("failureStage", external.get("status")),
                )
        if task.input_parameters.get("externalGProfiler"):
            _set_progress(task_id, 91)
            external_release_ids, external_warnings = run_opt_in_gprofiler(task, result, row_results)
            release_ids.extend(external_release_ids)
            result.setdefault("warnings", []).extend(external_warnings)
            _set_progress(task_id, 94)
            external = result.get("externalGProfiler", {})
            if external.get("status") in {"unavailable", "disabled", "insufficient_identifiers", "input_limit_exceeded"}:
                logger.warning(
                    "g:Profiler proteomics service incomplete task_id=%s stage=%s",
                    task_id,
                    external.get("failureStage", external.get("status")),
                )
        if task.input_parameters.get("externalString"):
            _set_progress(task_id, 95)
            external_release_ids, external_warnings = run_opt_in_string(
                task,
                result,
                row_results,
                task.input_parameters.get("stringRequiredScore", 700),
            )
            release_ids.extend(external_release_ids)
            result.setdefault("warnings", []).extend(external_warnings)
            _set_progress(task_id, 98)
            external = result.get("externalString", {})
            if external.get("status") in {"unavailable", "disabled", "insufficient_identifiers"}:
                logger.warning(
                    "STRING proteomics service incomplete task_id=%s stage=%s",
                    task_id,
                    external.get("failureStage", external.get("status")),
                )
        now = timezone.now()
        with transaction.atomic():
            locked_task = lock_running_analysis(task_id)
            ProteomicsRowResult.objects.filter(task_id=task_id).delete()
            ProteomicsRowResult.objects.bulk_create(row_results, batch_size=1000)
            locked_task.result = result
            locked_task.status = AnalysisTask.Status.SUCCEEDED
            locked_task.progress = 100
            locked_task.finished_at = now
            locked_task.input_parameters = task.input_parameters
            locked_task.save(
                update_fields=[
                    "result", "status", "progress", "finished_at", "input_parameters"
                ]
            )
            locked_task.source_releases.set(release_ids)
        return {"status": AnalysisTask.Status.SUCCEEDED, "taskId": task_id}
    except TaskExecutionStopped:
        return {"status": "skipped", "taskId": task_id}
    except ProteomicsInputError as exc:
        record_runtime_event("proteomics.rejected", task_id=task_id, exception=exc)
        public_message = str(exc)
        logger.info("Proteomics input rejected task_id=%s reason=%s", task_id, public_message)
        status = AnalysisTask.Status.FAILED
    except Exception as exc:
        record_runtime_event("proteomics.failed", task_id=task_id, exception=exc)
        logger.exception("Proteomics analysis failed task_id=%s", task_id)
        public_message = "分析失败，请核对输入后重试，或联系平台管理员并提供任务编号。"
        status = AnalysisTask.Status.FAILED

    updated = AnalysisTask.objects.filter(pk=task_id, status=AnalysisTask.Status.RUNNING).update(
        status=status,
        progress=100,
        error_summary=public_message,
        finished_at=timezone.now(),
    )
    return {"status": status if updated else "skipped", "taskId": task_id}
