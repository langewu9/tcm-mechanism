"""Validate published provenance and serve the exact bytes that were verified."""
import errno
import hashlib
from io import BytesIO
import os
from pathlib import PurePosixPath
import re
import stat

from django.core.files.storage import FileSystemStorage, default_storage
from rest_framework.exceptions import APIException

from .visualization import FORMAT_MIME_TYPES, MAX_ARTIFACT_BYTES


class ArtifactReadError(ValueError):
    """Reason codes only: never include private paths or storage exceptions."""


class ArtifactUnavailable(APIException):
    status_code = 503
    default_code = "artifact_unavailable"
    default_detail = "图表文件缺失、损坏或保存记录不一致，暂不能读取。请联系管理员核对任务编号；系统不会自动重新绘图。"


def positive_id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,18}", value):
        return int(value)
    return None


def valid_sha(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def safe_key_parts(key):
    if not isinstance(key, str) or not key or "\\" in key or "\x00" in key:
        raise ArtifactReadError("invalid_storage_key")
    parts = key.split("/")
    if PurePosixPath(key).is_absolute() or any(part in {"", ".", ".."} for part in parts):
        raise ArtifactReadError("invalid_storage_key")
    return parts


def metadata_issue(artifact):
    """Check existing fields only; do not infer or repair historical identity."""
    render, parent = artifact.render_task, artifact.task
    if render.status != "succeeded" or parent.status != "succeeded":
        return "unpublished_record"
    if (render.task_type != "visualization" or parent.task_type not in {"network", "proteomics"}
            or render.owner_id != artifact.owner_id or parent.owner_id != artifact.owner_id
            or (render.parent_task_id is not None and render.parent_task_id != parent.pk)):
        return "source_identity_mismatch"
    params, result = render.input_parameters, render.result
    if not isinstance(params, dict) or not isinstance(result, dict):
        return "manifest_mismatch"
    if (params.get("analysisKind") != "r_visualization" or params.get("chartKey") != artifact.chart_key
            or positive_id(params.get("parentTaskId")) != parent.pk
            or params.get("inputSha256") != artifact.input_sha256
            or positive_id(result.get("taskId")) != render.pk or positive_id(result.get("parentTaskId")) != parent.pk
            or result.get("chartKey") != artifact.chart_key or result.get("inputSha256") != artifact.input_sha256
            or result.get("status", "succeeded") != "succeeded"):
        return "source_identity_mismatch"
    if (not valid_sha(artifact.content_sha256) or not valid_sha(artifact.input_sha256)
            or not isinstance(artifact.byte_size, int) or isinstance(artifact.byte_size, bool)
            or not 0 < artifact.byte_size <= MAX_ARTIFACT_BYTES
            or FORMAT_MIME_TYPES.get(artifact.file_format) != artifact.mime_type
            or not isinstance(result.get("rendererVersion"), str)
            or result["rendererVersion"][:80] != artifact.renderer_version):
        return "invalid_artifact_metadata"
    entries = result.get("artifacts")
    if not isinstance(entries, list) or not 0 < len(entries) <= 16:
        return "manifest_mismatch"
    matching = [item for item in entries if isinstance(item, dict)
        and type(item.get("id")) is int and item["id"] == artifact.pk]
    expected = {"format": artifact.file_format, "filename": artifact.filename, "mimeType": artifact.mime_type,
        "sha256": artifact.content_sha256, "byteSize": artifact.byte_size,
        "rendererVersion": artifact.renderer_version,
        "downloadUrl": f"/api/v1/research/analysis-artifacts/{artifact.pk}/download/"}
    if (len(matching) != 1 or type(matching[0].get("byteSize")) is not int
            or any(matching[0].get(key) != value for key, value in expected.items())):
        return "manifest_mismatch"
    return None


def open_local_file(storage, key):
    """Use directory FDs so relative symlinks cannot escape the configured root."""
    parts = safe_key_parts(key)
    directory = None
    descriptor = None
    try:
        directory = os.open(storage.location, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ArtifactReadError("unsafe_file_type")
        stream = os.fdopen(descriptor, "rb")
        descriptor = None
        return stream
    except FileNotFoundError as exc:
        raise ArtifactReadError("file_missing") from exc
    except OSError as exc:
        code = "unsafe_file_type" if exc.errno in {errno.ELOOP, errno.ENOTDIR} else "storage_unavailable"
        raise ArtifactReadError(code) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory is not None:
            os.close(directory)


def open_stored_file(storage, key):
    safe_key_parts(key)
    if isinstance(storage, FileSystemStorage):
        return open_local_file(storage, key)
    try:
        return storage.open(key, "rb")
    except FileNotFoundError as exc:
        raise ArtifactReadError("file_missing") from exc
    except Exception as exc:
        raise ArtifactReadError("storage_unavailable") from exc


def verified_artifact_bytes(artifact, storage=None):
    issue = metadata_issue(artifact)
    if issue:
        raise ArtifactReadError(issue)
    storage = default_storage if storage is None else storage
    try:
        with open_stored_file(storage, artifact.storage_key) as source:
            chunks, count, digest = [], 0, hashlib.sha256()
            while True:
                chunk = source.read(min(64 * 1024, MAX_ARTIFACT_BYTES + 1 - count))
                if not chunk:
                    break
                count += len(chunk)
                if count > MAX_ARTIFACT_BYTES:
                    raise ArtifactReadError("size_limit_exceeded")
                digest.update(chunk)
                chunks.append(chunk)
            if count != artifact.byte_size:
                raise ArtifactReadError("size_mismatch")
            if digest.hexdigest() != artifact.content_sha256:
                raise ArtifactReadError("checksum_mismatch")
            # The response uses this immutable copy, never a second storage open.
            return BytesIO(b"".join(chunks))
    except ArtifactReadError:
        raise
    except Exception as exc:
        raise ArtifactReadError("storage_unavailable") from exc
