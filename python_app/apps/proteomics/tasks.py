import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.core.models import AnalysisTask
from apps.proteomics.models import ProteomicsRowResult
from apps.proteomics.services import ProteomicsInputError, run_proteomics_analysis


logger = logging.getLogger(__name__)


@shared_task(name="proteomics.run_analysis")
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
        now = timezone.now()
        with transaction.atomic():
            locked_task = AnalysisTask.objects.select_for_update().get(pk=task_id)
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
    except ProteomicsInputError as exc:
        public_message = str(exc)
        logger.info("Proteomics input rejected task_id=%s reason=%s", task_id, public_message)
        status = AnalysisTask.Status.FAILED
    except Exception:
        logger.exception("Proteomics analysis failed task_id=%s", task_id)
        public_message = "分析失败，请核对输入后重试，或联系平台管理员并提供任务编号。"
        status = AnalysisTask.Status.FAILED

    AnalysisTask.objects.filter(pk=task_id).update(
        status=status,
        progress=100,
        error_summary=public_message,
        finished_at=timezone.now(),
    )
    return {"status": status, "taskId": task_id}
