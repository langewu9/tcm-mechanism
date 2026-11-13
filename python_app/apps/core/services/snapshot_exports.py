"""Stream a frozen task, in bounded DB batches. Never re-query live evidence."""
import csv

from rest_framework.exceptions import NotFound, ValidationError

from apps.core.models import AnalysisSnapshotRow, AnalysisTask
from .complete_evidence import canonical


def snapshot_manifest(task):
    if "frozen_snapshot_manifest" in task.__dict__:
        manifest = task.__dict__["frozen_snapshot_manifest"] or {}
    else:
        manifest = task.result.get("snapshot", {})
    if task.status != AnalysisTask.Status.SUCCEEDED or manifest.get("complete") is not True:
        raise NotFound("此任务没有完整证据快照；历史结果不会从当前目录补算。")
    return manifest


def snapshot_table(task, name):
    manifest = snapshot_manifest(task)
    if name not in manifest["tables"]:
        raise ValidationError({"table": "请选择此任务已保存的证据表。"})
    return manifest, AnalysisSnapshotRow.objects.filter(task=task, table=name).order_by("ordinal")


class _Echo:
    def write(self, value):
        return value


def _cell(value):
    if isinstance(value, (dict, list)):
        value = canonical(value)
    if value is None:
        return ""
    value = str(value)
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def csv_chunks(task, table):
    manifest, rows = snapshot_table(task, table)
    columns = manifest["tables"][table]["columns"]
    writer = csv.writer(_Echo())
    yield "\ufeff" + writer.writerow(["_taskId", "_snapshotSha256", "_row", *columns])
    for ordinal, payload in rows.values_list("ordinal", "payload").iterator(chunk_size=250):
        yield writer.writerow([task.pk, manifest["sha256"], ordinal, *(_cell(payload.get(key)) for key in columns)])


def jsonl_chunks(task, table=None):
    manifest = snapshot_manifest(task)
    names = [table] if table else list(manifest["tables"])
    result = {key: value for key, value in task.result.items() if key != "snapshot"}
    yield canonical({"type": "manifest", "taskId": task.pk, "ownerId": task.owner_id,
                     "parameters": task.input_parameters, "result": result, "snapshot": manifest}) + "\n"
    for name in names:
        _, rows = snapshot_table(task, name)
        for ordinal, payload in rows.values_list("ordinal", "payload").iterator(chunk_size=250):
            yield canonical({"type": "row", "table": name, "ordinal": ordinal, "payload": payload}) + "\n"
