"""Evidence-backed herb/disease target intersection over the local catalogue."""

from __future__ import annotations

import re
from collections import defaultdict

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.models import AnalysisTask, EvidenceRelation, KnowledgeEntity, MedicalCase, MedicalCaseCandidate
from .herb_row_support import HerbRowSupport


INPUT_SPLIT = re.compile(r"[,，、;；|/\n\r]+")
HERB_COMPOUND_TYPES = {"contains", "herb_compound", "has_compound"}
FORMULA_HERB_TYPES = {"contains", "contains_herb", "formula_herb", "has_herb", "composed_of"}
COMPOUND_TARGET_TYPES = {"targets", "compound_target", "acts_on"}
DISEASE_TARGET_TYPES = {"disease_target", "disease_herb_target"}
PATHWAY_TYPES = {
    "genepathway", "gene_pathway", "proteinpathway", "protein_pathway", "targetpathway", "target_pathway",
    "participatesin", "participates_in", "annotatedtopathway", "annotated_to_pathway",
    "associatedwithpathway", "associated_with_pathway",
}
STATISTICS_VERSION = "main-078d374-candidate-statistics-v2"
RAW_EVIDENCE_VERSION = "network-raw-evidence-v2"
RAW_EXPORT_LIMIT = 4000


class NetworkPharmacologyInputError(ValueError):
    """A source candidate or case changed before a linked analysis could be saved."""


def parse_herb_names(value: str) -> list[str]:
    return list(dict.fromkeys(part.strip() for part in INPUT_SPLIT.split(value) if part.strip()))


def _entity_matches(entity_type: str, labels: list[str]) -> tuple[list[KnowledgeEntity], set[str]]:
    matches = []
    matched_labels = set()
    for label in labels:
        exact = list(KnowledgeEntity.objects.filter(
            entity_type=entity_type, is_active=True, label__iexact=label,
        ).filter(
            Q(source_release__isnull=True) | Q(source_release__source__enabled=True)
        ).order_by("stable_id")[:10])
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


def _relation_query(*, subject_ids=None, object_ids=None, relation_types, limit):
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

    def read_relations(stage, **kwargs):
        rows = _relation_query(**kwargs, limit=row_limit + 1)
        relation_limits[stage] = len(rows) > row_limit
        return rows[:row_limit]

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
    diseases, matched_disease_names = _entity_matches(KnowledgeEntity.EntityType.DISEASE, [disease_query.strip()])
    herb_ids = {item.pk for item in herbs}
    disease_ids = {item.pk for item in diseases}
    selected_herbs_by_stable_id = {item.stable_id: item.label for item in herbs}

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
        "diseaseTargets", subject_ids=disease_ids, relation_types=DISEASE_TARGET_TYPES,
    ) if diseases else []
    compound_by_id = {relation.object_id: relation.object for relation in herb_compound_relations}
    compound_target_counts: dict[int, set[int]] = defaultdict(set)
    herb_evidence: dict[int, dict] = defaultdict(lambda: {
        "herbs": set(), "compounds": set(), "sources": [], "count": 0,
    })
    source_releases = {relation.source_release_id for relation in formula_herb_relations}
    for relation in herb_compound_relations:
        source_releases.add(relation.source_release_id)
    for relation in compound_target_relations:
        compound_target_counts[relation.subject_id].add(relation.object_id)
        evidence = herb_evidence[relation.object_id]
        compound_support = support.for_target(relation)
        evidence["count"] += 1
        evidence["compounds"].add(relation.subject.label)
        evidence["herbs"].update(item.subject.label for item in compound_support)
        evidence["sources"].extend(_evidence_record(item) for item in compound_support)
        evidence["sources"].append(_evidence_record(relation))
        source_releases.add(relation.source_release_id)

    disease_evidence: dict[int, dict] = defaultdict(lambda: {
        "diseases": set(), "herbs": set(), "sources": [], "count": 0, "directCount": 0,
    })
    for relation in disease_target_relations:
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

    strict_ids = set(herb_evidence) & set(disease_evidence)
    direct_ids = {
        entity_id for entity_id, evidence in disease_evidence.items()
        if evidence["directCount"]
    }
    # Direct association and strict intersection describe independent evidence
    # sets, so an overlapping target contributes to both summary counts. Their
    # union still produces one target row, with strict intersection taking
    # precedence in its displayed match type, as in main.
    target_ids = strict_ids | direct_ids
    target_entities = {
        item.pk: item for item in KnowledgeEntity.objects.filter(pk__in=target_ids, is_active=True).filter(
            Q(source_release__isnull=True) | Q(source_release__source__enabled=True)
        )
    }
    # Main annotates every candidate, including a direct-only disease/herb
    # target. Resolve those annotations from real, enabled catalogue evidence
    # rather than limiting them to targets reached through compounds.
    pathway_relations = read_relations(
        "pathways", subject_ids=set(target_entities), relation_types=PATHWAY_TYPES,
    ) if target_entities else []
    pathway_by_target: dict[int, set[str]] = defaultdict(set)
    pathway_sources_by_target: dict[int, list[dict]] = defaultdict(list)
    for relation in pathway_relations:
        pathway_by_target[relation.subject_id].add(relation.object.label)
        pathway_sources_by_target[relation.subject_id].append(_evidence_record(relation))
        source_releases.add(relation.source_release_id)

    targets = []
    for entity_id in sorted(target_ids, key=lambda item: (
        target_entities[item].label.casefold(), target_entities[item].stable_id, item,
    ) if item in target_entities else ("", "", item)):
        target = target_entities.get(entity_id)
        if target is None:
            continue
        herb_data = herb_evidence.get(entity_id, {})
        disease_data = disease_evidence.get(entity_id, {})
        sources = (herb_data.get("sources", []) or []) + (disease_data.get("sources", []) or []) + pathway_sources_by_target.get(entity_id, [])
        targets.append({
            "target": target.label,
            "normalizedTarget": target.label.strip().upper(),
            "matchType": "严格交集" if entity_id in strict_ids else "疾病—中药直接关联",
            "targetName": (target.metadata or {}).get("name", ""),
            "genes": (target.metadata or {}).get("symbol", target.label),
            "pathways": sorted(pathway_by_target.get(entity_id, set())),
            "components": sorted(herb_data.get("compounds", set())),
            "herbs": sorted(set(herb_data.get("herbs", set())) | disease_data.get("herbs", set())),
            "diseaseNames": sorted(disease_data.get("diseases", set())),
            "herbEvidenceCount": herb_data.get("count", 0),
            "diseaseEvidenceCount": disease_data.get("count", 0),
            "directEvidenceCount": disease_data.get("directCount", 0),
            "sources": sources[:30],
        })

    # Main builds both charts from candidate rows rather than every herb target.
    # Keep stable entity identity for uniqueness here: catalogue entities with
    # coincidentally equal labels must not be merged into one molecular target.
    component_chart = sorted(
        (
            {
                "name": compound_by_id[item].label,
                "targets": len(compound_target_counts.get(item, set()) & target_ids),
                "stableId": compound_by_id[item].stable_id,
            }
            for item in compound_ids
            if item in compound_by_id and compound_target_counts.get(item, set()) & target_ids
        ),
        key=lambda item: (-item["targets"], item["name"], item["stableId"]),
    )[:20]
    candidate_pathways = {
        name for entity_id, names in pathway_by_target.items() if entity_id in target_ids for name in names
    }

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
        "unmatchedDiseases": [] if disease_query.strip() in matched_disease_names else [disease_query.strip()],
        "diseaseTargetCount": len(disease_evidence),
        "herbTargetCount": len(herb_evidence),
        "strictIntersectionCount": len(strict_ids),
        "directAssociationTargetCount": len(direct_ids),
        "candidateTargetCount": len(targets),
        "componentCount": len(compound_ids),
        "pathwayCount": len(candidate_pathways),
        "rowLimit": row_limit,
    }

    nodes = {}
    links = []
    def add_node(entity: KnowledgeEntity):
        nodes[entity.stable_id] = {
            "id": entity.stable_id,
            "label": entity.label,
            "type": entity.entity_type,
        }
    for entity in formulas + herbs + diseases:
        add_node(entity)
    for relation in formula_herb_relations + herb_compound_relations + compound_target_relations + disease_target_relations + pathway_relations:
        add_node(relation.subject)
        add_node(relation.object)
        links.append({
            "source": relation.subject.stable_id,
            "target": relation.object.stable_id,
            "relation": relation.relation_type,
            "sourceRecordId": relation.source_record_id,
            "sourceSlug": relation.source_release.source.slug,
        })

    raw_limit = min(row_limit, RAW_EXPORT_LIMIT)
    raw, raw_truncated = _raw_side_evidence(
        herb_compound_relations, compound_target_relations, disease_target_relations,
        herbs_by_stable_id=selected_herbs_by_stable_id, limit=raw_limit,
    )
    result = {
        "summary": summary,
        "targets": targets[:1000],
        "raw": raw,
        "rawLimits": {
            "formatVersion": RAW_EVIDENCE_VERSION,
            "rowLimit": raw_limit,
            "tablesTruncated": raw_truncated,
            "inputRelationsTruncated": relation_limits,
        },
        "network": {"nodes": list(nodes.values())[:2000], "links": links[:4000]},
        "charts": {
            "overlap": [
                {"name": "中药靶点", "value": len(herb_evidence)},
                {"name": "疾病靶点", "value": len(disease_evidence)},
                {"name": "严格交集", "value": len(strict_ids)},
                {"name": "直接关联", "value": len(direct_ids)},
            ],
            "components": [{"name": item["name"], "targets": item["targets"]} for item in component_chart],
            "pathways": sorted(
                (
                    {"name": pathway, "targets": sum(pathway in values for entity_id, values in pathway_by_target.items() if entity_id in target_ids)}
                    for pathway in candidate_pathways
                ),
                key=lambda item: (-item["targets"], item["name"]),
            )[:20],
        },
        "limits": {
            "targetsTruncated": len(targets) > 1000,
            "linksTruncated": len(links) > 4000,
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
            "rowLimit": row_limit,
            "statisticsVersion": STATISTICS_VERSION,
            "rawEvidenceVersion": RAW_EVIDENCE_VERSION,
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
    return {"taskId": task.pk, **result}
