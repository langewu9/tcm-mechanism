"""Bounded, read-only disease evidence lookups over the local knowledge graph."""

from __future__ import annotations

import hashlib
import json
from django.db.models import Q

from apps.core.models import EvidenceRelation, KnowledgeEntity
from .herb_evidence import _entity_record as snapshot_entity_record, _relation_record as snapshot_relation_record
from .disease_names import (
    ALIAS_DATA,
    disease_entity_queryset,
    expand_disease_queries,
    matched_disease_queries,
)


MAX_MATCHES = 20
MAX_RELATIONS = 1200

DISEASE_HERB_TYPE = "disease_herb"
DISEASE_TARGET_TYPES = {"disease_target", "disease_herb_target"}
TARGET_ENTITY_TYPES = [KnowledgeEntity.EntityType.GENE, KnowledgeEntity.EntityType.PROTEIN]


def disease_source_assertions(relation):
    metadata = relation.metadata if isinstance(relation.metadata, dict) else {}
    return {key: metadata[key] if isinstance(metadata.get(key), str) else None
            for key in ("sourceFile", "sourceDiseaseLabel", "sourceHerbLabel", "sourceTargetLabel")}


def disease_relation_snapshot(relation):
    return {**snapshot_relation_record(relation), "evidenceText": relation.evidence_text, "organism": relation.organism,
            **disease_source_assertions(relation)}


def _entity_record(entity: KnowledgeEntity) -> dict:
    release = entity.source_release
    return {
        "id": entity.pk,
        "stableId": entity.stable_id,
        "label": entity.label,
        "sourceSlug": release.source.slug if release else None,
        "sourceVersion": release.version if release else None,
    }


def _relation_record(relation: EvidenceRelation) -> dict:
    source_release = relation.source_release
    return {
        "subject": relation.subject.label,
        "object": relation.object.label,
        "subjectType": relation.subject.entity_type,
        "objectType": relation.object.entity_type,
        "relationType": relation.relation_type,
        "evidenceType": relation.evidence_type,
        "sourceSlug": source_release.source.slug,
        "sourceVersion": source_release.version,
        "sourceRecordId": relation.source_record_id,
        "score": float(relation.score) if relation.score is not None else None,
    }


def _visible_relations(disease_ids: set[int], *, limit=MAX_RELATIONS) -> tuple[list[EvidenceRelation], bool]:
    queryset = EvidenceRelation.objects.filter(
        is_active=True,
        subject__is_active=True,
        object__is_active=True,
        source_release__source__enabled=True,
        subject_id__in=disease_ids,
    ).filter(
        (Q(subject__source_release__isnull=True) | Q(subject__source_release__source__enabled=True))
        & (Q(object__source_release__isnull=True) | Q(object__source_release__source__enabled=True))
    ).filter(
        Q(relation_type=DISEASE_HERB_TYPE, object__entity_type=KnowledgeEntity.EntityType.HERB)
        | Q(
            relation_type__in=DISEASE_TARGET_TYPES,
            object__entity_type__in=TARGET_ENTITY_TYPES,
        )
    ).select_related(
        "subject", "subject__source_release", "subject__source_release__source",
        "object", "object__source_release", "object__source_release__source",
        "source_release", "source_release__source",
    )

    records = list(queryset.order_by(
        "relation_type", "subject__label", "subject__stable_id", "object__label",
        "object__stable_id", "source_release__source__slug", "source_release__version",
        "source_record_id", "id",
    )[: limit + 1])
    return records[:limit], len(records) > limit


def _direct_herb_stable_id(relation: EvidenceRelation) -> str | None:
    metadata = relation.metadata
    if not isinstance(metadata, dict):
        return None
    stable_id = metadata.get("herbStableId")
    if not isinstance(stable_id, str) or not stable_id:
        return None
    return stable_id


def _visible_herbs_by_stable_id(relations: list[EvidenceRelation]) -> dict[str, KnowledgeEntity]:
    stable_ids = {
        stable_id
        for relation in relations
        if relation.relation_type == "disease_herb_target"
        for stable_id in [_direct_herb_stable_id(relation)]
        if stable_id is not None
    }
    if not stable_ids:
        return {}
    herbs = KnowledgeEntity.objects.filter(
        entity_type=KnowledgeEntity.EntityType.HERB,
        stable_id__in=stable_ids,
        is_active=True,
    ).filter(
        Q(source_release__isnull=True) | Q(source_release__source__enabled=True)
    ).select_related("source_release", "source_release__source")
    return {herb.stable_id: herb for herb in herbs}


def search_disease_evidence(query: str, *, relation_limit=None, match_limit=None, capture=None) -> dict:
    relation_limit = MAX_RELATIONS if relation_limit is None else relation_limit
    match_limit = MAX_MATCHES if match_limit is None else match_limit
    query = str(query or "").strip()
    expanded_queries = expand_disease_queries(query)

    # The queryset provides the shared database search, and this value-based
    # check prevents JSON object keys from being treated as disease synonyms.
    matching_records = []
    for entity in disease_entity_queryset(expanded_queries).iterator(chunk_size=min(match_limit + 1, 250)):
        if matched_disease_queries(entity, expanded_queries):
            matching_records.append(entity)
            if len(matching_records) > match_limit:
                break
    matches_truncated = len(matching_records) > match_limit
    matches = matching_records[:match_limit]

    relations, relations_truncated = _visible_relations({entity.pk for entity in matches}, limit=relation_limit) if matches else ([], False)
    direct_herbs = _visible_herbs_by_stable_id(relations)

    herbs_by_id: dict[int, KnowledgeEntity] = {}
    targets_by_id: dict[int, KnowledgeEntity] = {}
    links = []
    for relation in relations:
        herb_label = ""
        target_label = ""
        herb_id, target_id = None, None
        if relation.relation_type == DISEASE_HERB_TYPE:
            herbs_by_id[relation.object_id] = relation.object
            herb_label = relation.object.label
            herb_id = relation.object_id
        else:
            targets_by_id[relation.object_id] = relation.object
            target_label = relation.object.label
            target_id = relation.object_id
            if relation.relation_type == "disease_herb_target":
                stable_id = _direct_herb_stable_id(relation)
                herb = direct_herbs.get(stable_id) if stable_id is not None else None
                if herb is not None:
                    herbs_by_id[herb.pk] = herb
                    herb_label = herb.label
                    herb_id = herb.pk

        links.append({
            **disease_source_assertions(relation),
            "relationId": relation.pk,
            "diseaseId": relation.subject_id,
            "herbId": herb_id,
            "targetId": target_id,
            "sourceReleaseId": relation.source_release_id,
            "disease": relation.subject.label,
            "herb": herb_label,
            "target": target_label,
            "relationType": relation.relation_type,
            "sourceSlug": relation.source_release.source.slug,
            "sourceVersion": relation.source_release.version,
            "sourceRecordId": relation.source_record_id,
        })

    entity_sort_key = lambda entity: (entity.label.casefold(), entity.stable_id.casefold(), entity.pk)
    truncated = matches_truncated or relations_truncated
    result = {
        "query": query,
        "expandedQueries": expanded_queries,
        "aliasSource": ALIAS_DATA["source"],
        "aliasSourceCommit": ALIAS_DATA["sourceCommit"],
        "matches": [_entity_record(entity) for entity in matches],
        "ambiguous": len(matches) > 1,
        "herbs": [_entity_record(entity) for entity in sorted(herbs_by_id.values(), key=entity_sort_key)],
        "targets": [_entity_record(entity) for entity in sorted(targets_by_id.values(), key=entity_sort_key)],
        "relations": [_relation_record(relation) for relation in relations],
        "links": links,
        "counts": {
            "diseases": len(matches),
            "herbs": len(herbs_by_id),
            "targets": len(targets_by_id),
            "links": len(links),
            "relations": len(relations),
        },
        "truncated": truncated,
        "limits": {"maxMatches": match_limit, "maxRelations": relation_limit},
    }
    # Bind the preview not only to display strings but also to real row/entity
    # identities and their source assertions. No live catalogue lookup on export.
    entities = {item.pk: item for item in [*matches, *herbs_by_id.values(), *targets_by_id.values()]}
    identity = {"result": result, "entities": [snapshot_entity_record(entities[key]) for key in sorted(entities)],
                "relations": [disease_relation_snapshot(row) for row in relations]}
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    result["resultSha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    if capture is not None:
        capture(entities=list(entities.values()), relations=relations, links=links)
    return result
