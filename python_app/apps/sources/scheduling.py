"""Schedule reviewed previews, never automatically apply a release."""
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.core.exceptions import TaskQueueUnavailable
from apps.core.models import DataSource, SyncRun
from apps.sources.services import (
    PUBCHEM_CONNECTOR, REACTOME_CONNECTOR, STRING_CONNECTOR, UNIPROT_CONNECTOR,
    enqueue_sync_run,
)
from apps.sources.sqlite_sync import SQLITE_CONNECTOR

SUPPORTED = {PUBCHEM_CONNECTOR, REACTOME_CONNECTOR, STRING_CONNECTOR, UNIPROT_CONNECTOR, SQLITE_CONNECTOR}


def enqueue_due_previews():
    counts = {"queued": 0, "failed": 0, "skipped": 0}
    if not settings.SOURCE_SCHEDULED_PREVIEWS_ENABLED:
        return counts
    source_ids = DataSource.objects.filter(
        enabled=True, refresh_interval_hours__gte=1,
    ).values_list("pk", flat=True)
    for source_id in source_ids.iterator():
        with transaction.atomic():
            source = DataSource.objects.select_for_update().filter(pk=source_id).first()
            if source is None:
                counts["skipped"] += 1
                continue
            now = timezone.now()
            connector = (source.configuration or {}).get("connector") or {
                "reactome": REACTOME_CONNECTOR, "string": STRING_CONNECTOR,
            }.get(source.slug, "")
            latest_run = source.sync_runs.order_by("-created_at").first()
            timestamps = [stamp for stamp in (
                source.last_preview_requested_at,
                latest_run.created_at if latest_run else None,
                source.last_success_at,
            ) if stamp is not None]
            last_attempt = max(timestamps) if timestamps else None
            interval = source.refresh_interval_hours
            if (
                not source.enabled or not interval or connector not in SUPPORTED
                or source.sync_runs.filter(status__in=[SyncRun.Status.PENDING, SyncRun.Status.RUNNING]).exists()
                or (last_attempt and now < last_attempt + timedelta(hours=interval))
            ):
                counts["skipped"] += 1
                continue
            run = SyncRun.objects.create(
                source=source, trigger=SyncRun.Trigger.SCHEDULED,
                preview_summary={"mode": "preview", "connector": connector},
            )
            # Preserve backoff even if the broker is temporarily unavailable.
            source.last_preview_requested_at = now
            source.save(update_fields=["last_preview_requested_at", "updated_at"])
        try:
            enqueue_sync_run(run)
        except TaskQueueUnavailable:
            counts["failed"] += 1
        else:
            counts["queued"] += 1
    return counts
