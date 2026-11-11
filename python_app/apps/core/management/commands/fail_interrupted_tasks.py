"""Maintenance-only reconciliation after all workers have been stopped."""
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.core.models import AnalysisTask, SyncRun
from apps.core.services.task_recovery import fail_running_record


class Command(BaseCommand):
    help = "Preview interrupted running records; apply only with all workers stopped. Never re-enqueues."

    def add_arguments(self, parser):
        parser.add_argument("--before", required=True, help="Explicit timezone-aware ISO cutoff, earlier than now.")
        parser.add_argument("--kind", choices=["analysis", "sync", "all"], default="all")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--workers-stopped", action="store_true",
                            help="Operator confirms all workers/producers are stopped for maintenance; not automatic detection.")

    def handle(self, *args, **options):
        try:
            cutoff = parse_datetime(options["before"])
        except ValueError:
            cutoff = None
        if cutoff is None or timezone.is_naive(cutoff) or cutoff >= timezone.now():
            raise CommandError("--before must be a timezone-aware ISO timestamp earlier than now.")
        if options["apply"] and not options["workers_stopped"]:
            raise CommandError("Stop every worker and producer first, then confirm with --workers-stopped. This is an operator assertion, not worker detection.")
        models = [AnalysisTask, SyncRun] if options["kind"] == "all" else [
            AnalysisTask if options["kind"] == "analysis" else SyncRun]
        report = {"dryRun": not options["apply"], "matched": 0, "updated": 0,
                  "skippedLocked": 0, "kind": options["kind"], "before": cutoff.isoformat(),
                  "automaticRetry": False, "workersStoppedAutomaticallyVerified": False}
        for model in models:
            queryset = model.objects.filter(status="running", started_at__lte=cutoff)
            record_ids = list(queryset.order_by("pk").values_list("pk", flat=True))
            report["matched"] += len(record_ids)
            if not options["apply"]:
                continue
            for record_id in record_ids:
                with transaction.atomic():
                    locked = queryset.filter(pk=record_id).select_for_update(
                        skip_locked=connection.features.has_select_for_update_skip_locked).first()
                    if locked is None:
                        if queryset.filter(pk=record_id).exists():
                            report["skippedLocked"] += 1
                        continue
                    report["updated"] += int(fail_running_record(model, record_id))
        self.stdout.write(json.dumps(report, ensure_ascii=False))
