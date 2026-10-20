"""Port main's four keyword rules and typed knowledge chain to Django.

The rules come from origin/main@078d374:src/lib/analysis.ts. Rule matches
are research candidates, not diagnoses. Unmatched inputs never fall back to
the first rule or an unrelated catalogue record.
"""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.models import AnalysisTask, EvidenceRelation, KnowledgeEntity, MedicalCaseAuditEvent
from .case_analysis import case_input_sha256
from .case_audit import create_case_audit_event
from .network_pharmacology import COMPOUND_TARGET_TYPES, FORMULA_HERB_TYPES, HERB_COMPOUND_TYPES, PATHWAY_TYPES


ALGORITHM_VERSION = "text-analysis-main-1.0"
RULE_SOURCE = "origin/main@078d374:src/lib/analysis.ts"
SYNDROME_RULES = (
    ("气虚血瘀", ("乏力", "偏瘫", "舌暗", "脉涩", "中风")),
    ("痰瘀阻络", ("痰", "眩晕", "麻木", "语言不利", "苔腻")),
    ("肝阳上亢", ("头痛", "眩晕", "急躁", "血压", "肝阳")),
    ("阴虚风动", ("手足震颤", "口干", "失眠", "舌红", "风动")),
)
MAX_RELATIONS = 500


def rank_syndrome_rules(query):
    scores = []
    for name, keywords in SYNDROME_RULES:
        hits = [keyword for keyword in keywords if keyword in query]
        scores.append({"name": name, "score": len(hits), "matchedKeywords": hits})
    # Python's stable sort preserves main's source order for tied scores.
    return sorted(scores, key=lambda item: -item["score"])


def _node(entity):
    return {
        "id": f"{entity.entity_type}:{entity.stable_id}",
        "label": entity.label,
        "type": entity.entity_type,
    }


def _active_entities():
    return KnowledgeEntity.objects.filter(is_active=True).filter(
        Q(source_release__isnull=True) | Q(source_release__source__enabled=True)
    ).select_related("source_release__source")


def build_text_analysis(query, *, relation_limit=MAX_RELATIONS):
    rule_scores = rank_syndrome_rules(query)
    selected = rule_scores[0] if rule_scores[0]["score"] else None
    result = {
        "algorithmVersion": ALGORITHM_VERSION,
        "ruleSource": RULE_SOURCE,
        "ruleScores": rule_scores,
        "selectedRule": selected,
        "matchStatus": "no_rule_match",
        "summary": "输入未命中旧版四组关键词规则，未选择证候或生成方药关联链。",
        "evidence": {"syndrome": "", "formula": [], "herbs": [], "compounds": [], "targets": [], "genes": [], "pathways": []},
        "network": {"nodes": [], "links": []},
        "evidenceRecords": [],
        "sources": [],
        "warnings": ["关键词规则仅提供研究候选；目录关联不代表确诊、疗效或因果关系。"],
        "limits": {"maxRelations": relation_limit, "relationsTruncated": False},
    }
    if not selected:
        return result
    syndromes = list(_active_entities().filter(
        entity_type=KnowledgeEntity.EntityType.SYNDROME, label=selected["name"],
    ).order_by("pk")[:2])
    if not syndromes:
        result.update(
            matchStatus="catalog_missing",
            summary=f"关键词规则匹配到“{selected['name']}”候选，但启用目录中没有对应证候，未生成方药关联链。",
        )
        return result
    if len(syndromes) > 1:
        result.update(
            matchStatus="ambiguous_syndrome",
            summary=f"启用目录中有多个“{selected['name']}”证候记录，需要先核对来源；系统未自动选取记录。",
        )
        return result
    syndrome = syndromes[0]
    nodes = {_node(syndrome)["id"]: _node(syndrome)}
    relations = {}
    release_by_id = {}

    def remember_entity(entity, *, graph=True):
        if graph:
            nodes[_node(entity)["id"]] = _node(entity)
        if entity.source_release_id:
            release_by_id[entity.source_release_id] = entity.source_release

    remember_entity(syndrome)

    def traverse(frontier, object_types, relation_types, *, reverse=False, graph=True):
        if not frontier:
            return []
        remaining = max(0, relation_limit - len(relations))
        filters = {"object_id__in" if reverse else "subject_id__in": [item.pk for item in frontier]}
        filters["subject__entity_type__in" if reverse else "object__entity_type__in"] = object_types
        queryset = EvidenceRelation.objects.filter(
            is_active=True, subject__is_active=True, object__is_active=True,
            source_release__source__enabled=True, relation_type__in=relation_types,
            **filters,
        ).filter(
            (Q(subject__source_release__isnull=True) | Q(subject__source_release__source__enabled=True))
            & (Q(object__source_release__isnull=True) | Q(object__source_release__source__enabled=True))
        ).select_related(
            "subject__source_release__source", "object__source_release__source", "source_release__source",
        ).order_by("pk")
        records = list(queryset[:remaining + 1])
        if len(records) > remaining:
            result["limits"]["relationsTruncated"] = True
        found = {}
        for relation in records[:remaining]:
            endpoint = relation.subject if reverse else relation.object
            found[endpoint.pk] = endpoint
            remember_entity(relation.subject, graph=graph)
            remember_entity(relation.object, graph=graph)
            release = relation.source_release
            release_by_id[release.pk] = release
            relations[relation.pk] = {
                "refId": f"relation:{relation.pk}",
                "subject": _node(relation.subject)["id"], "subjectLabel": relation.subject.label,
                "object": _node(relation.object)["id"], "objectLabel": relation.object.label,
                "relationType": relation.relation_type, "evidenceType": relation.evidence_type,
                "source": release.source.name, "sourceSlug": release.source.slug,
                "sourceVersion": release.version, "sourceRecordId": relation.source_record_id,
                "score": float(relation.score) if relation.score is not None else None,
            }
            if graph:
                result["network"]["links"].append({
                    "source": _node(relation.subject)["id"], "target": _node(relation.object)["id"],
                    "relation": relation.relation_type, "sourceRecordId": relation.source_record_id,
                    "sourceSlug": release.source.slug,
                })
        return list(found.values())

    formulas = traverse([syndrome], ["formula"], {"syndrome_formula"})
    herbs = traverse(formulas, ["herb"], FORMULA_HERB_TYPES)
    compounds = traverse(herbs, ["compound"], HERB_COMPOUND_TYPES)
    targets = traverse(compounds, ["protein", "gene"], COMPOUND_TARGET_TYPES | {"compound_gene", "compound_protein"})
    pathways = traverse(targets, ["pathway"], PATHWAY_TYPES)
    proteins = [target for target in targets if target.entity_type == "protein"]
    genes = {target.pk: target for target in targets if target.entity_type == "gene"}
    for gene in traverse(proteins, ["gene"], {"protein_gene", "target_gene", "encoded_by"}, graph=False):
        genes[gene.pk] = gene
    for gene in traverse(proteins, ["gene"], {"encodes"}, reverse=True, graph=False):
        genes[gene.pk] = gene
    result.update(
        matchStatus="matched",
        summary=f"旧版关键词规则优先匹配“{syndrome.label}”研究候选；启用目录关联到 {len(formulas)} 个方剂、{len(herbs)} 味中药、{len(compounds)} 个成分、{len(targets)} 个靶点及 {len(pathways)} 条通路。请逐项核对规则命中与目录来源。",
        evidence={
            "syndrome": syndrome.label, "formula": [item.label for item in formulas],
            "herbs": [item.label for item in herbs], "compounds": [item.label for item in compounds],
            "targets": [item.label for item in targets], "genes": [item.label for item in genes.values()],
            "pathways": [item.label for item in pathways],
        },
        evidenceRecords=list(relations.values()),
        sources=[{
            "id": release.pk, "source": release.source.name, "sourceSlug": release.source.slug,
            "version": release.version, "checksumSha256": release.checksum_sha256,
        } for release in sorted(release_by_id.values(), key=lambda release: release.pk)],
    )
    result["network"]["nodes"] = list(nodes.values())
    if result["limits"]["relationsTruncated"]:
        result["warnings"].append(f"本次关联链超过 {relation_limit} 条来源关系，结果已截断。")
    if len([item for item in rule_scores if item["score"] == selected["score"]]) > 1:
        result["warnings"].append("有规则命中数并列；沿用旧版规则表的先后顺序选择首项，不把排序作为置信度。")
    return result


@transaction.atomic
def create_text_analysis(*, user, name, query, medical_case=None):
    result = build_text_analysis(query)
    now = timezone.now()
    parameters = {"name": name, "query": query, "algorithmVersion": ALGORITHM_VERSION, "ruleSource": RULE_SOURCE}
    if medical_case:
        parameters["caseInputSha256"] = case_input_sha256(medical_case)
    task = AnalysisTask.objects.create(
        owner=medical_case.owner if medical_case else user, created_by=user,
        task_type=AnalysisTask.TaskType.TEXT_ANALYSIS, status=AnalysisTask.Status.SUCCEEDED,
        medical_case=medical_case, input_parameters=parameters, result=result,
        progress=100, started_at=now, finished_at=now,
    )
    task.source_releases.set([item["id"] for item in result["sources"]])
    if medical_case:
        create_case_audit_event(
            case=medical_case, actor=user, action=MedicalCaseAuditEvent.Action.ANALYSIS_REQUESTED,
            metadata={"taskId": task.pk, "algorithmVersion": ALGORITHM_VERSION},
        )
    return task
