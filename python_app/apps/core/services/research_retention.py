"""Archive private research records without deleting original files or evidence."""
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.models import MedicalCase, MedicalCaseAuditEvent, ResearchDatasetAuditEvent
from .case_audit import create_case_audit_event


def retention_scope(view, queryset):
    if view.action == "list":
        state = view.request.query_params.get("archived", "false")
        if state not in {"true", "false", "all"}:
            raise ValidationError({"archived": "请选择 true、false 或 all。"})
        if state != "all":
            queryset = queryset.filter(archived_at__isnull=state == "false")
    elif view.request.method not in {"GET", "HEAD", "OPTIONS"} and view.action not in {"restore", "destroy"}:
        queryset = queryset.filter(archived_at__isnull=True)
    return queryset


def dataset_audit(dataset, actor, action):
    return ResearchDatasetAuditEvent.objects.create(
        dataset=dataset, owner_id=dataset.owner_id, actor=actor,
        action=action, content_sha256=dataset.content_sha256,
    )


@transaction.atomic
def set_archived(record, *, actor, archived):
    record = type(record).objects.select_for_update().get(pk=record.pk)
    if bool(record.archived_at) == archived:
        return record
    before = {"archived_at": record.archived_at, "archived_by_id": record.archived_by_id}
    record.archived_at = timezone.now() if archived else None
    record.archived_by = actor if archived else None
    record.save(update_fields=["archived_at", "archived_by", "updated_at"])
    if isinstance(record, MedicalCase):
        create_case_audit_event(
            case=record, actor=actor,
            action=MedicalCaseAuditEvent.Action.ARCHIVED if archived else MedicalCaseAuditEvent.Action.RESTORED,
            before=before, after={"archived_at": record.archived_at, "archived_by_id": record.archived_by_id},
        )
    else:
        dataset_audit(record, actor, ResearchDatasetAuditEvent.Action.ARCHIVED if archived else ResearchDatasetAuditEvent.Action.RESTORED)
    return record
