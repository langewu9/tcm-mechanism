from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.exceptions import TaskQueueUnavailable
from apps.core.models import DataSource, EntityIdentifier, KnowledgeEntity, SourceRelease, SyncRun
from apps.sources.connectors.reactome import (
    ReactomeCatalogSnapshot,
    fetch_reactome_human_pathway_catalog,
)
from apps.sources.connectors.uniprot import UniProtCatalogSnapshot, UniProtProtein, fetch_uniprot_human_catalog


REACTOME_SOURCE_SLUG = "reactome"
REACTOME_CONNECTOR = "reactome-catalog"
UNIPROT_SOURCE_SLUG = "uniprot-human"
UNIPROT_CONNECTOR = "uniprot-human-catalog"


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


def _canonical_identifier(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def build_uniprot_preview(source: DataSource, snapshot: UniProtCatalogSnapshot) -> dict:
    incoming_accessions = {protein.accession for protein in snapshot.proteins}
    existing = {
        row.identifier: row
        for row in EntityIdentifier.objects.filter(
            namespace="uniprot",
            identifier__in=incoming_accessions,
        ).select_related("source_release", "source_release__source", "entity")
    }
    owned_accessions = set(
        EntityIdentifier.objects.filter(
            namespace="uniprot",
            source_release__source=source,
            is_active=True,
        ).values_list("identifier", flat=True)
    )
    symbols = {protein.primary_gene for protein in snapshot.proteins if protein.primary_gene}
    local_symbol_entities: dict[str, set[int]] = {}
    candidates = KnowledgeEntity.objects.filter(
        entity_type=KnowledgeEntity.EntityType.PROTEIN,
        is_active=True,
    ).filter(Q(source_release__isnull=True) | ~Q(source_release__source=source))
    for entity in candidates.only("id", "stable_id", "label", "metadata", "synonyms"):
        metadata = entity.metadata if isinstance(entity.metadata, dict) else {}
        symbol = metadata.get("symbol") or metadata.get("gene_symbol")
        if symbol and str(symbol) in symbols:
            local_symbol_entities.setdefault(_canonical_identifier(str(symbol)), set()).add(entity.pk)

    create_count = sum(accession not in existing for accession in incoming_accessions)
    unchanged_count = sum(
        row.is_active
        and row.source_release.source_id == source.pk
        and row.source_release.version == snapshot.release_version
        for row in existing.values()
    )
    update_count = len(incoming_accessions) - create_count - unchanged_count
    return {
        "mode": "preview",
        "connector": UNIPROT_CONNECTOR,
        "sourceVersion": snapshot.source_version,
        "releaseVersion": snapshot.release_version,
        "checksumSha256": snapshot.checksum_sha256,
        "endpoint": snapshot.endpoint,
        "totalRecords": snapshot.total_results,
        "pageCount": snapshot.page_count,
        "wouldCreate": create_count,
        "wouldUpdate": update_count,
        "unchanged": unchanged_count,
        "wouldRetire": len(owned_accessions - incoming_accessions),
        "geneSymbolsMappedToExistingTargets": sum(
            len(local_symbol_entities.get(_canonical_identifier(symbol), set())) == 1
            for symbol in symbols
        ),
        "ambiguousLocalGeneSymbols": sum(
            len(local_symbol_entities.get(_canonical_identifier(symbol), set())) > 1
            for symbol in symbols
        ),
        "releaseDate": snapshot.source_release_date,
    }


def _get_uniprot_snapshot() -> UniProtCatalogSnapshot:
    return fetch_uniprot_human_catalog()


def preview_uniprot_sync(run: SyncRun) -> None:
    if run.source.slug != UNIPROT_SOURCE_SLUG:
        raise ValidationError("该同步连接器只用于 UniProt 人类审核蛋白目录。")
    snapshot = _get_uniprot_snapshot()
    release, _ = SourceRelease.objects.get_or_create(
        source=run.source,
        version=snapshot.release_version,
        defaults={
            "checksum_sha256": snapshot.checksum_sha256,
            "published_at": None,
            "metadata": {
                "sourceVersion": snapshot.source_version,
                "releaseDate": snapshot.source_release_date,
                "endpoint": snapshot.endpoint,
                "retrievedAt": timezone.now().isoformat(),
                "recordCount": snapshot.total_results,
                "pageCount": snapshot.page_count,
            },
        },
    )
    if release.checksum_sha256 != snapshot.checksum_sha256:
        raise ValidationError("UniProt 版本号与校验值不一致，请重新预览并检查来源记录。")
    run.release = release
    run.cursor = snapshot.checksum_sha256
    run.records_seen = snapshot.total_results
    run.preview_summary = build_uniprot_preview(run.source, snapshot)
    run.save(update_fields=["release", "cursor", "records_seen", "preview_summary"])


def _uniprot_fallback_entity(protein: UniProtProtein, now, release: SourceRelease) -> KnowledgeEntity:
    if protein.primary_gene:
        entity_type = KnowledgeEntity.EntityType.GENE
        stable_id = f"uniprot-gene:{protein.primary_gene}"[:160]
        label = protein.primary_gene
        metadata = {
            "source": UNIPROT_SOURCE_SLUG,
            "symbol": protein.primary_gene,
            "accession": protein.accession,
            "proteinName": protein.protein_name,
            "geneNames": list(protein.gene_names),
        }
    else:
        entity_type = KnowledgeEntity.EntityType.PROTEIN
        stable_id = f"uniprot:{protein.accession}"
        label = protein.protein_name or protein.accession
        metadata = {
            "source": UNIPROT_SOURCE_SLUG,
            "accession": protein.accession,
            "proteinName": protein.protein_name,
            "geneNames": list(protein.gene_names),
        }
    return KnowledgeEntity(
        entity_type=entity_type,
        stable_id=stable_id,
        label=label[:300],
        organism="Homo sapiens",
        is_active=True,
        source_release=release,
        synonyms=list(dict.fromkeys([*protein.gene_names, protein.protein_name]))[:50],
        metadata=metadata,
        updated_at=now,
    )


def _identifier_values(protein: UniProtProtein) -> tuple[tuple[str, str, dict], ...]:
    values = [("uniprot", protein.accession, {"primaryGene": protein.primary_gene})]
    values.extend(
        ("uniprot-gene-name", name, {"scope": "gene_name"})
        for name in protein.gene_names
        if name
    )
    if protein.protein_name and len(protein.protein_name) <= 160:
        values.append(("uniprot-protein-name", protein.protein_name, {"scope": "protein_name"}))
    return tuple(values)


def apply_uniprot_sync(run: SyncRun) -> None:
    if run.source.slug != UNIPROT_SOURCE_SLUG:
        raise ValidationError("该同步连接器只用于 UniProt 人类审核蛋白目录。")
    if run.release_id is None or not run.cursor:
        raise ValidationError("缺少 UniProt 预览版本信息，请先重新运行预览。")

    snapshot = _get_uniprot_snapshot()
    if snapshot.checksum_sha256 != run.cursor or snapshot.checksum_sha256 != run.release.checksum_sha256:
        raise ValidationError("UniProt 目录在预览后已变化，请重新预览再应用。")

    now = timezone.now()
    incoming_accessions = {protein.accession for protein in snapshot.proteins}
    previous_accessions = set(
        EntityIdentifier.objects.filter(
            source_release__source=run.source,
            namespace="uniprot",
        ).values_list("identifier", flat=True)
    )
    existing_accession_rows = {
        row.identifier: row
        for row in EntityIdentifier.objects.filter(
            namespace="uniprot", identifier__in=incoming_accessions
        )
    }
    fallback_by_key: dict[tuple[str, str], KnowledgeEntity] = {}
    entity_for_accession: dict[str, KnowledgeEntity] = {}
    symbol_entities: dict[str, set[int]] = {}
    local_targets = KnowledgeEntity.objects.filter(
        entity_type=KnowledgeEntity.EntityType.PROTEIN,
        is_active=True,
    ).filter(Q(source_release__isnull=True) | ~Q(source_release__source=run.source))
    for entity in local_targets.only("id", "metadata"):
        metadata = entity.metadata if isinstance(entity.metadata, dict) else {}
        symbol = metadata.get("symbol") or metadata.get("gene_symbol")
        if symbol:
            symbol_entities.setdefault(_canonical_identifier(str(symbol)), set()).add(entity.pk)

    for protein in snapshot.proteins:
        matches = symbol_entities.get(_canonical_identifier(protein.primary_gene), set()) if protein.primary_gene else set()
        if len(matches) == 1:
            entity_for_accession[protein.accession] = KnowledgeEntity(pk=next(iter(matches)))
        else:
            entity = _uniprot_fallback_entity(protein, now, run.release)
            key = (entity.entity_type, entity.stable_id)
            fallback_by_key[key] = entity
            entity_for_accession[protein.accession] = entity

    with transaction.atomic():
        EntityIdentifier.objects.filter(
            source_release__source=run.source,
            is_active=True,
        ).update(is_active=False, updated_at=now)
        KnowledgeEntity.objects.filter(
            source_release__source=run.source,
            entity_type__in=[KnowledgeEntity.EntityType.GENE, KnowledgeEntity.EntityType.PROTEIN],
            is_active=True,
        ).update(is_active=False, updated_at=now)

        if fallback_by_key:
            KnowledgeEntity.objects.bulk_create(
                list(fallback_by_key.values()),
                batch_size=1000,
                update_conflicts=True,
                unique_fields=["entity_type", "stable_id"],
                update_fields=["label", "organism", "is_active", "source_release", "synonyms", "metadata", "updated_at"],
            )
            fallback_rows = KnowledgeEntity.objects.filter(
                entity_type__in={key[0] for key in fallback_by_key},
                stable_id__in={key[1] for key in fallback_by_key},
            )
            fallback_ids = {(row.entity_type, row.stable_id): row for row in fallback_rows}
            for protein in snapshot.proteins:
                entity = entity_for_accession[protein.accession]
                if entity.pk is None:
                    key = (entity.entity_type, entity.stable_id)
                    entity_for_accession[protein.accession] = fallback_ids[key]

        accession_existing = set(existing_accession_rows)
        identifier_rows: dict[tuple[str, str, int], EntityIdentifier] = {}
        new_accession_rows: list[EntityIdentifier] = []
        updated_accession_rows: list[EntityIdentifier] = []
        for protein in snapshot.proteins:
            entity = entity_for_accession[protein.accession]
            for namespace, identifier, metadata in _identifier_values(protein):
                if namespace == "uniprot":
                    row = existing_accession_rows.get(identifier)
                    if row is None:
                        new_accession_rows.append(EntityIdentifier(
                            entity=entity,
                            source_release=run.release,
                            namespace=namespace,
                            identifier=identifier,
                            is_active=True,
                            metadata=metadata,
                            updated_at=now,
                        ))
                    else:
                        row.entity = entity
                        row.source_release = run.release
                        row.is_active = True
                        row.metadata = metadata
                        row.updated_at = now
                        updated_accession_rows.append(row)
                else:
                    key = (namespace, identifier, entity.pk)
                    identifier_rows[key] = EntityIdentifier(
                        entity=entity,
                        source_release=run.release,
                        namespace=namespace,
                        identifier=identifier,
                        is_active=True,
                        metadata=metadata,
                        updated_at=now,
                    )
        if updated_accession_rows:
            EntityIdentifier.objects.bulk_update(
                updated_accession_rows,
                ["entity", "source_release", "is_active", "metadata", "updated_at"],
                batch_size=1000,
            )
        if new_accession_rows:
            EntityIdentifier.objects.bulk_create(new_accession_rows, batch_size=1000)
        EntityIdentifier.objects.bulk_create(
            list(identifier_rows.values()),
            batch_size=1000,
            update_conflicts=True,
            unique_fields=["namespace", "identifier", "entity"],
            update_fields=["source_release", "is_active", "metadata", "updated_at"],
        )

        retired_count = len(previous_accessions - incoming_accessions)
        run.records_seen = snapshot.total_results
        run.records_created = len(incoming_accessions - accession_existing)
        run.records_updated = len(incoming_accessions & accession_existing)
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
