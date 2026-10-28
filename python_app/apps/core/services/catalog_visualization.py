"""Freeze server-resolved catalogue queries for private, reproducible R charts."""
import hashlib
import json
from collections import Counter

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.core.models import AnalysisTask, EvidenceRelation, KnowledgeEntity, SourceRelease


def fingerprint_result(data):
    """Hash the actual response, not client-supplied graph edges or display names."""
    body = {key: value for key, value in data.items() if key != "evidenceSha256"}
    digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {**body, "evidenceSha256": digest}


def entity_neighborhood(entity_id):
    from .data_quality import compound_properties
    from apps.core.serializers import EvidenceRelationSerializer, KnowledgeEntitySerializer
    visible = Q(source_release__isnull=True) | Q(source_release__source__enabled=True)
    entity = get_object_or_404(KnowledgeEntity.objects.filter(is_active=True).filter(visible), pk=entity_id)
    records = list(EvidenceRelation.objects.filter(
        Q(subject=entity) | Q(object=entity), is_active=True, subject__is_active=True,
        object__is_active=True, source_release__source__enabled=True,
    ).filter(
        (Q(subject__source_release__isnull=True) | Q(subject__source_release__source__enabled=True))
        & (Q(object__source_release__isnull=True) | Q(object__source_release__source__enabled=True))
    ).select_related("subject", "object", "source_release__source").order_by(
        "relation_type", "subject__label", "object__label", "source_release__version", "pk",
    )[:201])
    return fingerprint_result({"entity": KnowledgeEntitySerializer(entity).data,"compoundProperties":compound_properties(entity),
        "relations": EvidenceRelationSerializer(records[:200], many=True).data, "truncated": len(records) > 200})


def _query(parameters):
    kind = parameters["queryType"]
    if kind in {"herb", "compound"}:
        from .herb_evidence import batch_herb_component_evidence
        return fingerprint_result(batch_herb_component_evidence(query_type=kind, queries=parameters["queries"]))
    if kind == "disease":
        from .disease_evidence import search_disease_evidence
        return fingerprint_result(search_disease_evidence(parameters["queries"][0]))
    if kind == "pathway":
        from .pathway_catalog import search_reactome_pathways
        return fingerprint_result(search_reactome_pathways(parameters["queries"][0]))
    if kind == "comparison":
        from .component_names import compare_components_multilingual
        return fingerprint_result(compare_components_multilingual(parameters["detected"], parameters["reference"]))
    return entity_neighborhood(parameters["entityId"])


def _snapshot(data, kind):
    if kind == "comparison":
        return {"analysisKind": "catalog_evidence", "queryType": kind, "queryResult": data,
            "network": {"nodes": [], "links": []}, "catalogCoverage": [],
            "catalogSummary": [{"label": label, "value": data["counts"][key]} for label, key in
                (("仅检测名称", "detectedOnly"), ("精确名称交集", "matched"), ("仅参考名称", "referenceOnly"), ("同家族候选（非交集）", "familyMatches"))],
            "limits": {"truncated": False}, "evidenceSha256": data["evidenceSha256"]}, set()
    if kind in {"herb", "compound"}:
        rows = [row for item in data["results"] for row in item["relations"]]
        entity_ids = {entity["id"] for item in data["results"] for key in ("matches", "herbs", "compounds", "targets") for entity in item[key]}
        truncated = any(item["truncated"] for item in data["results"])
    else:
        rows = data.get("relations", [])
        entity_ids = {entity["id"] for key in ("matches", "herbs", "targets") for entity in data.get(key, [])}
        if kind == "entity": entity_ids.add(data["entity"]["id"])
        if kind == "pathway": entity_ids.update(item["entityId"] for item in data["items"])
        truncated = data.get("truncated", False)
    for row in rows:
        entity_ids.update((row.get("subjectId", row.get("subject")), row.get("objectId", row.get("object"))))
    entity_ids = {key for key in entity_ids if isinstance(key, int) and not isinstance(key, bool)}
    entities = list(KnowledgeEntity.objects.filter(pk__in=entity_ids, is_active=True).filter(
        Q(source_release__isnull=True) | Q(source_release__source__enabled=True),
    ).order_by("pk"))
    lookup = {entity.pk: entity for entity in entities}
    nodes = [{"id": f"entity:{entity.pk}", "label": entity.label, "type": entity.entity_type, "stableId": entity.stable_id} for entity in entities[:5000]]
    shown = {node["id"] for node in nodes}
    links, release_ids, unique_relations = [], {entity.source_release_id for entity in entities if entity.source_release_id}, set()
    for row in rows:
        relation_id = row.get("relationId", row.get("id"))
        if relation_id in unique_relations: continue
        unique_relations.add(relation_id)
        source, target = row.get("subjectId", row.get("subject")), row.get("objectId", row.get("object"))
        release_id = row.get("sourceReleaseId", row.get("source_release"))
        if release_id: release_ids.add(release_id)
        if source not in lookup or target not in lookup: continue
        left, right = f"entity:{source}", f"entity:{target}"
        if left not in shown or right not in shown: continue
        links.append({"source": left, "target": right, "relation": row.get("relationType", row.get("relation_type", "")),
            "sourceSlug": row.get("sourceSlug", row.get("source_slug", "")), "sourceVersion": row.get("sourceVersion", row.get("source_version", "")),
            "sourceRecordId": row.get("sourceRecordId", row.get("source_record_id", str(relation_id))), "relationId": relation_id,
            "evidenceType": row.get("evidenceType", row.get("evidence_type", ""))})
    counts = Counter(entity.entity_type for entity in entities)
    summary = [{"label": label, "value": value} for label, value in (
        ("中药实体", counts["herb"]), ("成分实体", counts["compound"]),
        ("靶点实体", counts["gene"] + counts["protein"]), ("疾病实体", counts["disease"]),
        ("通路实体", counts["pathway"]), ("去重关系记录", len(unique_relations)),
    )]
    coverage = []
    if kind == "pathway":
        coverage = [{"label": item["name"], "value": item["targetAnnotations"]} for item in data["items"]]
        for source in [*data["sources"], *(source for item in data["items"] for source in item["annotationSources"])]:
            release_ids.update(SourceRelease.objects.filter(source__slug=source["sourceSlug"], version=source["sourceVersion"]).values_list("pk", flat=True))
        summary = [{"label": "匹配通路", "value": data["matchedTotal"]}, {"label": "返回通路", "value": len(data["items"])},
            {"label": "有靶点注释的通路", "value": sum(item["targetAnnotations"] > 0 for item in data["items"])}]
    return {"analysisKind": "catalog_evidence", "queryType": kind, "queryResult": data,
        "network": {"nodes": nodes, "links": links}, "catalogSummary": summary, "catalogCoverage": coverage,
        "limits": {"truncated": truncated or len(entities) > 5000}, "evidenceSha256": data["evidenceSha256"]}, release_ids


class CatalogueChanged(ValueError):
    pass


@transaction.atomic
def freeze_catalog_query(*, user, parameters):
    # Serialize same-owner requests; a repeated click reuses the immutable snapshot.
    get_user_model().objects.select_for_update().get(pk=user.pk)
    data = _query(parameters)
    if data["evidenceSha256"] != parameters["expectedSha256"]:
        raise CatalogueChanged("目录数据已变化，请重新检索后生成 R 图表；不会混用两个版本的结果。")
    existing = AnalysisTask.objects.filter(owner=user, task_type="network", status="succeeded",
        input_parameters__analysisKind="catalog_evidence", input_parameters__evidenceSha256=data["evidenceSha256"],
        input_parameters__queryType=parameters["queryType"]).first()
    if existing: return existing
    result, releases = _snapshot(data, parameters["queryType"])
    now = timezone.now()
    task = AnalysisTask.objects.create(owner=user, created_by=user, task_type="network", status="succeeded", progress=100,
        input_parameters={"analysisKind": "catalog_evidence", "queryType": parameters["queryType"],
            "queries": parameters.get("queries", []), "entityId": parameters.get("entityId"), "evidenceSha256": data["evidenceSha256"]},
        result=result, started_at=now, finished_at=now)
    task.source_releases.set(SourceRelease.objects.filter(pk__in=releases, source__enabled=True))
    return task
