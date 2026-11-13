import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from config.background_tasks import RecoverableTask
from apps.core.models import DataSource, SyncRun
from apps.core.services.task_recovery import TaskExecutionStopped
from apps.sources.services import (
    PUBCHEM_CONNECTOR,
    REACTOME_CONNECTOR,
    STRING_CONNECTOR,
    UNIPROT_CONNECTOR,
    apply_string_sync,
    apply_pubchem_sync,
    apply_reactome_sync,
    apply_uniprot_sync,
    preview_reactome_sync,
    preview_uniprot_sync,
    preview_pubchem_sync,
    preview_string_sync,
)
from apps.sources.sqlite_sync import SQLITE_CONNECTOR, apply_sqlite_sync, preview_sqlite_sync


logger = logging.getLogger(__name__)


@shared_task(name="sources.schedule_previews")
def schedule_source_previews():
    from apps.sources.scheduling import enqueue_due_previews
    return enqueue_due_previews()


def _run_local_sqlite_sync(run: SyncRun) -> dict[str, str | int]:
    # Local file reads do not call an external service. Publish the catalogue,
    # provenance counters and success together; preserve the source -> run lock
    # order used by manual requests and the scheduler.
    with transaction.atomic():
        source = DataSource.objects.select_for_update().get(pk=run.source_id)
        run = SyncRun.objects.select_for_update().get(pk=run.pk)
        if run.status != SyncRun.Status.RUNNING:
            raise TaskExecutionStopped("同步已停止，本次执行不再发布结果。")
        run.source = source
        if not source.enabled:
            raise ValidationError("该数据源已停用，不能执行同步。")
        mode = (run.preview_summary or {}).get("mode", "preview")
        if mode == "preview":
            preview_sqlite_sync(run)
        elif mode == "apply":
            apply_sqlite_sync(run)
        else:
            raise ValidationError("同步运行模式无效。")
        run.status = SyncRun.Status.SUCCEEDED
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at"])
    return {"status": SyncRun.Status.SUCCEEDED, "runId": run.pk}


@shared_task(name="sources.sync_run", base=RecoverableTask)
def sync_source_run(run_id: int) -> dict[str, str | int]:
    claimed = SyncRun.objects.filter(pk=run_id, status=SyncRun.Status.PENDING).update(
        status=SyncRun.Status.RUNNING,
        started_at=timezone.now(),
        error_summary="",
    )
    if not claimed:
        return {"status": "skipped", "runId": run_id}

    try:
        run = SyncRun.objects.select_related("source", "release").get(pk=run_id)
        if run.status != SyncRun.Status.RUNNING:
            return {"status": "skipped", "runId": run_id}
        mode = (run.preview_summary or {}).get("mode", "preview")
        connector = (run.preview_summary or {}).get("connector") or (
            REACTOME_CONNECTOR if run.source.slug == "reactome" else ""
        )
        if not run.source.enabled:
            raise ValidationError("该数据源已停用，不能执行同步。")
        if connector == SQLITE_CONNECTOR:
            return _run_local_sqlite_sync(run)
        if connector == REACTOME_CONNECTOR and mode == "preview":
            preview_reactome_sync(run)
        elif connector == REACTOME_CONNECTOR and mode == "apply":
            apply_reactome_sync(run)
        elif connector == UNIPROT_CONNECTOR and mode == "preview":
            preview_uniprot_sync(run)
        elif connector == UNIPROT_CONNECTOR and mode == "apply":
            apply_uniprot_sync(run)
        elif connector == PUBCHEM_CONNECTOR and mode == "preview":
            preview_pubchem_sync(run)
        elif connector == PUBCHEM_CONNECTOR and mode == "apply":
            apply_pubchem_sync(run)
        elif connector == STRING_CONNECTOR and mode == "preview":
            preview_string_sync(run)
        elif connector == STRING_CONNECTOR and mode == "apply":
            apply_string_sync(run)
        else:
            raise ValidationError("同步运行模式无效。")
        updated = SyncRun.objects.filter(pk=run_id, status=SyncRun.Status.RUNNING).update(
            status=SyncRun.Status.SUCCEEDED,
            finished_at=timezone.now(),
        )
        return {"status": SyncRun.Status.SUCCEEDED if updated else "skipped", "runId": run_id}
    except TaskExecutionStopped:
        return {"status": "skipped", "runId": run_id}
    except ValidationError as exc:
        error = str(exc.detail) if hasattr(exc, "detail") else str(exc)
        logger.info("Source sync rejected run_id=%s reason=%s", run_id, error)
    except Exception:
        logger.exception("Source sync failed run_id=%s", run_id)
        error = "数据源同步失败，请稍后重试或联系平台管理员并提供同步编号。"

    with transaction.atomic():
        updated = SyncRun.objects.filter(pk=run_id, status=SyncRun.Status.RUNNING).update(
            status=SyncRun.Status.FAILED,
            error_summary=error,
            finished_at=timezone.now(),
        )
    return {"status": SyncRun.Status.FAILED if updated else "skipped", "runId": run_id}
