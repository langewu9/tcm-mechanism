"""Conservative interruption handling: preserve history and never re-enqueue."""
import logging

from django.db import connection, transaction
from django.utils import timezone

from apps.core.models import AnalysisTask, SyncRun


logger = logging.getLogger(__name__)
ANALYSIS_TASK_NAMES = frozenset({
    "core.complete_evidence", "core.analyze_medical_case", "core.research_assistant",
    "core.external_analysis", "core.render_visualization", "proteomics.run_analysis",
})
INTERRUPTED_ANALYSIS = "后台执行进程中断，本次任务未确认完成。请重新发起分析；联系管理员时请提供任务编号。"
INTERRUPTED_SYNC = "后台同步进程中断，请管理员核对目录、来源版本及已产生的变动后重新预览；本次不会自动重试。"


class TaskExecutionStopped(RuntimeError):
    """An old execution must not publish after its record became terminal."""


def lock_running_analysis(task_id):
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Publishing analysis results requires an atomic transaction.")
    task = AnalysisTask.objects.select_for_update().get(pk=task_id)
    if task.status != AnalysisTask.Status.RUNNING:
        raise TaskExecutionStopped("任务已结束或中断，旧执行不能发布结果。")
    return task


def task_record(task_name, args=None, kwargs=None):
    if task_name in ANALYSIS_TASK_NAMES:
        model, key = AnalysisTask, "task_id"
    elif task_name == "sources.sync_run":
        model, key = SyncRun, "run_id"
    else:
        return None
    if not isinstance(args, (tuple, list, type(None))) or not isinstance(kwargs, (dict, type(None))):
        return None
    arguments, keywords = args or (), kwargs or {}
    record_id = arguments[0] if arguments else keywords.get(key)
    if isinstance(record_id, bool) or not isinstance(record_id, int) or record_id < 1:
        return None
    if len(arguments) > 1 or (arguments and key in keywords) or set(keywords) - {key}:
        return None
    return model, record_id


def fail_running_record(model, record_id):
    fields = {
        "status": "failed", "finished_at": timezone.now(),
        "error_summary": INTERRUPTED_ANALYSIS if model is AnalysisTask else INTERRUPTED_SYNC,
    }
    if model is AnalysisTask:
        fields["progress"] = 100
    return bool(model.objects.filter(pk=record_id, status="running").update(**fields))


def mark_interrupted(task_name, args=None, kwargs=None, reason="worker_lost"):
    reference = task_record(task_name, args, kwargs)
    if reference is None:
        return False
    model, record_id = reference
    queryset = model.objects.filter(pk=record_id, status="running")
    if model is AnalysisTask:
        expected_type = {
            "core.complete_evidence": "network", "core.analyze_medical_case": "case_link",
            "core.research_assistant": "research_assistant", "core.external_analysis": "network",
            "core.render_visualization": "visualization", "proteomics.run_analysis": "proteomics",
        }[task_name]
        # A malformed delivery must not fail an unrelated record with the same
        # integer ID. The worker's claim and its failure callback agree on type.
        queryset = queryset.filter(task_type=expected_type)
    # The hard-timeout callback runs BEFORE the pool kills the child. Waiting
    # for a row lock held by that child could block the parent and the kill.
    # If publication is still locked, defer reconciliation to maintenance.
    with transaction.atomic():
        running = queryset.select_for_update(
            skip_locked=connection.features.has_select_for_update_skip_locked).first()
        if running is None:
            return False
        updated = fail_running_record(model, record_id)
    if updated:
        # Never log task arguments, model output, broker credentials or source data.
        logger.warning("Background execution interrupted kind=%s record_id=%s reason=%s",
                       model._meta.model_name, record_id,
                       reason if reason in {"worker_lost", "hard_timeout", "worker_exception", "worker_terminated"} else "interrupted")
    return updated
