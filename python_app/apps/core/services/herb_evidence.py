"""Batch lookups over the versioned local herb/component evidence graph."""

from __future__ import annotations

import hashlib
import json
from django.db.models import Q, Subquery

from apps.core.models import EvidenceRelation, KnowledgeEntity
from .catalog_identity import exact_entity_names, exact_entity_queryset, structural_representatives
from .herb_row_support import HerbRowSupport


HERB_COMPOUND_TYPES = {"contains", "herb_compound", "has_compound"}
COMPOUND_TARGET_TYPES = {"targets", "compound_target", "acts_on"}
MAX_MATCHES = 10
MAX_RELATIONS = 1200
MAX_DISEASE_RELATIONS = 1200
DISEASE_TARGET_TYPES = {"disease_target", "disease_herb_target"}
DISEASE_HERB_TYPES = {"disease_herb"}


def _visible_entity_filter(queryset):
    return queryset.filter(Q(source_release__isnull=True) | Q(source_release__source__enabled=True))


def _visible_relations(
    *, relation_types, subject_ids=None, object_ids=None,
    subject_types=None, object_types=None, limit=MAX_RELATIONS,
):
    candidates = EvidenceRelation.objects.filter(
        is_active=True, subject__is_active=True, object__is_active=True,
        source_release__source__enabled=True, relation_type__in=relation_types,
    ).filter(
        (Q(subject__source_release__isnull=True) | Q(subject__source_release__source__enabled=True))
        & (Q(object__source_release__isnull=True) | Q(object__source_release__source__enabled=True))
    )
    if subject_ids is not None:
        candidates = candidates.filter(subject_id__in=subject_ids)
    if object_ids is not None:
        candidates = candidates.filter(object_id__in=object_ids)
    if subject_types is not None:
        candidates = candidates.filter(subject__entity_type__in=subject_types)
    if object_types is not None:
        candidates = candidates.filter(object__entity_type__in=object_types)
    # Sort/filter just the primary keys, then hydrate at most limit+1 rows.
    # Wide entity metadata and source details do not enter the candidate sort.
    ids = structural_representatives(candidates, relation_types=relation_types).order_by("id").values("pk")[:limit + 1]
    queryset = EvidenceRelation.objects.filter(pk__in=Subquery(ids)).select_related(
        "subject", "object", "source_release", "source_release__source",
    ).order_by("id")
    # Entity provenance is used when assembling each unique compound/target.
    # Load it in bounded batches instead of issuing two queries per entity.
    queryset = queryset.prefetch_related(
        "subject__source_release__source", "object__source_release__source",
    )
    records = list(queryset)
    return records[:limit], len(records) > limit


def _entity_record(entity: KnowledgeEntity) -> dict:
    release = entity.source_release
    metadata = entity.metadata if isinstance(entity.metadata, dict) else {}
    return {
        "id": entity.pk,
        "stableId": entity.stable_id,
        "label": entity.label,
        "sourceReleaseId": entity.source_release_id,
        "sourceSlug": release.source.slug if release else None,
        "sourceVersion": release.version if release else None,
        "sourceEntityId": metadata.get("sourceEntityId"),
        "sourceReferences": metadata.get("sourceReferences", []),
        "identifierStatus": metadata.get("identifierStatus"),
        "organism": entity.organism,
    }


def _relation_record(relation: EvidenceRelation) -> dict:
    metadata = relation.metadata if isinstance(relation.metadata, dict) else {}
    record = {
        "id": relation.pk,
        "relationId": relation.pk, "subjectId": relation.subject_id, "objectId": relation.object_id,
        "sourceReleaseId": relation.source_release_id,
        "subject": relation.subject.label,
        "object": relation.object.label,
        "subjectType": relation.subject.entity_type,
        "objectType": relation.object.entity_type,
        "relationType": relation.relation_type,
        "evidenceType": relation.evidence_type,
        "sourceSlug": relation.source_release.source.slug,
        "sourceVersion": relation.source_release.version,
        "sourceRecordId": relation.source_record_id,
        "sourceOrigin": metadata.get("sourceOrigin"),
        "sourceIdentity": metadata.get("sourceIdentity"),
        "score": float(relation.score) if relation.score is not None else None,
    }
    herb_stable_id = metadata.get("herbStableId")
    if relation.relation_type == "disease_herb_target" and isinstance(herb_stable_id, str):
        record["herbStableId"] = herb_stable_id
    return record


def _direct_herb_stable_id(relation: EvidenceRelation) -> str | None:
    metadata = relation.metadata if isinstance(relation.metadata, dict) else {}
    stable_id = metadata.get("herbStableId")
    return stable_id if isinstance(stable_id, str) else None


def _disease_target_relations(target_ids: set[int]) -> tuple[list[EvidenceRelation], bool]:
    if not target_ids:
        return [], False
    candidates = EvidenceRelation.objects.filter(
        is_active=True,
        subject__is_active=True,
        object__is_active=True,
        source_release__source__enabled=True,
        relation_type__in=DISEASE_TARGET_TYPES,
        subject__entity_type=KnowledgeEntity.EntityType.DISEASE,
        object__entity_type__in=[KnowledgeEntity.EntityType.GENE, KnowledgeEntity.EntityType.PROTEIN],
        object_id__in=target_ids,
    ).filter(
        (Q(subject__source_release__isnull=True) | Q(subject__source_release__source__enabled=True))
        & (Q(object__source_release__isnull=True) | Q(object__source_release__source__enabled=True))
    )
    ids = structural_representatives(candidates, relation_types=DISEASE_TARGET_TYPES).order_by("pk").values("pk")[:MAX_DISEASE_RELATIONS + 1]
    rows = list(EvidenceRelation.objects.filter(pk__in=Subquery(ids)).select_related(
        "subject", "subject__source_release", "subject__source_release__source",
        "object", "object__source_release", "object__source_release__source",
        "source_release", "source_release__source",
    ).order_by("pk"))
    return rows[:MAX_DISEASE_RELATIONS], len(rows) > MAX_DISEASE_RELATIONS


def _disease_herb_relations(herb_ids: set[int]) -> tuple[list[EvidenceRelation], bool]:
    if not herb_ids:
        return [], False
    candidates = EvidenceRelation.objects.filter(
        is_active=True,
        subject__is_active=True,
        object__is_active=True,
        source_release__source__enabled=True,
        relation_type__in=DISEASE_HERB_TYPES,
        subject__entity_type=KnowledgeEntity.EntityType.DISEASE,
        object__entity_type=KnowledgeEntity.EntityType.HERB,
        object_id__in=herb_ids,
    ).filter(
        (Q(subject__source_release__isnull=True) | Q(subject__source_release__source__enabled=True))
        & (Q(object__source_release__isnull=True) | Q(object__source_release__source__enabled=True))
    )
    ids = structural_representatives(candidates, relation_types=DISEASE_HERB_TYPES).order_by("pk").values("pk")[:MAX_DISEASE_RELATIONS + 1]
    rows = list(EvidenceRelation.objects.filter(pk__in=Subquery(ids)).select_related(
        "subject", "subject__source_release", "subject__source_release__source",
        "object", "object__source_release", "object__source_release__source",
        "source_release", "source_release__source",
    ).order_by("pk"))
    return rows[:MAX_DISEASE_RELATIONS], len(rows) > MAX_DISEASE_RELATIONS


def batch_herb_component_evidence(*, query_type: str, queries: list[str]) -> dict:
    result_items = []
    for raw_query in queries:
        query = raw_query.strip()
        entity_type = KnowledgeEntity.EntityType.HERB if query_type == "herb" else KnowledgeEntity.EntityType.COMPOUND
        matches = list(
            exact_entity_queryset(entity_type, query).select_related("source_release", "source_release__source").order_by("stable_id")[:MAX_MATCHES + 1]
        )
        matches_truncated = len(matches) > MAX_MATCHES
        matches = matches[:MAX_MATCHES]
        matched_ids = {item.pk for item in matches}

        if query_type == "herb":
            herb_edges, herb_edges_truncated = _visible_relations(
                subject_ids=matched_ids,
                relation_types=HERB_COMPOUND_TYPES,
                object_types=[KnowledgeEntity.EntityType.COMPOUND],
            ) if matched_ids else ([], False)
            compound_ids = {item.object_id for item in herb_edges}
            target_edges, target_edges_truncated = _visible_relations(
                subject_ids=compound_ids,
                relation_types=COMPOUND_TARGET_TYPES,
                object_types=[KnowledgeEntity.EntityType.PROTEIN, KnowledgeEntity.EntityType.GENE],
            ) if compound_ids else ([], False)
            support = HerbRowSupport(herb_edges)
            target_edges = [relation for relation in target_edges if support.for_target(relation)]
            herbs = matches
            compounds = list({item.object_id: item.object for item in herb_edges}.values())
            targets = list({item.object_id: item.object for item in target_edges}.values())
        else:
            herb_edges, herb_edges_truncated = _visible_relations(
                object_ids=matched_ids,
                relation_types=HERB_COMPOUND_TYPES,
                subject_types=[KnowledgeEntity.EntityType.HERB],
            ) if matched_ids else ([], False)
            target_edges, target_edges_truncated = _visible_relations(
                subject_ids=matched_ids,
                relation_types=COMPOUND_TARGET_TYPES,
                object_types=[KnowledgeEntity.EntityType.PROTEIN, KnowledgeEntity.EntityType.GENE],
            ) if matched_ids else ([], False)
            herbs = list({item.subject_id: item.subject for item in herb_edges}.values())
            compounds = matches
            targets = list({item.object_id: item.object for item in target_edges}.values())

        relations = [*herb_edges, *target_edges]
        result_items.append({
            "query": query,
            **({"searchedNames": exact_entity_names(entity_type, query)} if query_type == "compound" else {}),
            "matches": [_entity_record(item) for item in matches],
            "ambiguous": len(matches) > 1,
            "herbs": [_entity_record(item) for item in sorted(herbs, key=lambda item: item.label.casefold())],
            "compounds": [_entity_record(item) for item in sorted(compounds, key=lambda item: item.label.casefold())],
            "targets": [_entity_record(item) for item in sorted(targets, key=lambda item: item.label.casefold())],
            "relations": [_relation_record(item) for item in relations],
            "truncated": matches_truncated or herb_edges_truncated or target_edges_truncated,
        })

    # Extend the searched herb/compound chain through the same registered
    # target entities to diseases with source-backed disease-target evidence.
    all_target_ids = {entity["id"] for item in result_items for entity in item["targets"]}
    disease_relations, disease_relations_truncated = _disease_target_relations(all_target_ids)
    all_herb_ids = {entity["id"] for item in result_items for entity in item["herbs"]}
    disease_herb_relations, disease_herb_relations_truncated = _disease_herb_relations(all_herb_ids)
    direct_herb_stable_ids = {
        stable_id for relation in disease_relations
        if relation.relation_type == "disease_herb_target"
        for stable_id in [_direct_herb_stable_id(relation)] if stable_id
    }
    direct_herbs = {
        entity.stable_id: entity for entity in KnowledgeEntity.objects.filter(
            entity_type=KnowledgeEntity.EntityType.HERB,
            stable_id__in=direct_herb_stable_ids,
            is_active=True,
        ).filter(Q(source_release__isnull=True) | Q(source_release__source__enabled=True)).select_related(
            "source_release", "source_release__source",
        )
    } if direct_herb_stable_ids else {}
    disease_relations_by_target: dict[int, list[EvidenceRelation]] = {}
    for relation in disease_relations:
        disease_relations_by_target.setdefault(relation.object_id, []).append(relation)
    for item in result_items:
        target_ids = {entity["id"] for entity in item["targets"]}
        herb_ids = {entity["id"] for entity in item["herbs"]}
        rows = [relation for target_id in sorted(target_ids) for relation in disease_relations_by_target.get(target_id, [])]
        rows.extend(relation for relation in disease_herb_relations if relation.object_id in herb_ids)
        rows.sort(key=lambda relation: relation.pk)
        disease_entities = {relation.subject_id: relation.subject for relation in rows}
        herb_entities = {
            direct_herbs[stable_id].pk: direct_herbs[stable_id]
            for relation in rows
            for stable_id in [_direct_herb_stable_id(relation)]
            if relation.relation_type == "disease_herb_target" and stable_id in direct_herbs
        }
        item["diseases"] = [_entity_record(entity) for entity in sorted(disease_entities.values(), key=lambda entity: (entity.label.casefold(), entity.stable_id))]
        item["diseaseHerbs"] = [_entity_record(entity) for entity in sorted(herb_entities.values(), key=lambda entity: (entity.label.casefold(), entity.stable_id))]
        item["diseaseRelations"] = [_relation_record(relation) for relation in rows]
        item["diseaseRelationsTruncated"] = disease_relations_truncated or disease_herb_relations_truncated

    from .data_quality import data_quality_notices
    result = {"queryType": query_type, "results": result_items, "dataQuality": data_quality_notices()}
    canonical = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {**result, "resultSha256": hashlib.sha256(canonical.encode()).hexdigest()}
