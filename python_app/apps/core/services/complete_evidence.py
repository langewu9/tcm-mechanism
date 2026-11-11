"""Complete local analyses, frozen in paged rows rather than HTTP-sized JSON.

Safety ceilings are fail-closed workload bounds, NOT research/display cutoffs.
The transaction uses one consistent catalogue view and publishes rows + manifest
only together. Historical tasks are never filled from today's catalogue.
"""
import copy
import hashlib
import json

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.core.models import AnalysisSnapshotRow, AnalysisTask, MedicalCase, MedicalCaseCandidate, SourceRelease
from .catalog_analysis import CatalogSnapshotChanged, catalog_result
from .herb_evidence import _entity_record, _relation_record, batch_herb_component_evidence
from .network_pharmacology import NetworkPharmacologyInputError, build_network_pharmacology
from .task_recovery import TaskExecutionStopped


VERSION = "complete-local-evidence-1"


class CompleteEvidenceInputError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def relation_limit():
    return max(1, min(int(getattr(settings, "LOCAL_ANALYSIS_RELATION_LIMIT", 50000)), 100000))


def _freeze_table(task, name, records):
    checksum, columns, buffer, count = hashlib.sha256(), set(), [], 0
    for count, record in enumerate(records, 1):
        checksum.update((canonical(record) + "\n").encode())
        columns.update(record)
        buffer.append(AnalysisSnapshotRow(task=task, table=name, ordinal=count, payload=record))
        if len(buffer) == 250:
            AnalysisSnapshotRow.objects.bulk_create(buffer, batch_size=250)
            buffer.clear()
    if buffer:
        AnalysisSnapshotRow.objects.bulk_create(buffer, batch_size=250)
    return {"count": count, "sha256": checksum.hexdigest(), "columns": sorted(columns)}


def _catalog_data(task, limit):
    params = task.input_parameters
    preview = batch_herb_component_evidence(query_type=params["queryType"], queries=params["queries"])
    if preview["resultSha256"] != params["expectedResultSha256"]:
        raise CatalogSnapshotChanged("目录数据已更新，请重新检索后再保存完整查询。")
    items, records, entities, read_count = [], {}, {}, 0
    for query in params["queries"]:
        data = batch_herb_component_evidence(query_type=params["queryType"], queries=[query],
                                           relation_limit=limit, match_limit=1000, complete=True)
        item = data["results"][0]
        if item["truncated"]:
            raise CompleteEvidenceInputError("输入超过后台保护额度，请拆分查询；本次不会保存部分分析结果。")
        related_rows = [*item["relations"], *item.get("diseaseRelations", [])]
        read_count += len(related_rows)
        if read_count > 2 * limit:
            raise CompleteEvidenceInputError("批量输入超过后台保护额度，请拆分查询；本次不会保存部分分析结果。")
        items.append(item)
        for group, kind in (("herbs", "herb"), ("compounds", "compound"), ("targets", "target"),
                            ("diseases", "disease"), ("diseaseHerbs", "herb")):
            for entity in item[group]:
                entities[entity["id"]] = {**entity, "type": kind}
        records.update((row["id"], row) for row in related_rows)
        if len(records) > 2 * limit:
            raise CompleteEvidenceInputError("批量输入超过后台保护额度，请拆分查询；本次不会保存部分分析结果。")
    data = {"queryType": params["queryType"], "results": items}
    data["resultSha256"] = digest(data)
    if not records:
        raise CompleteEvidenceInputError("本次检索没有可保存的中药—成分—靶点关系。")
    result, _ = catalog_result(data)
    result["previewResultSha256"] = params["expectedResultSha256"]
    tables = {"evidenceRecords": [records[key] for key in sorted(records)],
              "entities": [entities[key] for key in sorted(entities)],
              "queries": [{"query": item["query"], "ambiguous": item["ambiguous"],
                           **({'resolution': item['resolution']} if 'resolution' in item else {}),
                           "matchedIds": [entity["id"] for entity in item["matches"]],
                           "herbIds": [entity["id"] for entity in item["herbs"]],
                           "compoundIds": [entity["id"] for entity in item["compounds"]],
                           "targetIds": [entity["id"] for entity in item["targets"]],
                           "diseaseIds": [entity["id"] for entity in item.get("diseases", [])],
                           "diseaseHerbIds": [entity["id"] for entity in item.get("diseaseHerbs", [])]} for item in items]}
    return result, tables


def _source_candidate(task):
    params = task.input_parameters
    if not params.get("sourceCaseId"):
        return None
    try:
        # Match candidate review and the synchronous network path's lock order:
        # case first, then candidate/task. A joined lock can otherwise acquire
        # the candidate first and deadlock with a concurrent human review.
        MedicalCase.objects.select_for_update().get(pk=params["sourceCaseId"], owner_id=task.owner_id)
        candidate = MedicalCaseCandidate.objects.select_for_update(of=("self", "task")).select_related(
            "task", "entity__source_release__source", "medical_case").get(
            pk=params["sourceCandidateId"], medical_case_id=params["sourceCaseId"],
            medical_case__owner_id=task.owner_id, task__owner_id=task.owner_id,
            task__medical_case_id=params["sourceCaseId"],
        )
    except (MedicalCase.DoesNotExist, MedicalCaseCandidate.DoesNotExist) as exc:
        raise NetworkPharmacologyInputError("关联的医案候选已不可用，请重新分析并确认后再提交。") from exc
    from .case_analysis import candidate_entity_available, case_input_sha256
    if (candidate.review_status != MedicalCaseCandidate.ReviewStatus.ACCEPTED
            or candidate.candidate_type != MedicalCaseCandidate.CandidateType.FORMULA
            or candidate.medical_case.archived_at is not None
            or not candidate.entity_id or not candidate_entity_available(candidate)
            or candidate.entity.stable_id != params["sourceFormulaStableId"]
            or candidate.task.status != AnalysisTask.Status.SUCCEEDED
            or candidate.task.input_parameters.get("caseContentSha256") != params["caseContentSha256"]
            or params["caseContentSha256"] != case_input_sha256(candidate.medical_case)):
        raise NetworkPharmacologyInputError("医案或已确认方剂已变化，请重新分析并确认后再提交。")
    return candidate


def _network_data(task, limit):
    params = task.input_parameters
    evidence, entities = {}, {}

    def capture_entities(rows):
        for entity in rows:
            entities[entity.pk] = {**_entity_record(entity), "type": entity.entity_type}

    def capture(stage, rows):
        for row in rows:
            evidence[row.pk] = _relation_record(row)
            capture_entities((row.subject, row.object))
        if len(evidence) > 2 * limit:
            raise CompleteEvidenceInputError("批量输入超过后台保护额度，请拆分查询；本次不会保存部分分析结果。")

    data = build_network_pharmacology(user=task.owner, herb_query=params["herb"], disease_query=params["disease"],
                                     row_limit=limit, source_case_candidate=_source_candidate(task),
                                     persist=False, complete=True, capture_relations=capture, capture_entities=capture_entities)
    targets = data["targets"]
    tables = {"evidenceRecords": [evidence[key] for key in sorted(evidence)],
              "entities": [entities[key] for key in sorted(entities)],
              "targets": [{key: value for key, value in target.items() if key != "sources"} for target in targets],
              **data["raw"],
              "targetSources": ({"targetIndex": index, "targetEntityId": target["entityId"], "targetStableId": target["stableId"], "target": target["target"], **source}
                                for index, target in enumerate(targets, 1) for source in target["sources"])}
    # Small result JSON serves cards/charts and backwards-compatible preview.
    result = {**data, "rawLimits": copy.deepcopy(data["rawLimits"]), "limits": {**data["limits"]}}
    result["targets"] = [{**target, "sources": target["sources"][:30]} for target in targets[:1000]]
    result["limits"]["targetsTruncated"] = len(targets) > 1000
    result["raw"] = {key: rows[:4000] for key, rows in data["raw"].items()}
    result["rawLimits"]["rowLimit"] = 4000
    result["rawLimits"]["tablesTruncated"] = {key: len(rows) > 4000 for key, rows in data["raw"].items()}
    return result, tables


def _disease_data(task, limit):
    from .disease_evidence import disease_relation_snapshot, search_disease_evidence
    params = task.input_parameters
    preview = search_disease_evidence(params["query"])
    if preview["resultSha256"] != params["expectedResultSha256"]:
        raise CatalogSnapshotChanged("疾病目录已更新，请重新检索后再保存完整查询。")
    captured = {}
    def capture(**rows):
        captured.update(rows)
    data = search_disease_evidence(params["query"], relation_limit=limit, match_limit=1000, capture=capture, complete=True)
    if data["truncated"]:
        raise CompleteEvidenceInputError("疾病输入超过后台保护额度，请缩小查询范围；本次不会保存部分分析结果。")
    if not data["matches"]:
        raise CompleteEvidenceInputError("当前启用目录没有匹配疾病，请确认名称或导入数据后重试。")
    tables = {
        "evidenceRecords": [disease_relation_snapshot(row) for row in captured["relations"]],
        "entities": [{**_entity_record(entity), "type": entity.entity_type}
                     for entity in sorted(captured["entities"], key=lambda item: item.pk)],
        "diseaseLinks": captured["links"],
        "queries": [{"query": data["query"], "expandedQueries": data["expandedQueries"],
                     "matchedIds": [item["id"] for item in data["matches"]],
                     "aliasSource": data["aliasSource"], "aliasSourceCommit": data["aliasSourceCommit"]}],
    }
    result = {"analysisKind": "disease_evidence", "query": data["query"],
              "expandedQueries": data["expandedQueries"], "aliasSource": data["aliasSource"],
              "aliasSourceCommit": data["aliasSourceCommit"], "ambiguous": data["ambiguous"],
              "counts": data["counts"], "limits": {"queryTruncated": False},
              "resultSha256": data["resultSha256"], "previewResultSha256": params["expectedResultSha256"],
              "summary": {"query": data["query"], **data["counts"]}}
    return result, tables


def _scientist_data(task, limit):
    from .scientist_report import build_report
    network, tables = _network_data(task, limit)
    return build_report(task.input_parameters, network, tables)


def execute_complete_evidence(task):
    with transaction.atomic():
        # Must precede the first catalogue read in this transaction (PostgreSQL).
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        builders = {"catalog_evidence": _catalog_data, "network_pharmacology": _network_data,
                    "disease_evidence": _disease_data, "scientist_hypothesis": _scientist_data}
        builder = builders.get(task.input_parameters.get("analysisKind"))
        if builder is None:
            raise CompleteEvidenceInputError("不支持的完整本地分析类型。")
        result, tables = builder(task, relation_limit())
        release_ids = {row["sourceReleaseId"] for row in tables["evidenceRecords"]}
        identity_release_id = result.get("targetIdentity", {}).get("releaseId")
        if identity_release_id:
            release_ids.add(identity_release_id)
        release_ids.update(row["sourceReleaseId"] for row in tables["entities"] if row["sourceReleaseId"])
        releases = [{"id": item.pk, "sourceSlug": item.source.slug, "version": item.version,
                     "checksumSha256": item.checksum_sha256}
                    for item in SourceRelease.objects.filter(pk__in=release_ids).select_related("source").order_by("pk")]
        manifest = {"version": VERSION, "complete": True, "capturedAt": timezone.now().isoformat(),
                    "sources": releases, "tables": {name: _freeze_table(task, name, rows) for name, rows in tables.items()}}
        # Include the actual parameters + displayed result as well as frozen tables.
        manifest["sha256"] = digest({"parameters": task.input_parameters, "result": result, "manifest": manifest})
        result["snapshot"] = manifest
        task.source_releases.set(sorted(release_ids))
        updated = AnalysisTask.objects.filter(pk=task.pk, status=AnalysisTask.Status.RUNNING).update(
            status=AnalysisTask.Status.SUCCEEDED, progress=100, result=result, finished_at=timezone.now())
        if not updated:
            raise TaskExecutionStopped("任务状态已改变，本次快照未发布。")
    return result


def dispatch_complete_task(task, *, request=None):
    from config.runtime_logs import record_runtime_event
    from apps.core.exceptions import TaskQueueUnavailable
    try:
        from apps.core.tasks import run_complete_evidence_task
        run_complete_evidence_task.apply_async(args=[task.pk])
    except Exception as exc:
        record_runtime_event("task.queue_unavailable", request=request, task_id=task.pk, exception=exc)
        AnalysisTask.objects.filter(pk=task.pk, status=AnalysisTask.Status.QUEUED).update(
            status=AnalysisTask.Status.FAILED, progress=100, error_summary="任务队列暂不可用，请稍后重试。",
            finished_at=timezone.now())
        raise TaskQueueUnavailable() from exc
