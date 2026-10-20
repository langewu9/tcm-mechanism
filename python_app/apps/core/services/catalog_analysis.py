"""Persist local catalogue evidence for the existing private R task pipeline."""
from django.db import transaction
from django.utils import timezone

from apps.core.models import AnalysisTask
from .herb_evidence import batch_herb_component_evidence

MAX_GRAPH_RECORDS = 5000
MAX_GRAPH_NODES = 5000


class CatalogSnapshotChanged(ValueError):
    pass


def save_catalog_analysis(*, user, query_type, queries, expected_sha256):
    snapshot = batch_herb_component_evidence(query_type=query_type, queries=queries)
    if snapshot["resultSha256"] != expected_sha256:
        raise CatalogSnapshotChanged("目录数据已更新，请重新检索后再保存关系图。")
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
    now = timezone.now()
    with transaction.atomic():
        task = AnalysisTask.objects.create(
            owner=user, created_by=user, task_type=AnalysisTask.TaskType.NETWORK,
            status=AnalysisTask.Status.SUCCEEDED, progress=100, started_at=now, finished_at=now,
            input_parameters={"analysisKind": "catalog_evidence", "algorithmVersion": "catalog-evidence-0.3",
                              "queryType": query_type, "queries": queries, "resultSha256": expected_sha256},
            result={"analysisKind": "catalog_evidence", "queryType": query_type, "queries": queries,
                    "resultSha256": expected_sha256, "capturedAt": now.isoformat(),
                    "network": {"nodes": nodes, "links": links}, "evidenceRecords": selected,
                    "counts": {"nodes": len(nodes), "evidenceRecords": len(selected),
                               "returnedEvidenceRecords": len(records),
                               "uniqueEdges": len({tuple(sorted((link['source'], link['target']))) for link in links})},
                    "limits": {"queryTruncated": any(item["truncated"] for item in snapshot["results"]),
                               "graphTruncated": len(selected) < len(records)}},
        )
        task.source_releases.set(sorted(release_ids))
    return task
