"""Evidence-backed herb/disease target intersection over the local catalogue."""

from __future__ import annotations

import re
import hashlib
import unicodedata
from collections import defaultdict

from django.db import transaction
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Q, Value, When, Subquery
from django.utils import timezone

from apps.core.models import AnalysisTask, EvidenceRelation, KnowledgeEntity, MedicalCase, MedicalCaseCandidate
from .catalog_identity import exact_entity_queryset, structural_representatives
from .disease_resolution import resolve_intersection_disease
from .target_identity import compare_target_identities, input_profiles, verified_target_node_identities
from .data_quality import data_quality_notices
from .herb_row_support import HerbRowSupport


INPUT_SPLIT = re.compile(r"[,，、;；|/\n\r]+")
HERB_COMPOUND_TYPES = {"contains", "herb_compound", "has_compound"}
DISEASE_HERB_TYPES = {"disease_herb"}
FORMULA_HERB_TYPES = {"contains", "contains_herb", "formula_herb", "has_herb", "composed_of"}
COMPOUND_TARGET_TYPES = {"targets", "compound_target", "acts_on"}
DISEASE_TARGET_TYPES = {"disease_target", "disease_herb_target"}
PATHWAY_TYPES = {
    "genepathway", "gene_pathway", "proteinpathway", "protein_pathway", "targetpathway", "target_pathway",
    "participatesin", "participates_in", "annotatedtopathway", "annotated_to_pathway",
    "associatedwithpathway", "associated_with_pathway",
}
STATISTICS_VERSION = "main-455a309-reviewed-disease-targets-v1"
RAW_EVIDENCE_VERSION = "network-raw-evidence-v2"
DISEASE_TARGET_ANALYSIS_SCOPE = "reviewed_direct_disease_targets_v1"
# This aggregate workbook currently has no independent disease-association
# provenance for its rows; herb-specific rows and the parallel disease-herb
# triples are retained as source candidates, not promoted to a disease target set.
UNREVIEWED_DISEASE_TARGET_SOURCES = {"disease-targets"}
RAW_EXPORT_LIMIT = 4000
CANDIDATE_EVIDENCE_LIMIT = 50000
NETWORK_NODE_LIMIT = 2000
NETWORK_EDGE_LIMIT = 4000
NETWORK_NODE_GROUP_LIMITS = {
    'herb': 250, 'disease': 100, 'compound': 650, 'target': 900, 'pathway': 100,
}
NETWORK_EDGE_GROUP_LIMITS = {
    'formula_herb': 100, 'disease_herb': 300, 'herb_compound': 900,
    'disease_target': 1050, 'compound_target': 1250, 'target_pathway': 200, 'other': 200,
}


class NetworkPharmacologyInputError(ValueError):
    """A source candidate or case changed before a linked analysis could be saved."""


def _network_node_group(node_type):
    if node_type in {'herb', 'formula', 'drug', 'medicine'}: return 'herb'
    if node_type == 'disease': return 'disease'
    if node_type in {'compound', 'ingredient'}: return 'compound'
    if node_type in {'target', 'gene', 'protein'}: return 'target'
    if node_type == 'pathway': return 'pathway'
    return node_type


def _network_edge_group(edge, nodes):
    raw_pair = frozenset((nodes[edge['source']]['type'], nodes[edge['target']]['type']))
    if raw_pair == frozenset(('formula', 'herb')): return 'formula_herb'
    left = _network_node_group(nodes[edge['source']]['type'])
    right = _network_node_group(nodes[edge['target']]['type'])
    pair = frozenset((left, right))
    if pair == frozenset(('herb', 'compound')): return 'herb_compound'
    if pair == frozenset(('compound', 'target')): return 'compound_target'
    if pair == frozenset(('disease', 'target')): return 'disease_target'
    if pair == frozenset(('disease', 'herb')): return 'disease_herb'
    if pair == frozenset(('target', 'pathway')): return 'target_pathway'
    return 'other'


def _bounded_network(nodes, links, focus_ids):
    """Keep all major evidence layers visible within the persisted graph limits."""
    adjacency = {key: set() for key in nodes}
    for edge in links:
        if edge['source'] in nodes and edge['target'] in nodes:
            adjacency[edge['source']].add(edge['target'])
            adjacency[edge['target']].add(edge['source'])

    def node_rank(key):
        node = nodes[key]
        return (not node.get('targetOverlap', False), -len(adjacency[key]), node['label'].casefold(), key)

    group_keys = {}
    for key, node in nodes.items():
        group_keys.setdefault(_network_node_group(node['type']), []).append(key)
    for keys in group_keys.values():
        keys.sort(key=node_rank)

    selected, selected_set = [], set()
    group_counts = {}
    node_limits = dict(NETWORK_NODE_GROUP_LIMITS)

    def add_node(key):
        if key not in nodes or key in selected_set or len(selected) >= NETWORK_NODE_LIMIT:
            return
        group = _network_node_group(nodes[key]['type'])
        limit = node_limits.get(group, NETWORK_NODE_LIMIT)
        if group_counts.get(group, 0) >= limit:
            return
        selected.append(key)
        selected_set.add(key)
        group_counts[group] = group_counts.get(group, 0) + 1

    for key in sorted((key for key in focus_ids if key in nodes), key=node_rank):
        add_node(key)
    for group in ('disease', 'herb', 'target', 'compound', 'pathway'):
        for key in group_keys.get(group, []):
            add_node(key)
    if len(selected) < NETWORK_NODE_LIMIT:
        for key in sorted((key for key in nodes if key not in selected_set), key=node_rank):
            if len(selected) >= NETWORK_NODE_LIMIT:
                break
            group = _network_node_group(nodes[key]['type'])
            # Initial quotas reserve space for every network layer. Any remaining
            # capacity is then available to whichever groups still have evidence.
            node_limits[group] = NETWORK_NODE_LIMIT
            add_node(key)

    shown_nodes = {key: nodes[key] for key in selected}
    buckets = {key: [] for key in NETWORK_EDGE_GROUP_LIMITS}
    for edge in links:
        if edge['source'] not in selected_set or edge['target'] not in selected_set:
            continue
        group = _network_edge_group(edge, nodes)
        buckets[group].append(edge)
    for name, edges in buckets.items():
        edges.sort(key=lambda edge: (
            not any(nodes[key].get('targetOverlap', False) for key in (edge['source'], edge['target'])),
            edge.get('sourceSlug', ''), edge.get('sourceRecordId', ''), edge['source'], edge['target'],
        ))

    selected_edges, selected_edge_ids = [], set()
    for group, limit in NETWORK_EDGE_GROUP_LIMITS.items():
        group_count = 0
        for edge in buckets[group]:
            if group_count >= limit or len(selected_edges) >= NETWORK_EDGE_LIMIT:
                break
            identity = (edge['source'], edge['target'], edge.get('relation'), edge.get('sourceSlug'), edge.get('sourceRecordId'))
            if identity in selected_edge_ids:
                continue
            selected_edge_ids.add(identity)
            selected_edges.append(edge)
            group_count += 1
    return list(shown_nodes.values()), selected_edges


def parse_herb_names(value: str) -> list[str]:
    return list(dict.fromkeys(part.strip() for part in INPUT_SPLIT.split(value) if part.strip()))


def _entity_matches(entity_type: str, labels: list[str]) -> tuple[list[KnowledgeEntity], set[str]]:
    matches = []
    matched_labels = set()
    for label in labels:
        exact = list(exact_entity_queryset(entity_type, label).order_by("stable_id")[:10])
        if exact:
            matches.extend(exact)
            matched_labels.add(label)
        # Deliberately require an exact label. Substring matching can turn a
        # partial disease/herb name into a misleading mechanistic result.
    unique = {entity.pk: entity for entity in matches}
    return list(unique.values()), matched_labels


def _evidence_record(relation: EvidenceRelation) -> dict:
    release = relation.source_release
    return {
        "source": release.source.name,
        "sourceSlug": release.source.slug,
        "sourceVersion": release.version,
        "evidenceType": relation.evidence_type,
        "sourceRecordId": relation.source_record_id,
        "relationType": relation.relation_type,
        "score": float(relation.score) if relation.score is not None else None,
    }


def _reviewed_disease_target_rows(rows):
    """Keep direct disease-target assertions whose association source was reviewed.

    The imported combined_results.xlsx release is an aggregate candidate table:
    its pulmonary-fibrosis rows contain thousands of targets with blank origin,
    while the remaining rows point to herb workbooks. Keep those rows available
    for provenance review, but do not treat them as independent disease evidence.
    A release can opt in after review by setting diseaseAssociationReviewed=true.
    """
    return rows.filter(relation_type="disease_target").exclude(
        Q(source_release__source__slug__in=UNREVIEWED_DISEASE_TARGET_SOURCES)
        & ~Q(source_release__metadata__diseaseAssociationReviewed=True)
    )


def _complete_identity_inputs(herb_ids, disease_ids, formula_ids, selected_herb_stable_ids=()):
    """Project distinct target identities before raw-row/graph display limits.

    Repeated older workbook rows must not hide a newer source's targets.
    This projection does not claim that every target identifier is verified.
    """
    visible = EvidenceRelation.objects.filter(is_active=True, subject__is_active=True,
        object__is_active=True, source_release__source__enabled=True).filter(
        Q(subject__source_release__isnull=True) | Q(subject__source_release__source__enabled=True)).filter(
        Q(object__source_release__isnull=True) | Q(object__source_release__source__enabled=True))
    formula_rows = visible.filter(subject_id__in=formula_ids, relation_type__in=FORMULA_HERB_TYPES,
        object__entity_type='herb')
    all_herbs = set(herb_ids) | set(formula_rows.order_by().values_list('object_id', flat=True).distinct())
    herb_rows = visible.filter(subject_id__in=all_herbs, relation_type__in=HERB_COMPOUND_TYPES,
        object__entity_type='compound')
    compound_ids = herb_rows.order_by().values('object_id').distinct()
    target_rows = visible.filter(subject_id__in=Subquery(compound_ids), relation_type__in=COMPOUND_TARGET_TYPES,
        object__entity_type__in=['gene', 'protein'])
    matching_herb_row = herb_rows.filter(
        source_release_id=OuterRef('source_release_id'),
        object_id=OuterRef('subject_id'),
        metadata__sourceRowId=OuterRef('metadata__sourceRowId'),
    ).exclude(metadata__sourceRowId__isnull=True)
    target_rows = target_rows.annotate(
        _matching_legacy_herb_row=Exists(matching_herb_row),
    ).filter(
        ~Q(source_release__metadata__connector='sqlite-herb-compound-target')
        | (Q(metadata__sourceRowId__isnull=False) & Q(_matching_legacy_herb_row=True))
    )
    disease_rows = visible.filter(subject_id__in=disease_ids, relation_type__in=DISEASE_TARGET_TYPES,
        object__entity_type__in=['gene', 'protein'])
    reviewed_disease_rows = _reviewed_disease_target_rows(disease_rows)
    herb_targets = set(target_rows.order_by().values_list('object_id', flat=True).distinct())
    disease_targets = set(reviewed_disease_rows.order_by().values_list('object_id', flat=True).distinct())
    direct_rows = disease_rows.filter(
        relation_type='disease_herb_target', metadata__herbStableId__in=selected_herb_stable_ids,
    ) if selected_herb_stable_ids else disease_rows.none()
    direct_target_ids = set(direct_rows.order_by().values_list('object_id', flat=True).distinct())
    all_source_target_ids = set(disease_rows.order_by().values_list('object_id', flat=True).distinct())
    target_profiles = input_profiles(herb_targets | disease_targets | direct_target_ids)
    releases = set()
    for rows in [formula_rows, herb_rows, target_rows, disease_rows]:
        releases.update(rows.order_by().values_list('source_release_id', flat=True).distinct())
    identity = compare_target_identities(herb_targets, disease_targets, profiles=target_profiles)
    entity_overlap = herb_targets & disease_targets
    source_breakdown = []
    for row in disease_rows.order_by().values(
        'source_release_id', 'source_release__source__slug', 'source_release__version',
        'source_release__metadata', 'relation_type',
    ).annotate(entity_count=Count('object_id', distinct=True), relation_count=Count('id')).order_by(
        'source_release__source__slug', 'source_release__version', 'relation_type',
    ):
        source_slug = row['source_release__source__slug']
        relation_type = row['relation_type']
        release_metadata = row['source_release__metadata'] or {}
        is_reviewed_direct = relation_type == 'disease_target' and (
            source_slug not in UNREVIEWED_DISEASE_TARGET_SOURCES
            or release_metadata.get('diseaseAssociationReviewed') is True
        )
        source_breakdown.append({
            'sourceSlug': source_slug,
            'sourceVersion': row['source_release__version'],
            'relationType': relation_type,
            'entityCount': row['entity_count'],
            'relationCount': row['relation_count'],
            'scope': 'analysis' if is_reviewed_direct else 'candidate',
        })
    identity['entityIdComparison'] = {
        'herbTargetCount': len(herb_targets),
        'diseaseTargetCount': len(disease_targets),
        'intersectionCount': len(entity_overlap),
        'intersectionEntities': list(KnowledgeEntity.objects.filter(pk__in=sorted(entity_overlap)[:100])
            .order_by('pk').values('id', 'label', 'entity_type', 'stable_id')[:100]),
        'rowsTruncated': len(entity_overlap) > 100,
        'scope': DISEASE_TARGET_ANALYSIS_SCOPE,
    }
    identity['diseaseTargetEvidence'] = {
        'scope': DISEASE_TARGET_ANALYSIS_SCOPE,
        'confirmedRelationCount': reviewed_disease_rows.count(),
        'confirmedEntityCount': len(disease_targets),
        'candidateRelationCount': disease_rows.count() - reviewed_disease_rows.count(),
        'candidateEntityCount': len(all_source_target_ids - disease_targets),
        'candidateSources': source_breakdown,
        'policy': 'Only reviewed direct disease-target relations enter disease-side intersections. Aggregate workbook rows pending disease-association provenance and herb-context triples remain source candidates.',
    }
    identity['comparisonVersion'] = 'target-identity-comparison-v4'
    identity['coverage'] = {'scope': DISEASE_TARGET_ANALYSIS_SCOPE, 'rawRowLimitsApplied': False}
    return identity, releases, herb_targets, disease_targets, direct_target_ids, target_profiles


def _relation_query(*, subject_ids=None, object_ids=None, relation_types, limit, preferred_herb_ids=None,
                    reviewed_disease_only=False):
    queryset = EvidenceRelation.objects.filter(
        is_active=True,
        subject__is_active=True,
        object__is_active=True,
        source_release__source__enabled=True,
        relation_type__in=relation_types,
    ).filter(
        (Q(subject__source_release__isnull=True) | Q(subject__source_release__source__enabled=True))
        & (Q(object__source_release__isnull=True) | Q(object__source_release__source__enabled=True))
    ).select_related("subject", "object", "source_release", "source_release__source")
    if subject_ids is not None:
        queryset = queryset.filter(subject_id__in=subject_ids)
    if object_ids is not None:
        queryset = queryset.filter(object_id__in=object_ids)
    if reviewed_disease_only:
        queryset = _reviewed_disease_target_rows(queryset)
    queryset = structural_representatives(queryset, relation_types=relation_types)
    if preferred_herb_ids:
        # Read selected-herb triples before a large disease's other-herb rows
        # exhaust the bounded query. Other evidence remains bounded/reported.
        queryset = queryset.annotate(selected_context_order=Case(When(
            relation_type="disease_herb_target", metadata__herbStableId__in=preferred_herb_ids,
            source_release__source__configuration__connector="local-workbooks-master",
            then=Value(0)), default=Value(1), output_field=IntegerField()))
        return list(queryset.order_by("selected_context_order", "id")[:limit])
    return list(queryset.order_by("id")[:limit])


def _raw_relation_record(relation: EvidenceRelation, prefix: str = "") -> dict:
    record = {
        **_evidence_record(relation),
        "relationId": relation.pk,
        "sourceReleaseId": relation.source_release_id,
        "sourceChecksumSha256": relation.source_release.checksum_sha256,
    }
    if not prefix:
        return record
    return {f"{prefix}{key[0].upper()}{key[1:]}": value for key, value in record.items()}


def _raw_side_evidence(herb_relations, target_relations, disease_relations, *, herbs_by_stable_id, limit):
    """Project read catalogue edges, including evidence outside the candidate set.

    A herb row is a pair of real edges, so both source records are retained.
    The join stops after one sentinel row instead of materializing a Cartesian product.
    """
    support = HerbRowSupport(herb_relations)
    herb_rows = []
    herb_truncated = False
    for target_relation in target_relations:
        for herb_relation in support.for_target(target_relation):
            if len(herb_rows) == limit:
                herb_truncated = True
                break
            herb_rows.append({
                "herb": herb_relation.subject.label,
                "herbStableId": herb_relation.subject.stable_id,
                "component": target_relation.subject.label,
                "componentStableId": target_relation.subject.stable_id,
                "target": target_relation.object.label,
                "targetStableId": target_relation.object.stable_id,
                **_raw_relation_record(target_relation),
                **_raw_relation_record(herb_relation, "herb"),
            })
        if herb_truncated:
            break
    disease_rows, triple_rows, direct_rows = [], [], []
    selected_herb_ids = set(herbs_by_stable_id)
    # Unselected herbs in disease-side triples are resolved only by active,
    # canonical IDs. Display-only herbLabel metadata never establishes identity.
    triple_herb_ids = {
        (relation.metadata or {}).get("herbStableId") for relation in disease_relations
        if relation.relation_type == "disease_herb_target"
        and isinstance((relation.metadata or {}).get("herbStableId"), str)
    }
    canonical_herbs = dict(KnowledgeEntity.objects.filter(
        entity_type=KnowledgeEntity.EntityType.HERB, stable_id__in=triple_herb_ids, is_active=True,
    ).filter(
        Q(source_release__isnull=True) | Q(source_release__source__enabled=True)
    ).values_list("stable_id", "label")) if triple_herb_ids else {}
    for relation in disease_relations:
        row = {
            "disease": relation.subject.label,
            "diseaseStableId": relation.subject.stable_id,
            "target": relation.object.label,
            "targetStableId": relation.object.stable_id,
            **_raw_relation_record(relation),
        }
        if relation.relation_type == "disease_target":
            if len(disease_rows) <= limit:
                disease_rows.append(row)
            continue
        herb_id = (relation.metadata or {}).get("herbStableId")
        herb_id = herb_id if isinstance(herb_id, str) else ""
        row.update({
            "herbStableId": herb_id,
            "herb": canonical_herbs.get(herb_id, ""),
            "herbIdentityStatus": "resolved" if herb_id in canonical_herbs else "unresolved",
        })
        if len(triple_rows) <= limit:
            triple_rows.append(row)
        if herb_id in selected_herb_ids and len(direct_rows) <= limit:
            direct_rows.append(row)
    return {
        "herbLinks": herb_rows,
        "diseaseTargets": disease_rows[:limit],
        "diseaseHerbLinks": triple_rows[:limit],
        "directDiseaseHerbLinks": direct_rows[:limit],
    }, {
        "herbLinks": herb_truncated,
        "diseaseTargets": len(disease_rows) > limit,
        "diseaseHerbLinks": len(triple_rows) > limit,
        "directDiseaseHerbLinks": len(direct_rows) > limit,
    }


def build_network_pharmacology(
    *, user, herb_query: str, disease_query: str, row_limit: int = 12000,
    source_case_candidate: MedicalCaseCandidate | None = None,
    persist: bool = True,
) -> dict:
    relation_limits = {}

    def read_relations(stage, limit_override=None, **kwargs):
        effective_limit = limit_override or row_limit
        rows = _relation_query(**kwargs, limit=effective_limit + 1)
        relation_limits[stage] = len(rows) > effective_limit
        return rows[:effective_limit]

    requested_names = parse_herb_names(herb_query)
    requested_herbs, matched_herb_names = _entity_matches(KnowledgeEntity.EntityType.HERB, requested_names)
    if source_case_candidate:
        formulas = [source_case_candidate.entity] if source_case_candidate.entity_id else []
        matched_formula_names = {
            name for name in requested_names
            if source_case_candidate.entity and name.casefold() == source_case_candidate.entity.label.casefold()
        }
    else:
        formulas, matched_formula_names = _entity_matches(KnowledgeEntity.EntityType.FORMULA, requested_names)
    if source_case_candidate and source_case_candidate.entity_id not in {item.pk for item in formulas}:
        raise NetworkPharmacologyInputError("已确认方剂未包含在本次查询中，或其来源记录当前不可用。")
    formula_herb_relations = read_relations(
        "formulaHerbs",
        subject_ids={item.pk for item in formulas},
        relation_types=FORMULA_HERB_TYPES,
    ) if formulas else []
    formula_herb_relations = [
        relation for relation in formula_herb_relations
        if relation.object.entity_type == KnowledgeEntity.EntityType.HERB
    ]
    formula_herbs = [
        relation.object for relation in formula_herb_relations
    ]
    herbs_by_id = {item.pk: item for item in [*requested_herbs, *formula_herbs]}
    herbs = list(herbs_by_id.values())
    herb_names = [item.label for item in herbs]
    diseases, disease_resolution = resolve_intersection_disease(disease_query)
    herb_ids = {item.pk for item in herbs}
    disease_ids = {item.pk for item in diseases}
    selected_herbs_by_stable_id = {item.stable_id: item.label for item in herbs}
    (complete_identity, identity_sources, all_herb_target_ids, all_disease_target_ids,
     all_direct_target_ids, target_profiles) = (
        _complete_identity_inputs(
            herb_ids, disease_ids, {item.pk for item in formulas},
            selected_herb_stable_ids=set(selected_herbs_by_stable_id),
        )
    )
    target_node_identities = verified_target_node_identities(
        all_herb_target_ids | all_disease_target_ids | all_direct_target_ids, profiles=target_profiles,
    )

    def target_identity_key(entity_id):
        identity = target_node_identities.get(entity_id)
        return identity["key"] if identity else f"source-entity:{entity_id}"

    herb_entities_by_identity: dict[str, set[int]] = defaultdict(set)
    disease_entities_by_identity: dict[str, set[int]] = defaultdict(set)
    for entity_id in all_herb_target_ids:
        herb_entities_by_identity[target_identity_key(entity_id)].add(entity_id)
    for entity_id in all_disease_target_ids:
        disease_entities_by_identity[target_identity_key(entity_id)].add(entity_id)
    strict_identity_keys = set(herb_entities_by_identity) & set(disease_entities_by_identity)
    direct_identity_keys = {target_identity_key(entity_id) for entity_id in all_direct_target_ids}
    candidate_identity_keys = strict_identity_keys | direct_identity_keys
    entities_by_identity: dict[str, set[int]] = defaultdict(set)
    for entity_id in all_herb_target_ids | all_disease_target_ids | all_direct_target_ids:
        identity_key = target_identity_key(entity_id)
        if identity_key in candidate_identity_keys:
            entities_by_identity[identity_key].add(entity_id)
    target_entity_ids_for_candidates = set().union(*entities_by_identity.values()) if entities_by_identity else set()

    herb_compound_relations = read_relations(
        "herbCompounds", subject_ids=herb_ids, relation_types=HERB_COMPOUND_TYPES,
    ) if herbs else []
    compound_ids = {item.object_id for item in herb_compound_relations}
    compound_target_relations = read_relations(
        "compoundTargets", subject_ids=compound_ids, relation_types=COMPOUND_TARGET_TYPES,
    ) if compound_ids else []
    support = HerbRowSupport(herb_compound_relations)
    compound_target_relations = [relation for relation in compound_target_relations if support.for_target(relation)]
    disease_target_relations = read_relations(
        "diseaseTargets", subject_ids=disease_ids, relation_types={"disease_target"},
        reviewed_disease_only=True,
    ) if diseases else []
    raw_disease_target_limit = min(row_limit, RAW_EXPORT_LIMIT)
    raw_disease_target_relations = _relation_query(
        subject_ids=disease_ids, relation_types=DISEASE_TARGET_TYPES,
        preferred_herb_ids=list(selected_herbs_by_stable_id),
        limit=raw_disease_target_limit + 1,
    ) if diseases else []
    relation_limits['diseaseTargets'] = relation_limits.get('diseaseTargets', False) or (
        len(raw_disease_target_relations) > raw_disease_target_limit
    )
    disease_herb_relations = read_relations(
        "diseaseHerbs", subject_ids=disease_ids, object_ids=herb_ids, relation_types=DISEASE_HERB_TYPES,
    ) if diseases and herbs else []

    candidate_compound_target_relations = read_relations(
        "candidateCompoundTargets", limit_override=CANDIDATE_EVIDENCE_LIMIT,
        object_ids=target_entity_ids_for_candidates, relation_types=COMPOUND_TARGET_TYPES,
    ) if target_entity_ids_for_candidates else []
    candidate_compound_ids = {relation.subject_id for relation in candidate_compound_target_relations}
    candidate_herb_compound_relations = read_relations(
        "candidateHerbCompounds", limit_override=CANDIDATE_EVIDENCE_LIMIT,
        subject_ids=herb_ids, object_ids=candidate_compound_ids, relation_types=HERB_COMPOUND_TYPES,
    ) if candidate_compound_ids and herbs else []
    candidate_support = HerbRowSupport(candidate_herb_compound_relations)
    candidate_compound_target_relations = [
        relation for relation in candidate_compound_target_relations
        if candidate_support.for_target(relation)
    ]
    candidate_disease_target_relations = read_relations(
        "candidateDiseaseTargets", limit_override=CANDIDATE_EVIDENCE_LIMIT,
        subject_ids=disease_ids, object_ids=target_entity_ids_for_candidates,
        relation_types=DISEASE_TARGET_TYPES,
        preferred_herb_ids=list(selected_herbs_by_stable_id),
    ) if target_entity_ids_for_candidates and diseases else []

    compound_by_id = {
        relation.object_id: relation.object for relation in candidate_herb_compound_relations
    }
    compound_target_counts: dict[int, set[int]] = defaultdict(set)
    herb_evidence: dict[int, dict] = defaultdict(lambda: {
        "herbs": set(), "compounds": set(), "sources": [], "count": 0,
    })
    source_releases = set(identity_sources)
    source_releases.update(relation.source_release_id for relation in formula_herb_relations)
    source_releases.update(relation.source_release_id for relation in disease_herb_relations)
    source_releases.update(relation.source_release_id for relation in herb_compound_relations)
    source_releases.update(relation.source_release_id for relation in candidate_herb_compound_relations)
    for relation in candidate_compound_target_relations:
        compound_target_counts[relation.subject_id].add(relation.object_id)
        evidence = herb_evidence[relation.object_id]
        compound_support = candidate_support.for_target(relation)
        evidence["count"] += 1
        evidence["compounds"].add(relation.subject.label)
        evidence["herbs"].update(item.subject.label for item in compound_support)
        evidence["sources"].extend(_evidence_record(item) for item in compound_support)
        evidence["sources"].append(_evidence_record(relation))
        source_releases.add(relation.source_release_id)

    disease_evidence: dict[int, dict] = defaultdict(lambda: {
        "diseases": set(), "herbs": set(), "sources": [], "count": 0, "directCount": 0,
    })
    for relation in candidate_disease_target_relations:
        evidence = disease_evidence[relation.object_id]
        evidence["diseases"].add(relation.subject.label)
        evidence["sources"].append(_evidence_record(relation))
        evidence["count"] += 1
        direct_herb = (relation.metadata or {}).get("herbStableId")
        direct_herb_label = (
            selected_herbs_by_stable_id.get(direct_herb) if isinstance(direct_herb, str) else None
        )
        if direct_herb_label is not None:
            evidence["directCount"] += 1
            evidence["herbs"].add(direct_herb_label)
        source_releases.add(relation.source_release_id)

    target_entities = {
        item.pk: item for item in KnowledgeEntity.objects.filter(
            pk__in=target_entity_ids_for_candidates, is_active=True,
        ).filter(Q(source_release__isnull=True) | Q(source_release__source__enabled=True))
    }
    # Main annotates every candidate, including a direct-only disease/herb
    # target. Resolve those annotations from real, enabled catalogue evidence
    # rather than limiting them to targets reached through compounds.
    pathway_relations = read_relations(
        "pathways", limit_override=CANDIDATE_EVIDENCE_LIMIT,
        subject_ids=set(target_entities), relation_types=PATHWAY_TYPES,
    ) if target_entities else []
    pathway_by_target: dict[int, set[str]] = defaultdict(set)
    pathway_sources_by_target: dict[int, list[dict]] = defaultdict(list)
    for relation in pathway_relations:
        pathway_by_target[relation.subject_id].add(relation.object.label)
        pathway_sources_by_target[relation.subject_id].append(_evidence_record(relation))
        source_releases.add(relation.source_release_id)

    identity_labels = {
        key: target_node_identities[entity_id]["label"]
        for key, entity_ids in entities_by_identity.items()
        for entity_id in sorted(entity_ids)
        if entity_id in target_node_identities
    }

    targets = []
    for identity_key in sorted(candidate_identity_keys, key=lambda key: (
        identity_labels.get(key, min(
            (target_entities[entity_id].label for entity_id in entities_by_identity.get(key, set()) if entity_id in target_entities),
            default=key,
        )).casefold(), key,
    )):
        entity_ids = sorted(entities_by_identity.get(identity_key, set()))
        entities = [target_entities[entity_id] for entity_id in entity_ids if entity_id in target_entities]
        if not entities:
            continue
        identity = next((target_node_identities[entity_id] for entity_id in entity_ids
                         if entity_id in target_node_identities), None)
        display_label = identity["label"] if identity else entities[0].label
        herb_data = {"herbs": set(), "compounds": set(), "sources": [], "count": 0}
        disease_data = {"diseases": set(), "herbs": set(), "sources": [], "count": 0, "directCount": 0}
        pathways, pathway_sources = set(), []
        for entity_id in entity_ids:
            herb_item = herb_evidence.get(entity_id, {})
            disease_item = disease_evidence.get(entity_id, {})
            herb_data["herbs"].update(herb_item.get("herbs", set()))
            herb_data["compounds"].update(herb_item.get("compounds", set()))
            herb_data["sources"].extend(herb_item.get("sources", []))
            herb_data["count"] += herb_item.get("count", 0)
            disease_data["diseases"].update(disease_item.get("diseases", set()))
            disease_data["herbs"].update(disease_item.get("herbs", set()))
            disease_data["sources"].extend(disease_item.get("sources", []))
            disease_data["count"] += disease_item.get("count", 0)
            disease_data["directCount"] += disease_item.get("directCount", 0)
            pathways.update(pathway_by_target.get(entity_id, set()))
            pathway_sources.extend(pathway_sources_by_target.get(entity_id, []))
        sources = herb_data["sources"] + disease_data["sources"] + pathway_sources
        first_target = entities[0]
        targets.append({
            "target": display_label,
            "normalizedTarget": display_label.strip().upper(),
            "matchType": "严格交集" if identity_key in strict_identity_keys else "疾病—中药直接关联",
            "canonicalTargetKey": identity["key"] if identity else None,
            "identityStatus": "verified" if identity else "source_record_only",
            "sourceEntityIds": entity_ids,
            "targetName": (first_target.metadata or {}).get("name", ""),
            "genes": display_label if identity else (first_target.metadata or {}).get("symbol", first_target.label),
            "pathways": sorted(pathways),
            "components": sorted(herb_data["compounds"]),
            "herbs": sorted(herb_data["herbs"] | disease_data["herbs"]),
            "diseaseNames": sorted(disease_data["diseases"]),
            "herbEvidenceCount": herb_data["count"],
            "diseaseEvidenceCount": disease_data["count"],
            "directEvidenceCount": disease_data["directCount"],
            "sources": sources[:30],
        })

    # Main builds both charts from candidates rather than every herb target.
    # Canonicalized targets count once, while their source entity records and
    # evidence remain attached to the merged result row.
    component_chart = sorted(
        (
            {
                "name": compound_by_id[item].label,
                "targets": len({target_identity_key(entity_id)
                    for entity_id in compound_target_counts.get(item, set())
                    if target_identity_key(entity_id) in candidate_identity_keys}),
                "stableId": compound_by_id[item].stable_id,
            }
            for item in compound_ids
            if item in compound_by_id and any(
                target_identity_key(entity_id) in candidate_identity_keys
                for entity_id in compound_target_counts.get(item, set())
            )
        ),
        key=lambda item: (-item["targets"], item["name"], item["stableId"]),
    )[:20]
    pathway_target_identities: dict[str, set[str]] = defaultdict(set)
    for entity_id, names in pathway_by_target.items():
        identity_key = target_identity_key(entity_id)
        if identity_key in candidate_identity_keys:
            for name in names:
                pathway_target_identities[name].add(identity_key)
    candidate_pathways = set(pathway_target_identities)

    summary = {
        "herb": "、".join(requested_names),
        "herbs": herb_names,
        "matchedHerbs": [item.label for item in herbs],
        "unmatchedHerbs": [name for name in requested_names if name not in matched_herb_names and name not in matched_formula_names],
        "formulas": [item.label for item in formulas],
        "matchedFormulas": [item.label for item in formulas],
        "unmatchedFormulas": [name for name in requested_names if name not in matched_herb_names and name not in matched_formula_names],
        "unresolvedFormulas": [
            formula.label for formula in formulas
            if formula.pk not in {relation.subject_id for relation in formula_herb_relations}
        ],
        "disease": disease_query.strip(),
        "matchedDiseases": [item.label for item in diseases],
        "unmatchedDiseases": [] if diseases else [disease_query.strip()],
        "diseaseResolution": disease_resolution,
        "diseaseTargetCount": len(set(disease_entities_by_identity) | direct_identity_keys),
        "herbTargetCount": len(herb_entities_by_identity),
        "strictIntersectionCount": len(strict_identity_keys),
        "directAssociationTargetCount": len(direct_identity_keys),
        "diseaseTargetEntityCount": len(all_disease_target_ids),
        "diseaseTargetCandidateEntityCount": complete_identity["diseaseTargetEvidence"]["candidateEntityCount"],
        "diseaseTargetCandidateRelationCount": complete_identity["diseaseTargetEvidence"]["candidateRelationCount"],
        "herbTargetEntityCount": len(all_herb_target_ids),
        "strictEntityIdIntersectionCount": len(all_herb_target_ids & all_disease_target_ids),
        "candidateTargetCount": len(targets),
        "componentCount": len(compound_ids),
        "pathwayCount": len(candidate_pathways),
        "rowLimit": row_limit,
    }

    nodes = {}
    graph_entity_ids = {}
    graph_source_entities = {}
    query_herb_ids = {item.pk for item in herbs}
    query_disease_ids = {item.pk for item in diseases}
    links = []
    def add_node(entity: KnowledgeEntity):
        identity = target_node_identities.get(entity.pk)
        display_group = (
            'herb' if entity.pk in query_herb_ids else
            'disease' if entity.pk in query_disease_ids else None
        )
        if display_group:
            # This is a query-view aggregation only: exact same-name focus
            # records from several sources share one display node, while every
            # relationship keeps its original source and record identifier.
            normalized_label = unicodedata.normalize('NFKC', entity.label).strip().casefold()
            digest_key = hashlib.sha256(normalized_label.encode('utf-8')).hexdigest()[:20]
            node_id = f"query-{display_group}:{digest_key}"
            nodes.setdefault(node_id, {
                "id": node_id,
                "label": entity.label.strip(),
                "type": display_group,
            })
        elif identity:
            node_id = f"human-target:{identity['key']}"
            node = nodes.setdefault(node_id, {
                "id": node_id,
                "label": identity['label'],
                "type": 'target',
                "canonicalTargetKey": identity['key'],
                "canonicalTargetNamespace": identity['namespace'],
                "identityStatus": 'verified',
                "taxonKey": '9606',
                "targetOverlap": False,
                "sourceEntityCount": 0,
            })
        else:
            node_id = entity.stable_id
            nodes.setdefault(node_id, {
                "id": node_id,
                "label": entity.label,
                "type": entity.entity_type,
            })
        graph_source_entities.setdefault(node_id, set()).add(entity.pk)
        nodes[node_id]['sourceEntityCount'] = len(graph_source_entities[node_id])
        graph_entity_ids[entity.pk] = node_id
        return node_id

    focus_graph_ids = set()
    for entity in formulas + herbs + diseases:
        focus_graph_ids.add(add_node(entity))
    for relation in formula_herb_relations + herb_compound_relations + compound_target_relations + disease_target_relations + disease_herb_relations + pathway_relations:
        source_id = add_node(relation.subject)
        target_id = add_node(relation.object)
        links.append({
            "source": source_id,
            "target": target_id,
            "relation": relation.relation_type,
            "sourceRecordId": relation.source_record_id,
            "sourceSlug": relation.source_release.source.slug,
            "sourceVersion": relation.source_release.version,
        })
    herbs_by_stable_id = {entity.stable_id: entity for entity in herbs}
    for relation in disease_target_relations:
        metadata = relation.metadata if isinstance(relation.metadata, dict) else {}
        stable_id = metadata.get("herbStableId")
        herb = herbs_by_stable_id.get(stable_id) if isinstance(stable_id, str) else None
        if relation.relation_type != "disease_herb_target" or herb is None:
            continue
        links.append({
            "source": graph_entity_ids[relation.subject_id],
            "target": graph_entity_ids[herb.pk],
            "relation": "disease_herb_target（三元证据）",
            "sourceRecordId": relation.source_record_id,
            "sourceSlug": relation.source_release.source.slug,
            "sourceVersion": relation.source_release.version,
        })

    herb_target_ids = set()
    disease_target_node_ids = set()
    for edge in links:
        group = _network_edge_group(edge, nodes)
        if group == 'compound_target':
            herb_target_ids.add(edge['target'] if _network_node_group(nodes[edge['target']]['type']) == 'target' else edge['source'])
        elif group == 'disease_target':
            disease_target_node_ids.add(edge['target'] if _network_node_group(nodes[edge['target']]['type']) == 'target' else edge['source'])
    for node_id in herb_target_ids & disease_target_node_ids:
        if nodes[node_id].get('identityStatus') == 'verified':
            nodes[node_id]['targetOverlap'] = True

    graph_nodes, graph_links = _bounded_network(nodes, links, focus_graph_ids)
    displayed_herb_target_ids = set()
    displayed_disease_target_ids = set()
    for edge in graph_links:
        group = _network_edge_group(edge, nodes)
        if group == 'compound_target':
            displayed_herb_target_ids.add(
                edge['target'] if _network_node_group(nodes[edge['target']]['type']) == 'target' else edge['source']
            )
        elif group == 'disease_target':
            displayed_disease_target_ids.add(
                edge['target'] if _network_node_group(nodes[edge['target']]['type']) == 'target' else edge['source']
            )
    displayed_shared_target_ids = displayed_herb_target_ids & displayed_disease_target_ids
    for node in graph_nodes:
        if node.get('identityStatus') == 'verified':
            node['targetOverlap'] = node['id'] in displayed_shared_target_ids

    raw_limit = min(row_limit, RAW_EXPORT_LIMIT)
    raw, raw_truncated = _raw_side_evidence(
        herb_compound_relations, compound_target_relations, raw_disease_target_relations,
        herbs_by_stable_id=selected_herbs_by_stable_id, limit=raw_limit,
    )
    result = {
        "dataQuality": data_quality_notices(),
        "summary": summary,
        "targetIdentity": complete_identity,
        "targets": targets[:1000],
        "raw": raw,
        "rawLimits": {
            "formatVersion": RAW_EVIDENCE_VERSION,
            "rowLimit": raw_limit,
            "tablesTruncated": raw_truncated,
            "inputRelationsTruncated": relation_limits,
            "structuralEvidencePolicy": "workbook_structure_one_representative_per_source; all_target_rows_retained; full_original_rows_in_source_records",
            "structuralRowsCollapsed": any(
                relation.relation_type in {"contains", "disease_herb"}
                and relation.source_release.source.configuration.get("connector") == "local-workbooks-master"
                for relation in herb_compound_relations + disease_target_relations
            ),
        },
        "network": {"nodes": graph_nodes, "links": graph_links},
        "charts": {
            "overlap": [
                {"name": "中药靶点", "value": len(herb_entities_by_identity)},
                {"name": "疾病靶点", "value": len(disease_entities_by_identity)},
                {"name": "严格交集", "value": len(strict_identity_keys)},
                {"name": "直接关联", "value": len(direct_identity_keys)},
            ],
            "components": [{"name": item["name"], "targets": item["targets"]} for item in component_chart],
            "pathways": sorted(
                (
                    {"name": pathway, "targets": len(pathway_target_identities[pathway])}
                    for pathway in candidate_pathways
                ),
                key=lambda item: (-item["targets"], item["name"]),
            )[:20],
        },
        "limits": {
            "targetsTruncated": len(targets) > 1000,
            "linksTruncated": len(graph_links) < len(links),
            "networkNodesTruncated": len(graph_nodes) < len(nodes),
        },
    }
    if not persist:
        return result

    with transaction.atomic():
        owner = user
        medical_case = None
        input_parameters = {
            "herbs": herb_names,
            "requestedNames": requested_names,
            "formulas": [item.stable_id for item in formulas],
            "disease": disease_query.strip(),
            "diseaseResolution": disease_resolution,
            "rowLimit": row_limit,
            "statisticsVersion": STATISTICS_VERSION,
            "rawEvidenceVersion": RAW_EVIDENCE_VERSION,
            "targetIdentityReleaseId": result["targetIdentity"].get("releaseId"),
            "targetIdentityComparisonVersion": result["targetIdentity"].get("comparisonVersion"),
        }
        if source_case_candidate:
            medical_case = MedicalCase.objects.select_for_update().get(pk=source_case_candidate.medical_case_id)
            # The optional entity uses an outer join, which PostgreSQL cannot
            # lock. Serialize the candidate and its source task explicitly.
            candidate = (
                MedicalCaseCandidate.objects.select_for_update(of=("self", "task"))
                .select_related("task", "entity")
                .get(pk=source_case_candidate.pk, medical_case=medical_case)
            )
            from .case_analysis import case_input_sha256

            if (
                medical_case.owner_id != user.pk
                or candidate.review_status != MedicalCaseCandidate.ReviewStatus.ACCEPTED
                or candidate.candidate_type != MedicalCaseCandidate.CandidateType.FORMULA
                or not candidate.entity_id
                or candidate.entity_id not in {item.pk for item in formulas}
                or candidate.task.status != AnalysisTask.Status.SUCCEEDED
                or candidate.task.input_parameters.get("caseContentSha256") != case_input_sha256(medical_case)
            ):
                raise NetworkPharmacologyInputError(
                    "已确认方剂候选或医案内容已变化；请重新分析并确认后再创建网络药理任务。"
                )
            owner = medical_case.owner
            input_parameters.update({
                "sourceCaseId": medical_case.pk,
                "sourceCandidateId": candidate.pk,
                "caseContentSha256": candidate.task.input_parameters["caseContentSha256"],
                "sourceFormulaStableId": candidate.entity.stable_id,
            })
        task = AnalysisTask.objects.create(
            owner=owner,
            created_by=user,
            task_type=AnalysisTask.TaskType.NETWORK,
            status=AnalysisTask.Status.SUCCEEDED,
            progress=100,
            medical_case=medical_case,
            input_parameters=input_parameters,
            result=result,
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )
        task.source_releases.set(source_releases)
        if result["targetIdentity"].get("releaseId"):
            task.source_releases.add(result["targetIdentity"]["releaseId"])
    return {"taskId": task.pk, **result}
