"""Preview and import the legacy SQLite herb/component/target table."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.models import DataSource, EvidenceRelation, KnowledgeEntity, SourceRelease, SyncRun
from apps.sources.connectors.sqlite_tcm import (
    MAX_TARGETS_PER_ROW,
    SQLiteSourceError,
    clean_cell,
    inspect_sqlite_source,
    iter_configured_rows,
    split_targets,
)


SQLITE_CONNECTOR = "sqlite-herb-compound-target"
EVIDENCE_TYPE = "curated_sqlite_database"
_SPACE = re.compile(r"\s+")


def _canonical(value: str) -> str:
    return _SPACE.sub(" ", value.strip().casefold())


def _stable_id(source: DataSource, kind: str, label: str) -> str:
    digest = hashlib.sha256(_canonical(label).encode("utf-8")).hexdigest()
    return f"sqlite:{source.slug}:{kind}:{digest}"


def _configuration_sha256(configuration: dict) -> str:
    encoded = json.dumps(configuration, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sqlite_snapshot(source: DataSource):
    if (source.configuration or {}).get("connector") != SQLITE_CONNECTOR:
        raise ValidationError("该数据源不是受支持的 SQLite 中药—成分—靶点来源。")
    try:
        return inspect_sqlite_source(source.configuration)
    except SQLiteSourceError as exc:
        raise ValidationError(str(exc)) from exc


def _source_rows(source: DataSource):
    try:
        yield from iter_configured_rows(source.configuration)
    except SQLiteSourceError as exc:
        raise ValidationError(str(exc)) from exc


def _ensure_snapshot_unchanged(source: DataSource, expected_checksum: str) -> None:
    snapshot = _sqlite_snapshot(source)
    if snapshot.checksum_sha256 != expected_checksum:
        raise ValidationError("SQLite 文件在预览后已变化，请重新测试并预览后再应用。")


def _row_entities_and_relations(source: DataSource, row):
    kind, row_id, first_value, second_value, third_value = row
    herb = clean_cell(first_value) if kind == "herb" else ""
    compound = clean_cell(second_value) if kind == "herb" else ""
    disease = clean_cell(first_value) if kind in {"diseaseTarget", "diseaseHerbTarget"} else ""
    disease_herb = clean_cell(second_value) if kind == "diseaseHerbTarget" else ""
    raw_targets = third_value if kind in {"herb", "diseaseHerbTarget"} else second_value
    source_file = clean_cell(third_value) if kind == "diseaseTarget" else ""
    targets = list(dict.fromkeys(split_targets(raw_targets)))
    if len(targets) > MAX_TARGETS_PER_ROW:
        raise ValidationError(f"源文件中单行拆分出的靶点超过 {MAX_TARGETS_PER_ROW} 个，请检查分隔符和数据内容。")
    entities: dict[tuple[str, str], dict] = {}
    relation_specs: list[tuple[str, str, str, str, int, dict]] = []

    def add_entity(kind: str, entity_type: str, label: str) -> str:
        if len(label) > 300:
            raise ValidationError("源文件中存在超过 300 个字符的实体名称，请先清理该字段。")
        stable_id = _stable_id(source, kind, label)
        key = (entity_type, stable_id)
        metadata = {"source": source.slug, "sourceKind": kind}
        if kind == "target":
            metadata["symbol"] = label
        entities[key] = {
            "entity_type": entity_type,
            "stable_id": stable_id,
            "label": label,
            "metadata": metadata,
        }
        return stable_id

    herb_id = add_entity("herb", KnowledgeEntity.EntityType.HERB, herb) if herb else ""
    compound_id = add_entity("compound", KnowledgeEntity.EntityType.COMPOUND, compound) if compound else ""
    disease_id = add_entity("disease", KnowledgeEntity.EntityType.DISEASE, disease) if disease else ""
    target_ids = [
        add_entity("target", KnowledgeEntity.EntityType.PROTEIN, target)
        for target in targets
        if target
    ]
    if herb_id and compound_id:
        relation_specs.append(("contains", herb_id, compound_id, f"herb:{row_id}:herb-compound", row_id, {}))
    if compound_id:
        relation_specs.extend(
            ("targets", compound_id, target_id, f"herb:{row_id}:compound-target:{target_id.rsplit(':', 1)[-1]}", row_id, {})
            for target_id in target_ids
        )
    if disease_id and kind == "diseaseTarget":
        relation_specs.extend(
            ("disease_target", disease_id, target_id, f"diseaseTarget:{row_id}:{target_id.rsplit(':', 1)[-1]}", row_id, {"sourceFile": source_file})
            for target_id in target_ids
        )
    if disease_id and kind == "diseaseHerbTarget" and disease_herb:
        disease_herb_id = add_entity("herb", KnowledgeEntity.EntityType.HERB, disease_herb)
        relation_specs.append(("disease_herb", disease_id, disease_herb_id, f"diseaseHerbTarget:{row_id}:herb", row_id, {}))
        relation_specs.extend(
            ("disease_herb_target", disease_id, target_id, f"diseaseHerbTarget:{row_id}:disease-target:{target_id.rsplit(':', 1)[-1]}", row_id, {"herbStableId": disease_herb_id, "herbLabel": disease_herb})
            for target_id in target_ids
        )
        relation_specs.extend(
            ("herb_disease_target", disease_herb_id, target_id, f"diseaseHerbTarget:{row_id}:herb-target:{target_id.rsplit(':', 1)[-1]}", row_id, {"diseaseStableId": disease_id, "diseaseLabel": disease})
            for target_id in target_ids
        )
    return list(entities.values()), relation_specs


def preview_sqlite_sync(run: SyncRun) -> None:
    source = run.source
    snapshot = _sqlite_snapshot(source)
    configuration_sha256 = _configuration_sha256(source.configuration)
    release_version = f"sqlite-{snapshot.checksum_sha256}-{configuration_sha256[:12]}"
    seen: dict[str, dict[str, str]] = defaultdict(dict)
    relation_count = 0
    rows_seen = 0
    for row in _source_rows(source):
        entities, relations = _row_entities_and_relations(source, row)
        for entity in entities:
            seen[entity["entity_type"]][entity["stable_id"]] = entity["label"]
        relation_count += len(relations)
        rows_seen += 1
        if rows_seen > settings.SQLITE_SOURCE_MAX_ROWS:
            raise ValidationError("SQLite 数据表超过配置的最大导入行数。")
    if rows_seen != snapshot.row_count:
        raise ValidationError("SQLite 文件读取行数与预览时记录数不一致，请停止写入后重试。")
    if rows_seen == 0 or relation_count == 0:
        raise ValidationError("所选 SQLite 数据表没有有效的中药—成分—靶点关系，不能预览或覆盖现有目录。")
    if _sqlite_snapshot(source).checksum_sha256 != snapshot.checksum_sha256:
        raise ValidationError("SQLite 文件在预览期间发生变化，请暂停写入后重试。")

    incoming_ids = set().union(*(set(items) for items in seen.values())) if seen else set()
    existing_rows = []
    for entity_type, labels_by_id in seen.items():
        stable_ids = list(labels_by_id)
        for start in range(0, len(stable_ids), 500):
            existing_rows.extend(
                KnowledgeEntity.objects.filter(
                    entity_type=entity_type,
                    stable_id__in=stable_ids[start : start + 500],
                ).values("entity_type", "stable_id", "label", "is_active", "source_release_id")
            )
    release, _ = SourceRelease.objects.get_or_create(
        source=source,
        version=release_version,
        defaults={
            "checksum_sha256": snapshot.checksum_sha256,
            "metadata": {
                "connector": SQLITE_CONNECTOR,
                "databaseFile": source.configuration["databaseFile"],
                "table": source.configuration["table"],
                "diseaseTargetTable": source.configuration.get("diseaseTargetTable") or None,
                "diseaseHerbTargetTable": source.configuration.get("diseaseHerbTargetTable") or None,
                "configurationSha256": configuration_sha256,
                "columnMapping": {
                    "herb": source.configuration["herbColumn"],
                    "compound": source.configuration["compoundColumn"],
                    "target": source.configuration["targetColumn"],
                    "disease": source.configuration.get("diseaseColumn"),
                    "diseaseTarget": source.configuration.get("diseaseTargetColumn"),
                    "diseaseHerb": source.configuration.get("diseaseHerbHerbColumn"),
                    "diseaseHerbTarget": source.configuration.get("diseaseHerbTargetColumn"),
                },
                "recordCount": snapshot.row_count,
                "tableRowCounts": snapshot.table_row_counts,
                "fileBytes": snapshot.file_size,
                "retrievedAt": timezone.now().isoformat(),
            },
        },
    )
    if release.checksum_sha256 != snapshot.checksum_sha256:
        raise ValidationError("SQLite 来源版本与已有校验值不一致，请联系平台管理员检查。")
    existing = {(row["entity_type"], row["stable_id"]): row for row in existing_rows}
    would_create = 0
    would_update = 0
    for entity_type, labels_by_id in seen.items():
        for stable_id, label in labels_by_id.items():
            previous = existing.get((entity_type, stable_id))
            if previous is None:
                would_create += 1
            elif (
                not previous["is_active"]
                or previous["label"] != label
                or previous["source_release_id"] != release.pk
            ):
                would_update += 1
    active_ids = set(
        KnowledgeEntity.objects.filter(
            source_release__source=source,
            entity_type__in=seen.keys(),
            is_active=True,
        ).values_list("stable_id", flat=True)
    )
    run.release = release
    run.cursor = snapshot.checksum_sha256
    run.records_seen = rows_seen
    run.preview_summary = {
        "mode": "preview",
        "connector": SQLITE_CONNECTOR,
        "checksumSha256": snapshot.checksum_sha256,
        "configurationSha256": configuration_sha256,
        "releaseVersion": release_version,
        "databaseFile": source.configuration["databaseFile"],
        "table": source.configuration["table"],
        "tableRowCounts": snapshot.table_row_counts,
        "fileBytes": snapshot.file_size,
        "totalRows": rows_seen,
        "uniqueHerbs": len(seen.get(KnowledgeEntity.EntityType.HERB, {})),
        "uniqueCompounds": len(seen.get(KnowledgeEntity.EntityType.COMPOUND, {})),
        "uniqueTargets": len(seen.get(KnowledgeEntity.EntityType.PROTEIN, {})),
        "uniqueDiseases": len(seen.get(KnowledgeEntity.EntityType.DISEASE, {})),
        "uniqueDiseases": len(seen.get(KnowledgeEntity.EntityType.DISEASE, {})),
        "relationships": relation_count,
        "wouldCreate": would_create,
        "wouldUpdate": would_update,
        "wouldRetire": len(active_ids - incoming_ids),
    }
    run.save(update_fields=["release", "cursor", "records_seen", "preview_summary"])


def _apply_sqlite_batch(source: DataSource, release: SourceRelease, rows: list, seen_ids: set[str], counters: dict):
    entity_payloads: dict[tuple[str, str], dict] = {}
    relation_payloads: list[tuple[str, str, str, str, int, dict]] = []
    for row in rows:
        entities, relations = _row_entities_and_relations(source, row)
        entity_payloads.update({(entity["entity_type"], entity["stable_id"]): entity for entity in entities})
        relation_payloads.extend(relations)

    entity_keys = list(entity_payloads)
    existing_entities = {
        (entity_type, stable_id): (label, organism, synonyms, metadata, is_active, source_release_id)
        for entity_type, stable_id, label, organism, synonyms, metadata, is_active, source_release_id in KnowledgeEntity.objects.filter(
            entity_type__in={key[0] for key in entity_keys},
            stable_id__in={key[1] for key in entity_keys},
        ).values_list(
            "entity_type", "stable_id", "label", "organism", "synonyms", "metadata", "is_active", "source_release_id"
        )
    } if entity_keys else {}
    for entity_type, stable_id in entity_keys:
        if stable_id not in seen_ids:
            seen_ids.add(stable_id)
            previous = existing_entities.get((entity_type, stable_id))
            payload = entity_payloads[(entity_type, stable_id)]
            if previous is None:
                counters["created"] += 1
            elif (
                previous[0] != payload["label"]
                or previous[1] != ""
                or previous[2] != []
                or previous[3] != payload["metadata"]
                or not previous[4]
                or previous[5] != release.pk
            ):
                counters["updated"] += 1
            else:
                counters["unchanged"] += 1

    now = timezone.now()
    entity_objects = [
        KnowledgeEntity(
            **payload,
            organism="",
            synonyms=[],
            is_active=True,
            source_release=release,
            updated_at=now,
        )
        for payload in entity_payloads.values()
    ]
    if entity_objects:
        KnowledgeEntity.objects.bulk_create(
            entity_objects,
            batch_size=500,
            update_conflicts=True,
            unique_fields=["entity_type", "stable_id"],
            update_fields=["label", "organism", "synonyms", "is_active", "source_release", "metadata", "updated_at"],
        )
    ids_by_stable = {
        stable_id: pk
        for pk, stable_id in KnowledgeEntity.objects.filter(
            stable_id__in={key[1] for key in entity_keys}
        ).values_list("pk", "stable_id")
    } if entity_keys else {}
    record_ids = [spec[3] for spec in relation_payloads]
    existing_relation_ids = set(
        EvidenceRelation.objects.filter(source_release=release, source_record_id__in=record_ids)
        .values_list("source_record_id", flat=True)
    ) if record_ids else set()
    counters["relationsCreated"] += sum(record_id not in existing_relation_ids for record_id in record_ids)
    counters["relationsUpdated"] += len(existing_relation_ids)
    relation_objects = [
        EvidenceRelation(
            source_release=release,
            source_record_id=record_id,
            subject_id=ids_by_stable[subject_stable_id],
            object_id=ids_by_stable[object_stable_id],
            relation_type=relation_type,
            evidence_type=EVIDENCE_TYPE,
        evidence_text=f"Imported from SQLite rowid {row_id}",
        is_active=True,
        metadata={"sourceRowId": row_id, "source": source.slug, **relation_metadata},
        )
            for relation_type, subject_stable_id, object_stable_id, record_id, row_id, relation_metadata in relation_payloads
        ]
    if relation_objects:
        EvidenceRelation.objects.bulk_create(
            relation_objects,
            batch_size=500,
            update_conflicts=True,
            unique_fields=["source_release", "source_record_id"],
            update_fields=[
                "subject", "object", "relation_type", "evidence_type", "evidence_text", "organism", "is_active", "metadata"
            ],
        )


def apply_sqlite_sync(run: SyncRun) -> None:
    source = run.source
    if run.release_id is None or not run.cursor:
        raise ValidationError("缺少预览版本信息，请先重新运行预览。")
    if (run.preview_summary or {}).get("configurationSha256") != _configuration_sha256(source.configuration):
        raise ValidationError("SQLite 数据表或列映射在预览后已变化，请重新测试并预览。")
    _ensure_snapshot_unchanged(source, run.cursor)
    counters = {"created": 0, "updated": 0, "unchanged": 0, "relationsCreated": 0, "relationsUpdated": 0}
    seen_ids: set[str] = set()
    rows_seen = 0
    batch = []

    with transaction.atomic():
        for row in _source_rows(source):
            batch.append(row)
            if len(batch) < 250:
                continue
            _apply_sqlite_batch(source, run.release, batch, seen_ids, counters)
            rows_seen += len(batch)
            batch.clear()
        if batch:
            _apply_sqlite_batch(source, run.release, batch, seen_ids, counters)
            rows_seen += len(batch)
        if rows_seen != run.records_seen:
            raise ValidationError("SQLite 文件读取行数与预览时记录数不一致，请重新预览。")
        _ensure_snapshot_unchanged(source, run.cursor)
        retired = KnowledgeEntity.objects.filter(
            source_release__source=source,
            entity_type__in=[
                KnowledgeEntity.EntityType.HERB,
                KnowledgeEntity.EntityType.COMPOUND,
                KnowledgeEntity.EntityType.PROTEIN,
                KnowledgeEntity.EntityType.DISEASE,
            ],
            is_active=True,
        ).exclude(source_release=run.release).update(is_active=False, updated_at=timezone.now())
        EvidenceRelation.objects.filter(
            source_release__source=source,
            is_active=True,
        ).exclude(source_release=run.release).update(is_active=False)
        run.records_seen = rows_seen
        run.records_created = counters["created"]
        run.records_updated = counters["updated"]
        run.records_retired = retired
        run.preview_summary = {
            **(run.preview_summary or {}),
            "mode": "apply",
            "appliedAt": timezone.now().isoformat(),
            "relationshipsCreated": counters["relationsCreated"],
            "relationshipsUpdated": counters["relationsUpdated"],
            "entitiesUnchanged": counters["unchanged"],
        }
        run.save(
            update_fields=["records_seen", "records_created", "records_updated", "records_retired", "preview_summary"]
        )
        DataSource.objects.filter(pk=source.pk).update(last_success_at=timezone.now())
