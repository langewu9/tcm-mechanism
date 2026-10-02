import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.core.models import AnalysisTask
from apps.core.services.external_analysis import execute_external_analysis


logger = logging.getLogger(__name__)


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
    except Exception:
        logger.exception("External analysis worker failed task_id=%s", task_id)
        with transaction.atomic():
            AnalysisTask.objects.filter(pk=task_id, status=AnalysisTask.Status.RUNNING).update(
                status=AnalysisTask.Status.FAILED,
                progress=100,
                error_summary="外部分析失败，请联系管理员并提供任务编号。",
                finished_at=timezone.now(),
            )
        return {"status": AnalysisTask.Status.FAILED, "taskId": task_id}
