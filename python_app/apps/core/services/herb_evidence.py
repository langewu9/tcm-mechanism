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
    return {
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

    from .data_quality import data_quality_notices
    result = {"queryType": query_type, "results": result_items, "dataQuality": data_quality_notices()}
    canonical = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {**result, "resultSha256": hashlib.sha256(canonical.encode()).hexdigest()}
