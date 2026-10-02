from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.exceptions import TaskQueueUnavailable
from apps.core.models import DataSource, KnowledgeEntity, SourceRelease, SyncRun
from apps.sources.connectors.reactome import (
    ReactomeCatalogSnapshot,
    fetch_reactome_human_pathway_catalog,
)


REACTOME_SOURCE_SLUG = "reactome"
REACTOME_CONNECTOR = "reactome-catalog"


def enqueue_sync_run(run: SyncRun) -> None:
    try:
        from apps.sources.tasks import sync_source_run

        sync_source_run.delay(run.pk)
    except Exception as exc:
        run.status = SyncRun.Status.FAILED
        run.error_summary = "后台任务队列暂不可用，请检查 Redis 和 worker 后重试。"
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_summary", "finished_at"])
        raise TaskQueueUnavailable() from exc


def build_pathway_preview(source: DataSource, snapshot: ReactomeCatalogSnapshot) -> dict:
    incoming = {item.stable_id: item for item in snapshot.pathways}
    existing = {
        item.stable_id: item
        for item in KnowledgeEntity.objects.filter(
            entity_type=KnowledgeEntity.EntityType.PATHWAY,
            stable_id__in=incoming,
        ).select_related("source_release")
    }
    owned_active_ids = set(
        KnowledgeEntity.objects.filter(
            entity_type=KnowledgeEntity.EntityType.PATHWAY,
            source_release__source=source,
            is_active=True,
        ).values_list("stable_id", flat=True)
    )
    create_count = 0
    update_count = 0
    unchanged_count = 0
    for stable_id, pathway in incoming.items():
        row = existing.get(stable_id)
        if row is None:
            create_count += 1
        elif (
            row.label != pathway.name
            or row.organism != pathway.species
            or not row.is_active
            or row.source_release is None
            or row.source_release.source_id != source.pk
        ):
            update_count += 1
        else:
            unchanged_count += 1

    return {
        "mode": "preview",
        "connector": REACTOME_CONNECTOR,
        "sourceVersion": snapshot.source_version,
        "releaseVersion": snapshot.release_version,
        "checksumSha256": snapshot.checksum_sha256,
        "endpoint": snapshot.endpoint,
        "totalRecords": len(snapshot.pathways),
        "wouldCreate": create_count,
        "wouldUpdate": update_count,
        "unchanged": unchanged_count,
        "wouldRetire": len(owned_active_ids - set(incoming)),
    }


def _get_snapshot() -> ReactomeCatalogSnapshot:
    return fetch_reactome_human_pathway_catalog()


def preview_reactome_sync(run: SyncRun) -> None:
    if run.source.slug != REACTOME_SOURCE_SLUG:
        raise ValidationError("当前仅实现 Reactome 通路目录同步。")
    snapshot = _get_snapshot()
    version = snapshot.release_version
    release, _ = SourceRelease.objects.get_or_create(
        source=run.source,
        version=version,
        defaults={
            "checksum_sha256": snapshot.checksum_sha256,
            "metadata": {
                "sourceVersion": snapshot.source_version,
                "endpoint": snapshot.endpoint,
                "retrievedAt": timezone.now().isoformat(),
                "recordCount": len(snapshot.pathways),
            },
        },
    )
    if release.checksum_sha256 != snapshot.checksum_sha256:
        raise ValidationError("Reactome 版本号与已有校验值不一致，请联系管理员检查来源记录。")
    run.release = release
    run.cursor = snapshot.checksum_sha256
    run.records_seen = len(snapshot.pathways)
    run.preview_summary = build_pathway_preview(run.source, snapshot)
    run.save(
        update_fields=["release", "cursor", "records_seen", "preview_summary"]
    )


def apply_reactome_sync(run: SyncRun) -> None:
    if run.source.slug != REACTOME_SOURCE_SLUG:
        raise ValidationError("当前仅实现 Reactome 通路目录同步。")
    if run.release_id is None or not run.cursor:
        raise ValidationError("缺少预览版本信息，请先重新运行预览。")

    snapshot = _get_snapshot()
    if snapshot.checksum_sha256 != run.cursor or snapshot.checksum_sha256 != run.release.checksum_sha256:
        raise ValidationError("Reactome 源文件在预览后已变化，请重新预览再应用。")

    now = timezone.now()
    incoming_ids = [item.stable_id for item in snapshot.pathways]
    existing = {
        row.stable_id: row
        for row in KnowledgeEntity.objects.filter(
            entity_type=KnowledgeEntity.EntityType.PATHWAY,
            stable_id__in=incoming_ids,
        )
    }
    create_count = sum(stable_id not in existing for stable_id in incoming_ids)
    update_count = len(incoming_ids) - create_count
    upserts = [
        KnowledgeEntity(
            entity_type=KnowledgeEntity.EntityType.PATHWAY,
            stable_id=item.stable_id,
            label=item.name,
            organism=item.species,
            is_active=True,
            source_release=run.release,
            metadata={"source": REACTOME_SOURCE_SLUG, "species": item.species},
            updated_at=now,
        )
        for item in snapshot.pathways
    ]
    with transaction.atomic():
        KnowledgeEntity.objects.bulk_create(
            upserts,
            batch_size=1000,
            update_conflicts=True,
            unique_fields=["entity_type", "stable_id"],
            update_fields=["label", "organism", "is_active", "source_release", "metadata", "updated_at"],
        )
        retired_count = KnowledgeEntity.objects.filter(
            entity_type=KnowledgeEntity.EntityType.PATHWAY,
            source_release__source=run.source,
            is_active=True,
        ).exclude(stable_id__in=incoming_ids).update(is_active=False, updated_at=now)
        run.records_seen = len(incoming_ids)
        run.records_created = create_count
        run.records_updated = update_count
        run.records_retired = retired_count
        run.preview_summary = {
            **(run.preview_summary or {}),
            "mode": "apply",
            "appliedAt": now.isoformat(),
            "checksumSha256": snapshot.checksum_sha256,
        }
        run.save(
            update_fields=[
                "records_seen", "records_created", "records_updated", "records_retired", "preview_summary"
            ]
        )
        DataSource.objects.filter(pk=run.source_id).update(last_success_at=now)
