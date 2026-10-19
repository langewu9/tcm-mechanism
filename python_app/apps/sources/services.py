import hashlib

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.exceptions import TaskQueueUnavailable
from apps.core.models import DataSource, EntityIdentifier, KnowledgeEntity, SourceRelease, SyncRun
from apps.sources.connectors.reactome import (
    ReactomeCatalogSnapshot,
    fetch_reactome_human_pathway_catalog,
)
from apps.sources.connectors.pubchem import (
    PubChemCatalogSnapshot,
    PubChemCatalogError,
    fetch_pubchem_compound_catalog,
    validate_pubchem_mappings,
)
from apps.sources.connectors.uniprot import UniProtCatalogSnapshot, UniProtProtein, fetch_uniprot_human_catalog
from apps.sources.uniprot_identity import build_identity_plan
from apps.sources.connectors.string import (
    STRING_CONNECTOR,
    STRING_SOURCE_SLUG,
    StringCatalogError,
    StringCatalogSnapshot,
    fetch_string_human_identifier_snapshot,
)


REACTOME_SOURCE_SLUG = "reactome"
REACTOME_CONNECTOR = "reactome-catalog"
UNIPROT_SOURCE_SLUG = "uniprot-human"
UNIPROT_CONNECTOR = "uniprot-human-catalog"
PUBCHEM_SOURCE_SLUG = "pubchem-compounds"
PUBCHEM_CONNECTOR = "pubchem-compound-catalog"


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


def build_uniprot_preview(source: DataSource, snapshot: UniProtCatalogSnapshot) -> dict:
    incoming_accessions = {protein.accession for protein in snapshot.proteins}
    plan = build_identity_plan(source, snapshot)
    existing = plan.existing
    owned_accessions = set(
        EntityIdentifier.objects.filter(
            namespace="uniprot",
            source_release__source=source,
            is_active=True,
        ).values_list("identifier", flat=True)
    )
    create_count = sum(accession not in existing for accession in incoming_accessions)
    expected_metadata = {protein.accession: _identifier_values(protein)[0][2] for protein in snapshot.proteins}
    unchanged_count = sum(
        row.is_active
        and row.source_release.source_id == source.pk
        and row.source_release.version == snapshot.release_version
        and row.metadata == expected_metadata[row.identifier]
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
        **plan.summary,
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
    values = [("uniprot", protein.accession, {"primaryGene": protein.primary_gene, "taxonId": 9606})]
    values.extend(
        ("uniprot-gene-name", name, {"scope": "gene_name", "taxonId": 9606})
        for name in protein.gene_names
        if name
    )
    if protein.protein_name and len(protein.protein_name) <= 160:
        values.append(("uniprot-protein-name", protein.protein_name, {"scope": "protein_name", "taxonId": 9606}))
    return tuple(values)


@transaction.atomic
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
    plan = build_identity_plan(run.source, snapshot, lock=True)
    if (run.preview_summary or {}).get("identityPlanSha256") != plan.summary["identityPlanSha256"]:
        raise ValidationError("UniProt 本地身份依据在预览后变化或预览版本过旧，请重新预览再应用。")
    if plan.summary["identifierConflicts"]:
        raise ValidationError("UniProt 已有编号存在物种、符号或归属冲突；未修改知识目录，请先核对再重新预览。")
    existing_accession_rows = plan.existing
    fallback_by_key: dict[tuple[str, str], KnowledgeEntity] = {}
    entity_for_accession: dict[str, KnowledgeEntity] = {}
    for protein in snapshot.proteins:
        if protein.accession in plan.local_entities:
            entity_for_accession[protein.accession] = plan.local_entities[protein.accession]
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
            **plan.summary,
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


def _get_pubchem_snapshot(source: DataSource) -> PubChemCatalogSnapshot:
    configuration = source.configuration or {}
    try:
        mappings = validate_pubchem_mappings(configuration.get("mappings"))
    except PubChemCatalogError as exc:
        raise ValidationError(str(exc)) from exc
    stable_ids = {mapping.stable_id for mapping in mappings}
    compounds = {
        row.stable_id: row
        for row in KnowledgeEntity.objects.filter(
            entity_type=KnowledgeEntity.EntityType.COMPOUND,
            is_active=True,
            stable_id__in=stable_ids,
        ).only("id", "stable_id")
    }
    missing = sorted(stable_ids - set(compounds))
    if missing:
        example = ", ".join(missing[:3])
        raise ValidationError(f"PubChem 映射引用了不存在或已停用的本地成分 stableId：{example}。")

    existing_identifiers = {
        row.identifier: row
        for row in EntityIdentifier.objects.filter(
            namespace="pubchem",
            identifier__in=[mapping.cid for mapping in mappings],
        ).select_related("entity")
    }
    for mapping in mappings:
        previous = existing_identifiers.get(mapping.cid)
        if previous and previous.entity.stable_id != mapping.stable_id:
            raise ValidationError(
                f"PubChem CID {mapping.cid} 已关联到其他本地成分；请先人工核对稳定 ID，不能自动改绑。"
            )
    try:
        return fetch_pubchem_compound_catalog(configuration.get("mappings"))
    except PubChemCatalogError as exc:
        raise ValidationError(str(exc)) from exc


def build_pubchem_preview(source: DataSource, snapshot: PubChemCatalogSnapshot) -> dict:
    incoming = {row.cid: row for row in snapshot.compounds}
    target_entities = {
        row.stable_id: row
        for row in KnowledgeEntity.objects.filter(
            entity_type=KnowledgeEntity.EntityType.COMPOUND,
            stable_id__in=[item.stable_id for item in snapshot.compounds],
        ).only("id", "stable_id", "label")
    }
    existing = {
        row.identifier: row
        for row in EntityIdentifier.objects.filter(
            namespace="pubchem",
            identifier__in=incoming,
        ).select_related("source_release")
    }
    owned_active = set(
        EntityIdentifier.objects.filter(
            namespace="pubchem",
            source_release__source=source,
            is_active=True,
        ).values_list("identifier", flat=True)
    )
    created = sum(cid not in existing for cid in incoming)
    unchanged = sum(
        row.is_active
        and row.source_release.source_id == source.pk
        and row.source_release.version == snapshot.release_version
        for row in existing.values()
    )
    updated = len(incoming) - created - unchanged
    preview_records = []
    for record in snapshot.compounds[:20]:
        compound = target_entities.get(record.stable_id)
        preview_records.append({
            "compound": compound.label if compound else record.stable_id,
            "stableId": record.stable_id,
            "cid": record.cid,
            "molecularFormula": record.molecular_formula,
            "molecularWeight": record.molecular_weight,
            "inchiKey": record.inchikey,
            "iupacName": record.iupac_name,
        })
    return {
        "mode": "preview",
        "connector": PUBCHEM_CONNECTOR,
        "sourceVersion": snapshot.source_version,
        "releaseVersion": snapshot.release_version,
        "checksumSha256": snapshot.checksum_sha256,
        "endpoint": snapshot.endpoint,
        "totalRecords": len(snapshot.compounds),
        "pageCount": snapshot.page_count,
        "wouldCreate": created,
        "wouldUpdate": updated,
        "unchanged": unchanged,
        "wouldRetire": len(owned_active - set(incoming)),
        "previewRecords": preview_records,
        "previewRecordsTruncated": len(snapshot.compounds) > len(preview_records),
    }


def preview_pubchem_sync(run: SyncRun) -> None:
    if run.source.slug != PUBCHEM_SOURCE_SLUG:
        raise ValidationError("该同步连接器只用于经人工映射的 PubChem 成分属性。")
    snapshot = _get_pubchem_snapshot(run.source)
    release, _ = SourceRelease.objects.get_or_create(
        source=run.source,
        version=snapshot.release_version,
        defaults={
            "checksum_sha256": snapshot.checksum_sha256,
            "metadata": {
                "sourceVersion": snapshot.source_version,
                "endpoint": snapshot.endpoint,
                "retrievedAt": timezone.now().isoformat(),
                "recordCount": len(snapshot.compounds),
                "pageCount": snapshot.page_count,
                "versionNote": "PubChem 不提供此组属性的统一目录版本；版本由检索日期和响应/映射 SHA-256 共同标识。",
            },
        },
    )
    if release.checksum_sha256 != snapshot.checksum_sha256:
        raise ValidationError("PubChem 快照版本与已有校验值不一致，请重新预览并检查来源记录。")
    run.release = release
    run.cursor = snapshot.checksum_sha256
    run.records_seen = len(snapshot.compounds)
    run.preview_summary = build_pubchem_preview(run.source, snapshot)
    run.save(update_fields=["release", "cursor", "records_seen", "preview_summary"])


def apply_pubchem_sync(run: SyncRun) -> None:
    if run.source.slug != PUBCHEM_SOURCE_SLUG:
        raise ValidationError("该同步连接器只用于经人工映射的 PubChem 成分属性。")
    if run.release_id is None or not run.cursor:
        raise ValidationError("缺少 PubChem 预览版本信息，请先重新运行预览。")

    snapshot = _get_pubchem_snapshot(run.source)
    if snapshot.checksum_sha256 != run.cursor or snapshot.checksum_sha256 != run.release.checksum_sha256:
        raise ValidationError("PubChem 属性或人工映射在预览后已变化，请重新预览再应用。")

    with transaction.atomic():
        now = timezone.now()
        stable_ids = {row.stable_id for row in snapshot.compounds}
        entities = {
            row.stable_id: row
            for row in KnowledgeEntity.objects.select_for_update().filter(
                entity_type=KnowledgeEntity.EntityType.COMPOUND,
                is_active=True,
                stable_id__in=stable_ids,
            )
        }
        if set(entities) != stable_ids:
            raise ValidationError("预览后本地成分映射发生变化，请重新预览。")
        incoming = {row.cid: row for row in snapshot.compounds}
        previous_ids = set(
            EntityIdentifier.objects.filter(
                namespace="pubchem",
                source_release__source=run.source,
            ).values_list("identifier", flat=True)
        )
        existing = {
            row.identifier: row
            for row in EntityIdentifier.objects.select_for_update().filter(
                namespace="pubchem", identifier__in=incoming
            )
        }
        for record in snapshot.compounds:
            previous = existing.get(record.cid)
            if previous and previous.entity_id != entities[record.stable_id].pk:
                raise ValidationError(f"PubChem CID {record.cid} 已关联到其他本地成分，已中止应用。")

        EntityIdentifier.objects.filter(
            namespace="pubchem",
            source_release__source=run.source,
            is_active=True,
        ).update(is_active=False, updated_at=now)

        identifier_rows = []
        changed_entities = []
        for record in snapshot.compounds:
            entity = entities[record.stable_id]
            pubchem_metadata = {
                "cid": record.cid,
                "iupacName": record.iupac_name,
                "molecularFormula": record.molecular_formula,
                "molecularWeight": record.molecular_weight,
                "canonicalSmiles": record.canonical_smiles,
                "inchiKey": record.inchikey,
                "sourceRelease": run.release.version,
            }
            metadata = entity.metadata if isinstance(entity.metadata, dict) else {}
            entity.metadata = {**metadata, "pubchem": pubchem_metadata}
            entity.updated_at = now
            changed_entities.append(entity)
            identifier_rows.append(EntityIdentifier(
                entity=entity,
                source_release=run.release,
                namespace="pubchem",
                identifier=record.cid,
                is_active=True,
                metadata={"source": PUBCHEM_SOURCE_SLUG},
                updated_at=now,
            ))
        KnowledgeEntity.objects.bulk_update(changed_entities, ["metadata", "updated_at"], batch_size=500)
        if identifier_rows:
            EntityIdentifier.objects.bulk_create(
                identifier_rows,
                batch_size=500,
                update_conflicts=True,
                unique_fields=["namespace", "identifier", "entity"],
                update_fields=["source_release", "is_active", "metadata", "updated_at"],
            )

        current_ids = set(incoming)
        run.records_seen = len(current_ids)
        run.records_created = len(current_ids - set(existing))
        run.records_updated = len(current_ids & set(existing))
        run.records_retired = len(previous_ids - current_ids)
        run.preview_summary = {
            **(run.preview_summary or {}),
            "mode": "apply",
            "appliedAt": now.isoformat(),
            "checksumSha256": snapshot.checksum_sha256,
        }
        run.save(update_fields=["records_seen", "records_created", "records_updated", "records_retired", "preview_summary"])
        DataSource.objects.filter(pk=run.source_id).update(last_success_at=now)


def _get_string_snapshot() -> StringCatalogSnapshot:
    try:
        return fetch_string_human_identifier_snapshot()
    except StringCatalogError as exc:
        raise ValidationError(str(exc)) from exc


def _string_conflict_fingerprint(conflicts: list[tuple[str, int, int]]) -> str:
    payload = "\n".join(f"{identifier}\t{owner_id}\t{target_id}" for identifier, owner_id, target_id in sorted(conflicts))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _string_identifier_metadata(mapping) -> dict:
    return {
        "query": mapping.query,
        "preferredName": mapping.preferred_name,
        "annotation": mapping.annotation,
        "taxonId": 9606,
        "source": STRING_SOURCE_SLUG,
    }


def build_string_preview(source: DataSource, snapshot: StringCatalogSnapshot) -> dict:
    incoming = {item.string_id: item for item in snapshot.mappings}
    existing = {
        row.identifier: row
        for row in EntityIdentifier.objects.filter(
            namespace="string", identifier__in=incoming
        ).select_related("entity", "source_release", "source_release__source")
    }
    owned_active = set(
        EntityIdentifier.objects.filter(
            namespace="string", source_release__source=source, is_active=True
        ).values_list("identifier", flat=True)
    )
    conflicts = [
        (identifier, row.entity_id, incoming[identifier].entity_id)
        for identifier, row in existing.items()
        if row.entity_id != incoming[identifier].entity_id
    ]
    safe_ids = set(incoming) - {item[0] for item in conflicts}
    created = sum(identifier not in existing for identifier in safe_ids)
    unchanged = sum(
        row.is_active
        and row.entity_id == incoming[identifier].entity_id
        and row.source_release.source_id == source.pk
        and row.source_release.version == snapshot.release_version
        and row.metadata == _string_identifier_metadata(incoming[identifier])
        for identifier, row in existing.items()
        if identifier in safe_ids
    )
    updated = len(safe_ids) - created - unchanged
    return {
        "mode": "preview",
        "connector": STRING_CONNECTOR,
        "sourceVersion": snapshot.source_version,
        "releaseVersion": snapshot.release_version,
        "checksumSha256": snapshot.checksum_sha256,
        "endpoint": snapshot.api_endpoint,
        "totalRecords": len(snapshot.mappings),
        "localHumanEntityCount": snapshot.local_entity_count,
        "submittedQueryCount": snapshot.submitted_query_count,
        "wouldCreate": created,
        "wouldUpdate": updated,
        "unchanged": unchanged,
        "wouldRetire": len(owned_active - safe_ids),
        "unmappedQueries": snapshot.unmapped_query_count,
        "ambiguousLocalEntities": snapshot.ambiguous_local_count,
        "ambiguousStringIds": snapshot.ambiguous_remote_count,
        "identifierConflicts": len(conflicts),
        "conflictFingerprint": _string_conflict_fingerprint(conflicts),
        "previewRecords": [
            {
                "entityStableId": row.entity_stable_id,
                "query": row.query,
                "stringId": row.string_id,
                "preferredName": row.preferred_name,
                "annotation": row.annotation,
            }
            for row in snapshot.mappings[:20]
        ],
        "previewRecordsTruncated": len(snapshot.mappings) > 20,
    }


def preview_string_sync(run: SyncRun) -> None:
    if run.source.slug != STRING_SOURCE_SLUG:
        raise ValidationError("该同步连接器只用于 STRING 人类基因/蛋白标识映射。")
    snapshot = _get_string_snapshot()
    release, _ = SourceRelease.objects.get_or_create(
        source=run.source,
        version=snapshot.release_version,
        defaults={
            "checksum_sha256": snapshot.checksum_sha256,
            "metadata": {
                "sourceVersion": snapshot.source_version,
                "endpoint": snapshot.api_endpoint,
                "retrievedAt": timezone.now().isoformat(),
                "recordCount": len(snapshot.mappings),
                "catalogueScope": "STRING mappings for existing local human gene/protein entities",
            },
        },
    )
    if release.checksum_sha256 != snapshot.checksum_sha256:
        raise ValidationError("STRING 版本与已有校验值不一致，请重新预览并检查来源记录。")
    run.release = release
    run.cursor = snapshot.checksum_sha256
    run.records_seen = len(snapshot.mappings)
    run.preview_summary = build_string_preview(run.source, snapshot)
    run.save(update_fields=["release", "cursor", "records_seen", "preview_summary"])


def apply_string_sync(run: SyncRun) -> None:
    if run.source.slug != STRING_SOURCE_SLUG:
        raise ValidationError("该同步连接器只用于 STRING 人类基因/蛋白标识映射。")
    if run.release_id is None or not run.cursor:
        raise ValidationError("缺少 STRING 预览版本信息，请先重新运行预览。")

    snapshot = _get_string_snapshot()
    if snapshot.checksum_sha256 != run.cursor or snapshot.checksum_sha256 != run.release.checksum_sha256:
        raise ValidationError("STRING 映射在预览后已变化，请重新预览再应用。")

    incoming = {item.string_id: item for item in snapshot.mappings}
    with transaction.atomic():
        entities = {
            row.pk: row
            for row in KnowledgeEntity.objects.select_for_update().filter(
                pk__in={item.entity_id for item in incoming.values()},
                is_active=True,
            )
        }
        if set(entities) != {item.entity_id for item in incoming.values()}:
            raise ValidationError("预览后有人类知识实体被删除或停用，请重新预览。")

        existing_rows = {
            row.identifier: row
            for row in EntityIdentifier.objects.select_for_update().filter(
                namespace="string", identifier__in=incoming
            ).select_related("source_release", "source_release__source")
        }
        conflicts = [
            (identifier, row.entity_id, incoming[identifier].entity_id)
            for identifier, row in existing_rows.items()
            if row.entity_id != incoming[identifier].entity_id
        ]
        preview_summary = run.preview_summary or {}
        if _string_conflict_fingerprint(conflicts) != preview_summary.get("conflictFingerprint"):
            raise ValidationError("STRING 标识归属在预览后发生变化，请重新预览并检查冲突。")
        conflict_ids = {item[0] for item in conflicts}
        safe_ids = set(incoming) - conflict_ids
        if not safe_ids:
            raise ValidationError("当前 STRING 映射均与已有标识归属冲突；系统未修改知识目录。")

        now = timezone.now()
        previous_active_ids = set(
            EntityIdentifier.objects.filter(
                namespace="string", source_release__source=run.source, is_active=True
            ).values_list("identifier", flat=True)
        )
        EntityIdentifier.objects.filter(
            namespace="string", source_release__source=run.source, is_active=True
        ).exclude(identifier__in=safe_ids).update(is_active=False, updated_at=now)

        updates = []
        creates = []
        for identifier in sorted(safe_ids):
            mapping = incoming[identifier]
            entity = entities[mapping.entity_id]
            existing = existing_rows.get(identifier)
            metadata = _string_identifier_metadata(mapping)
            if existing is None:
                creates.append(EntityIdentifier(
                    entity=entity,
                    source_release=run.release,
                    namespace="string",
                    identifier=identifier,
                    is_active=True,
                    metadata=metadata,
                    updated_at=now,
                ))
            elif not (
                existing.is_active
                and existing.entity_id == entity.pk
                and existing.source_release_id == run.release_id
                and existing.metadata == metadata
            ):
                existing.entity = entity
                existing.source_release = run.release
                existing.is_active = True
                existing.metadata = metadata
                existing.updated_at = now
                updates.append(existing)
        if updates:
            EntityIdentifier.objects.bulk_update(
                updates, ["entity", "source_release", "is_active", "metadata", "updated_at"], batch_size=1000
            )
        if creates:
            EntityIdentifier.objects.bulk_create(creates, batch_size=1000)

        retired_count = len(previous_active_ids - safe_ids)
        run.records_seen = len(snapshot.mappings)
        run.records_created = len(creates)
        run.records_updated = len(updates)
        run.records_retired = retired_count
        run.preview_summary = {
            **preview_summary,
            "mode": "apply",
            "appliedAt": now.isoformat(),
            "checksumSha256": snapshot.checksum_sha256,
        }
        run.save(update_fields=[
            "records_seen", "records_created", "records_updated", "records_retired", "preview_summary"
        ])
        DataSource.objects.filter(pk=run.source_id).update(last_success_at=now)
