"""Privacy-aware, append-only audit records for researcher medical cases."""

from __future__ import annotations

import hashlib
import json

from apps.core.models import MedicalCase, MedicalCaseAuditEvent


AUDITED_FIELDS = (
    "title",
    "deidentified_text",
    "structured_data",
    "source_reference",
    "research_notes",
    "review_status",
    "reviewed_by_id",
    "reviewed_at",
)


def _digest(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_case_audit_event(*, case: MedicalCase, actor, action: str, before=None, after=None, metadata=None):
    """Record changed field names and hashes, never duplicate clinical text into the audit log."""
    before = before or {}
    after = after or {}
    changed_fields = sorted(set(before) | set(after))
    hashes = {
        field: {
            "before": _digest(before[field]) if field in before else None,
            "after": _digest(after[field]) if field in after else None,
        }
        for field in changed_fields
    }
    return MedicalCaseAuditEvent.objects.create(
        case=case,
        case_id_snapshot=case.pk,
        case_title_snapshot=case.title,
        owner_id=case.owner_id,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        changed_fields=changed_fields,
        content_hashes=hashes,
        metadata=metadata or {},
    )


def case_field_values(case: MedicalCase, fields=None) -> dict:
    selected = fields or AUDITED_FIELDS
    return {field: getattr(case, field) for field in selected}
