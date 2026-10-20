"""Account-wide retained-upload budgets; serialize admission on PostgreSQL."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count, Sum

from apps.core.exceptions import UploadQuotaExceeded
from apps.core.models import ResearchDataset, ResearchUploadQuota


def upload_quota_usage(user_id):
    quota = ResearchUploadQuota.objects.filter(user_id=user_id).first()
    limit_bytes = (
        quota.storage_limit_mib * 1024 * 1024
        if quota is not None and quota.storage_limit_mib is not None
        else settings.DATASET_STORAGE_QUOTA_BYTES
    )
    limit_datasets = (
        quota.dataset_limit if quota is not None and quota.dataset_limit is not None
        else settings.DATASET_COUNT_QUOTA
    )
    retained = ResearchDataset.objects.filter(owner_id=user_id).aggregate(bytes=Sum("byte_size"), datasets=Count("pk"))
    used_bytes = retained["bytes"] or 0
    used_datasets = retained["datasets"]
    return {
        "limitBytes": limit_bytes, "limitDatasets": limit_datasets,
        "usedBytes": used_bytes, "usedDatasets": used_datasets,
        "remainingBytes": max(0, limit_bytes - used_bytes),
        "remainingDatasets": max(0, limit_datasets - used_datasets),
    }


def check_locked_upload_quota(user_id, incoming_bytes):
    """Caller holds transaction.atomic through file/row creation and audit.

    Lock the existing user row, even when no quota override exists yet. Admin
    quota edits save that same user inside their transaction before the inline.
    Archived originals are retained, so they continue to consume the budget.
    """
    get_user_model().objects.select_for_update().only("pk").get(pk=user_id)
    usage = upload_quota_usage(user_id)
    if incoming_bytes > usage["remainingBytes"] or usage["remainingDatasets"] < 1:
        raise UploadQuotaExceeded({**usage, "incomingBytes": incoming_bytes})
    return usage
