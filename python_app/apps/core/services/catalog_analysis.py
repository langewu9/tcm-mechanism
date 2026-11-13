"""Persist local catalogue evidence for the existing private R task pipeline."""
from collections import Counter
import hashlib
import json

from django.db import transaction
from django.utils import timezone

from apps.core.models import AnalysisTask
from .herb_evidence import batch_herb_component_evidence

MAX_GRAPH_RECORDS = 5000
MAX_GRAPH_NODES = 5000


class CatalogSnapshotChanged(ValueError):
    pass


def catalog_summary(entities, relation_count):
    """Count source identities, never names or the bounded display projection."""
    counts = Counter(entity["type"] for entity in entities)
    return [{"label": label, "value": value} for label, value in (
        ("中药实体", counts["herb"]), ("成分实体", counts["compound"]),
        ("靶点实体", counts["target"] + counts["gene"] + counts["protein"]),
        ("疾病实体", counts["disease"]), ("通路实体", counts["pathway"]),
        ("去重关系记录", relation_count),
    )]


def frozen_catalog_summary(task):
    """Compatibility for old complete snapshots without altering their results."""
    result = task.result or {}
    manifest = result.get("snapshot") or {}
    tables = manifest.get("tables") or {}
    if result.get("queryType") not in {"herb", "compound"} or manifest.get("complete") is not True:
        raise ValueError("本次检索没有保存可统计的完整实体和关系表。")
    expected = {}
    for name in ("entities", "evidenceRecords"):
        metadata = tables.get(name) or {}
        count = metadata.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("完整快照的统计清单无效。")
        expected[name] = count
    if task.snapshot_rows.filter(table="evidenceRecords").count() != expected["evidenceRecords"]:
        raise ValueError("完整快照的关系数量与保存清单不一致。")

    checksum, types, count = hashlib.sha256(), Counter(), 0
    for row in task.snapshot_rows.filter(table="entities").order_by("ordinal").values_list("payload", flat=True).iterator(chunk_size=250):
        count += 1
        if count > expected["entities"] or not isinstance(row, dict) or not isinstance(row.get("type"), str):
            raise ValueError("完整快照的实体统计数据无效。")
        checksum.update((json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode())
        types[row["type"]] += 1
    if count != expected["entities"] or checksum.hexdigest() != tables["entities"].get("sha256"):
        raise ValueError("完整快照的实体数量或校验值不一致。")
    # Feed only saved type counts to the same formatter; no live catalogue reads.
    return [{"label": label, "value": value} for label, value in (
        ("中药实体", types["herb"]), ("成分实体", types["compound"]),
        ("靶点实体", types["target"] + types["gene"] + types["protein"]),
        ("疾病实体", types["disease"]), ("通路实体", types["pathway"]),
        ("去重关系记录", expected["evidenceRecords"]),
    )]


def save_catalog_analysis(*, user, query_type, queries, expected_sha256):
    snapshot = batch_herb_component_evidence(query_type=query_type, queries=queries)
    if snapshot["resultSha256"] != expected_sha256:
        raise CatalogSnapshotChanged("目录数据已更新，请重新检索后再保存关系图。")
    if any(item["truncated"] for item in snapshot["results"]):
        raise ValueError("预览未包含全部输入，请使用完整后台分析。")
    result, release_ids = catalog_result(snapshot)
    now = timezone.now()
    with transaction.atomic():
        task = AnalysisTask.objects.create(
            owner=user, created_by=user, task_type=AnalysisTask.TaskType.NETWORK,
            status=AnalysisTask.Status.SUCCEEDED, progress=100, started_at=now, finished_at=now,
            input_parameters={"analysisKind": "catalog_evidence", "algorithmVersion": "catalog-evidence-0.5" if query_type == 'compound' else "catalog-evidence-0.4",
                              "queryType": query_type, "queries": queries, "resultSha256": expected_sha256},
            result=result,
        )
        task.source_releases.set(sorted(release_ids))
    return task


def catalog_result(snapshot):
    """Graph is a bounded display projection; caller separately freezes ALL rows."""
    entities, records = {}, {}
    for item in snapshot["results"]:
        for group, kind in (("herbs", "herb"), ("compounds", "compound"), ("targets", "target")):
            for entity in item[group]:
                entities[entity["id"]] = {**entity, "type": kind}
        for record in item["relations"]:
            records[record["id"]] = record
    used, selected = set(), []
    for record_id in sorted(records):
        record = records[record_id]
        endpoints = {record["subjectId"], record["objectId"]}
        if not endpoints <= entities.keys():
            raise ValueError("关系端点与检索实体不一致，请重新检索。")
        if len(selected) >= MAX_GRAPH_RECORDS or len(used | endpoints) > MAX_GRAPH_NODES:
            continue
        used.update(endpoints)
        selected.append(record)
    if not selected:
        raise ValueError("本次检索没有可保存的中药—成分—靶点关系。")
    nodes = [{"id": f"entity:{pk}", "label": entities[pk]["label"], "type": entities[pk]["type"],
              "stableId": entities[pk]["stableId"], "entityId": pk,
              "sourceReleaseId": entities[pk]["sourceReleaseId"],
              **{key: entities[pk][key] for key in ("sourceEntityId", "sourceReferences", "identifierStatus", "organism")}}
             for pk in sorted(used)]
    links = [{"source": f"entity:{record['subjectId']}", "target": f"entity:{record['objectId']}",
              "relation": record["relationType"], "sourceRecordId": record["sourceRecordId"],
              "sourceSlug": record["sourceSlug"], "sourceVersion": record["sourceVersion"],
              "sourceReleaseId": record["sourceReleaseId"], "evidenceId": record["id"]} for record in selected]
    release_ids = {record["sourceReleaseId"] for record in selected}
    release_ids.update(entities[pk]["sourceReleaseId"] for pk in used if entities[pk]["sourceReleaseId"])
    return {"analysisKind": "catalog_evidence", "queryType": snapshot["queryType"], "queries": [item["query"] for item in snapshot["results"]],
                    **({'queryResolutions': [{'query': item['query'], 'resolution': item['resolution']} for item in snapshot['results']]}
                       if snapshot['queryType'] == 'compound' else {}),
                    "resultSha256": snapshot["resultSha256"], "capturedAt": timezone.now().isoformat(),
                    "network": {"nodes": nodes, "links": links}, "evidenceRecords": selected,
                    "catalogSummary": catalog_summary(entities.values(), len(records)),
                    "counts": {"nodes": len(nodes), "evidenceRecords": len(selected),
                               "returnedEvidenceRecords": len(records),
                               "uniqueEdges": len({tuple(sorted((link['source'], link['target']))) for link in links})},
                    "limits": {"queryTruncated": any(item["truncated"] for item in snapshot["results"]),
                               "graphTruncated": len(selected) < len(records)}}, release_ids
