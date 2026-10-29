"""Bounded, local-only inventory. Findings are never deletion instructions."""
import hashlib
import os
from pathlib import Path
import stat

from django.conf import settings
from django.core.files.storage import FileSystemStorage, storages
from django.db.models import Count

from apps.core.models import AnalysisTask, ResearchDataset, VisualizationArtifact
from .artifact_integrity import ArtifactReadError, metadata_issue, open_local_file, valid_sha


def audit_result_files(*, max_records=10000, max_files=10000, max_findings=200, max_bytes=2 * 1024**3):
    limits = {"maxRecords": max_records, "maxFiles": max_files, "maxFindings": max_findings, "maxBytes": max_bytes}
    ceilings = {"maxRecords": 100000, "maxFiles": 1000000, "maxFindings": 10000, "maxBytes": 100 * 1024**3}
    if any(isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= ceilings[key] for key, value in limits.items()):
        raise ValueError("Audit limits must be positive integers within their hard ceilings.")
    report = {"schemaVersion": "result-file-audit-1", "readOnly": True, "complete": True, "status": "ok",
        "limits": limits, "incompleteReasons": [], "findings": [], "findingsTruncated": False,
        "filesystemIsLiveNotAtomic": True, "unregisteredFilesAreDeletionCandidates": False,
        "counters": {"recordsChecked": 0, "artifactRecords": 0, "datasetRecords": 0, "renderTaskRecords": 0,
            "registeredFilesChecked": 0, "filesystemEntriesChecked": 0, "bytesHashed": 0,
            "findingCount": 0, "unregisteredCandidates": 0, "notChecked": 0}}
    counts = report["counters"]

    def incomplete(reason):
        report["complete"] = False
        if reason not in report["incompleteReasons"]:
            report["incompleteReasons"].append(reason)

    def finding(kind, reason, record_id=None, key=None):
        counts["findingCount"] += 1
        item = {"kind": kind, "reason": reason}
        if record_id is not None:
            item["recordId"] = record_id
        if key is not None:
            item["storageKeySha256"] = hashlib.sha256(str(key).encode()).hexdigest()
        if len(report["findings"]) < max_findings:
            report["findings"].append(item)
        else:
            report["findingsTruncated"] = True
            incomplete("finding_output_limit")

    storage = storages["default"]
    if type(storage) is not FileSystemStorage or os.path.abspath(storage.location) != os.path.abspath(settings.MEDIA_ROOT):
        report.update(status="unsupported", complete=False)
        report["incompleteReasons"] = ["only_default_local_media_storage_is_supported"]
        return report
    # This is an observation, never a claim that any long-running task is dead.
    report["pendingTasks"] = {item["status"]: item["count"] for item in AnalysisTask.objects.filter(
        status__in=["queued", "running"]).values("status").annotate(count=Count("id"))}
    referenced, artifacts = set(), {}

    def consume(queryset, counter):
        for item in queryset.iterator(chunk_size=200):
            if counts["recordsChecked"] >= max_records:
                incomplete("record_limit")
                return
            counts["recordsChecked"] += 1
            counts[counter] += 1
            yield item

    def check_file(kind, item):
        key = item.storage_key
        if not key:
            finding(kind, "no_stored_file_key", item.pk)
            return
        referenced.add(key)
        if not valid_sha(item.content_sha256) or not isinstance(item.byte_size, int) or item.byte_size < 0:
            finding(kind, "invalid_file_metadata", item.pk, key)
            return
        try:
            with open_local_file(storage, key) as source:
                before = os.fstat(source.fileno())
                counts["registeredFilesChecked"] += 1
                if before.st_size != item.byte_size:
                    finding(kind, "size_mismatch", item.pk, key)
                    return
                if before.st_size > max_bytes - counts["bytesHashed"]:
                    counts["notChecked"] += 1
                    incomplete("byte_limit")
                    return
                digest, remaining = hashlib.sha256(), before.st_size
                while remaining:
                    chunk = source.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    counts["bytesHashed"] += len(chunk)
                    digest.update(chunk)
                after = os.fstat(source.fileno())
                signature = lambda info: (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                if signature(before) != signature(after):
                    finding(kind, "file_changed_during_read", item.pk, key)
                    incomplete("live_file_changed")
                elif remaining:
                    finding(kind, "size_mismatch", item.pk, key)
                elif digest.hexdigest() != item.content_sha256:
                    finding(kind, "checksum_mismatch", item.pk, key)
        except ArtifactReadError as error:
            finding(kind, str(error), item.pk, key)
            if str(error) == "storage_unavailable":
                incomplete("storage_read_error")
        except OSError:
            finding(kind, "storage_unavailable", item.pk, key)
            incomplete("storage_read_error")

    for artifact in consume(VisualizationArtifact.objects.select_related("task", "render_task").order_by("pk"), "artifactRecords"):
        artifacts[artifact.pk] = artifact.render_task_id
        reason = metadata_issue(artifact)
        if reason:
            finding("artifact", reason, artifact.pk, artifact.storage_key)
        check_file("artifact", artifact)
    for dataset in consume(ResearchDataset.objects.only("pk", "storage_key", "content_sha256", "byte_size").order_by("pk"), "datasetRecords"):
        check_file("dataset", dataset)
    reference_inventory_complete = "record_limit" not in report["incompleteReasons"]
    pending_renders = set()
    for task in consume(AnalysisTask.objects.filter(task_type="visualization").only("pk", "status", "result").order_by("pk"), "renderTaskRecords"):
        if task.status in {"queued", "running"}:
            pending_renders.add(task.pk)
        if task.status != "succeeded":
            continue
        entries = task.result.get("artifacts") if isinstance(task.result, dict) else None
        if not isinstance(entries, list) or not 0 < len(entries) <= 16:
            finding("task", "invalid_task_manifest", task.pk)
            continue
        for entry in entries:
            identifier = entry.get("id") if isinstance(entry, dict) else None
            if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier < 1:
                finding("task", "invalid_task_manifest", task.pk)
            elif reference_inventory_complete and artifacts.get(identifier) != task.pk:
                finding("task", "manifest_artifact_record_missing_or_mismatched", task.pk)

    # No arbitrary user paths or external object listing. Inspect only namespaces
    # written by this project, using no-follow directory FDs throughout.
    root_fd = None
    try:
        root_fd = os.open(storage.location, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for prefix in ("analysis-artifacts", "research-datasets"):
            if counts["filesystemEntriesChecked"] >= max_files:
                incomplete("filesystem_entry_limit")
                break
            try:
                info = os.stat(prefix, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(info.st_mode):
                finding("file", "unsafe_namespace_type", key=prefix)
                continue

            def scan_error(error):
                incomplete("filesystem_scan_error")
                finding("file", "filesystem_scan_error")

            for directory, dirs, files, fd in os.fwalk(prefix, follow_symlinks=False, dir_fd=root_fd, onerror=scan_error):
                stop = False
                for name in list(dirs) + files:
                    if counts["filesystemEntriesChecked"] >= max_files:
                        incomplete("filesystem_entry_limit")
                        stop = True
                        break
                    counts["filesystemEntriesChecked"] += 1
                    key = f"{directory}/{name}"
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if name in dirs:
                        if not stat.S_ISDIR(info.st_mode):
                            finding("file", "unsafe_file_type", key=key)
                            dirs.remove(name)
                        continue
                    if not stat.S_ISREG(info.st_mode):
                        finding("file", "unsafe_file_type", key=key)
                        continue
                    if key not in referenced:
                        if not reference_inventory_complete:
                            counts["notChecked"] += 1
                            incomplete("file_references_not_fully_checked")
                            continue
                        counts["unregisteredCandidates"] += 1
                        parts = Path(key).parts
                        active_path = (prefix == "analysis-artifacts" and len(parts) >= 5
                            and parts[3].isdigit() and int(parts[3]) in pending_renders)
                        finding("file", "unregistered_path_with_active_task_id" if active_path else "unregistered_file_candidate", key=key)
                if stop:
                    break
    except OSError:
        incomplete("filesystem_scan_error")
        finding("file", "filesystem_scan_error")
    finally:
        if root_fd is not None:
            os.close(root_fd)
    report["status"] = "incomplete" if not report["complete"] else "findings" if counts["findingCount"] else "ok"
    return report
