"""Bounded, read-only disease evidence lookups over the local knowledge graph."""

from __future__ import annotations

from django.db.models import Q

from apps.core.models import EvidenceRelation, KnowledgeEntity
from .catalog_identity import exact_entity_queryset, structural_representatives
from .disease_resolution import EXACT_ALIASES, exact_disease_terms


MAX_MATCHES = 20
MAX_RELATIONS = 1200

DISEASE_HERB_TYPE = "disease_herb"
DISEASE_TARGET_TYPES = {"disease_target", "disease_herb_target"}
TARGET_ENTITY_TYPES = [KnowledgeEntity.EntityType.GENE, KnowledgeEntity.EntityType.PROTEIN]


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
        "relationId": relation.pk, "subjectId": relation.subject_id, "objectId": relation.object_id,
        "sourceReleaseId": relation.source_release_id,
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


def _visible_relations(disease_ids: set[int]):
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

    queryset = structural_representatives(queryset)
    herb_relations = queryset.filter(
        relation_type=DISEASE_HERB_TYPE,
        object__entity_type=KnowledgeEntity.EntityType.HERB,
    )
    target_relations = queryset.filter(
        relation_type__in=DISEASE_TARGET_TYPES,
        object__entity_type__in=TARGET_ENTITY_TYPES,
    )
    direct_target_relations = target_relations.filter(relation_type="disease_target")
    triple_target_relations = target_relations.filter(relation_type="disease_herb_target")

    herb_ids = set(herb_relations.order_by().values_list("object_id", flat=True).distinct())
    target_ids = set(target_relations.order_by().values_list("object_id", flat=True).distinct())
    direct_herb_stable_ids = {
        metadata.get("herbStableId")
        for metadata in triple_target_relations.order_by().values_list("metadata", flat=True)
        if isinstance(metadata, dict) and isinstance(metadata.get("herbStableId"), str)
        and metadata.get("herbStableId")
    }

    counts = {
        "disease_target": direct_target_relations.count(),
        "disease_herb_target": triple_target_relations.count(),
        DISEASE_HERB_TYPE: herb_relations.count(),
    }
    total_count = sum(counts.values())

    # Reserve display rows for each evidence layer. The old global alphabetical
    # ordering let thousands of disease→herb edges consume the entire page
    # before any disease→target evidence could be shown.
    target_total = counts["disease_target"] + counts["disease_herb_target"]
    target_budget = min(target_total, max(1, int(MAX_RELATIONS * 0.75))) if target_total else 0
    direct_budget = min(counts["disease_target"], (target_budget + 1) // 2)
    triple_budget = min(counts["disease_herb_target"], target_budget - direct_budget)
    selected = {
        "disease_target": direct_budget,
        "disease_herb_target": triple_budget,
        DISEASE_HERB_TYPE: min(counts[DISEASE_HERB_TYPE], MAX_RELATIONS - target_budget),
    }
    target_remaining = target_budget - direct_budget - triple_budget
    for kind in ("disease_target", "disease_herb_target"):
        extra = min(target_remaining, counts[kind] - selected[kind])
        selected[kind] += extra
        target_remaining -= extra
    remaining = MAX_RELATIONS - sum(selected.values())
    for kind in ("disease_target", "disease_herb_target", DISEASE_HERB_TYPE):
        extra = min(remaining, counts[kind] - selected[kind])
        selected[kind] += extra
        remaining -= extra

    ordering = (
        "subject__label", "subject__stable_id", "object__label", "object__stable_id",
        "source_release__source__slug", "source_release__version", "source_record_id", "id",
    )
    relation_groups = {
        "disease_target": direct_target_relations,
        "disease_herb_target": triple_target_relations,
        DISEASE_HERB_TYPE: herb_relations,
    }
    records = []
    for kind in ("disease_target", "disease_herb_target", DISEASE_HERB_TYPE):
        if selected[kind]:
            records.extend(list(relation_groups[kind].order_by(*ordering)[:selected[kind]]))
    return records, total_count > MAX_RELATIONS, herb_ids, target_ids, direct_herb_stable_ids, total_count


def _direct_herb_stable_id(relation: EvidenceRelation) -> str | None:
    metadata = relation.metadata
    if not isinstance(metadata, dict):
        return None
    stable_id = metadata.get("herbStableId")
    if not isinstance(stable_id, str) or not stable_id:
        return None
    return stable_id


def _visible_herbs_by_stable_id(stable_ids: set[str]) -> dict[str, KnowledgeEntity]:
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


def search_disease_evidence(query: str) -> dict:
    query = str(query or "").strip()
    expanded_queries = exact_disease_terms(query)

    # Reuse the intersection resolver's exact label/source-observation lookup.
    # This keeps disease evidence and network pharmacology on the same scope,
    # without silently widening a disease to its subtypes by substring match.
    matching_by_id = {}
    for term in expanded_queries:
        for entity in exact_entity_queryset("disease", term).select_related(
            "source_release", "source_release__source",
        ).order_by("stable_id").iterator(chunk_size=MAX_MATCHES + 1):
            matching_by_id.setdefault(entity.pk, entity)
            if len(matching_by_id) > MAX_MATCHES:
                break
        if len(matching_by_id) > MAX_MATCHES:
            break
    matching_records = sorted(
        matching_by_id.values(), key=lambda entity: (entity.label.casefold(), entity.stable_id.casefold(), entity.pk)
    )
    matches_truncated = len(matching_records) > MAX_MATCHES
    matches = matching_records[:MAX_MATCHES]

    relations, relations_truncated, herb_ids, target_ids, direct_herb_stable_ids, total_relations = (
        _visible_relations({entity.pk for entity in matches})
        if matches else ([], False, set(), set(), set(), 0)
    )
    direct_herbs = _visible_herbs_by_stable_id(direct_herb_stable_ids)

    herbs_by_id: dict[int, KnowledgeEntity] = {
        entity.pk: entity for entity in KnowledgeEntity.objects.filter(
            pk__in=herb_ids, is_active=True,
        ).filter(Q(source_release__isnull=True) | Q(source_release__source__enabled=True)).select_related(
            "source_release", "source_release__source",
        )
    }
    herbs_by_id.update({entity.pk: entity for entity in direct_herbs.values()})
    targets_by_id: dict[int, KnowledgeEntity] = {
        entity.pk: entity for entity in KnowledgeEntity.objects.filter(
            pk__in=target_ids, is_active=True,
        ).filter(Q(source_release__isnull=True) | Q(source_release__source__enabled=True)).select_related(
            "source_release", "source_release__source",
        )
    }
    links = []
    for relation in relations:
        herb_label = ""
        target_label = ""
        herb_id = None
        if relation.relation_type == DISEASE_HERB_TYPE:
            herb_label = relation.object.label
            herb_id = relation.object_id
        else:
            target_label = relation.object.label
            if relation.relation_type == "disease_herb_target":
                stable_id = _direct_herb_stable_id(relation)
                herb = direct_herbs.get(stable_id) if stable_id is not None else None
                if herb is not None:
                    herbs_by_id[herb.pk] = herb
                    herb_label = herb.label
                    herb_id = herb.pk

        links.append({
            "diseaseId": relation.subject_id,
            "herbId": herb_id,
            "targetId": relation.object_id if target_label else None,
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
    from .data_quality import data_quality_notices
    return {
        "dataQuality": data_quality_notices(),
        "query": query,
        "expandedQueries": expanded_queries,
        "aliasSource": EXACT_ALIASES["source"].rsplit(" @ ", 1)[0],
        "aliasSourceCommit": EXACT_ALIASES["source"].rsplit("@ ", 1)[-1],
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
            "links": total_relations,
            "relations": total_relations,
        },
        "truncated": truncated,
        "limits": {
            "maxMatches": MAX_MATCHES,
            "maxRelations": MAX_RELATIONS,
            "returnedRelations": len(relations),
        },
    }
