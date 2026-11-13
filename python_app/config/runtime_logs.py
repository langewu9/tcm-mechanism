"""Bounded, allowlisted diagnostics; never expose or parse arbitrary server logs.

The Linux API/worker processes share four rotating JSONL files and an advisory
lock. These are operational hints, not durable audit evidence. Business work
must continue if the diagnostic disk is unavailable.
"""

from contextlib import contextmanager
import errno
import json
import logging
import os
from pathlib import Path
import re
import stat
import time
import traceback
import uuid

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime


logger = logging.getLogger(__name__)
FILE_BYTES = 1024 * 1024
BACKUPS = 3
SCAN_BYTES = 1024 * 1024
LINE_BYTES = 8192
LOCK_TIMEOUT = 0.1
EVENTS = {
    "api.unhandled": ("error", "API 发生未处理异常。"),
    "api.server_error": ("error", "API 暂时无法完成请求。"),
    "task.queue_unavailable": ("error", "任务无法提交到分析队列。"),
    "proteomics.rejected": ("warning", "蛋白组学分析输入未通过检查。"),
    "proteomics.failed": ("error", "蛋白组学分析发生异常。"),
    "case.rejected": ("warning", "医案分析输入或模型响应未通过检查。"),
    "case.failed": ("error", "医案分析发生异常。"),
    "assistant.rejected": ("warning", "科研助手输入或模型响应未通过检查。"),
    "assistant.failed": ("error", "科研助手发生异常。"),
    "external.rejected": ("warning", "外部分析未通过检查或服务暂不可用。"),
    "external.failed": ("error", "外部分析发生异常。"),
    "integration.failed": ("error", "管理员连接检查发生异常。"),
    "visualization.rejected": ("warning", "图表输入未通过检查。"),
    "visualization.failed": ("error", "图表生成发生异常。"),
    "complete_evidence.rejected": ("warning", "完整本地分析输入未通过检查。"),
    "complete_evidence.failed": ("error", "完整本地分析发生异常。"),
}
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_.<>:-]{0,159}\Z")


class RuntimeLogUnavailable(Exception):
    pass


def _identifier(value):
    return value if isinstance(value, str) and IDENTIFIER.fullmatch(value) else None


def _uuid(value):
    try:
        return str(uuid.UUID(str(value))) if value else None
    except (ValueError, TypeError, AttributeError):
        return None


def _positive_int(value):
    return value if type(value) is int and 0 < value <= 9223372036854775807 else None


def _frames(exception):
    # No exception messages, source lines, filenames, chained values or locals.
    frames = []
    if exception is not None:
        for frame, line in traceback.walk_tb(exception.__traceback__):
            module = _identifier(frame.f_globals.get("__name__"))
            function = _identifier(frame.f_code.co_name)
            if module and function:
                frames.append({"module": module, "function": function, "line": line})
    return frames[-12:]


def _open_regular(path, flags):
    # The root is deployment configuration, never a URL/query parameter. Refuse
    # symlinks and special files even inside that private directory.
    if path.is_symlink():
        raise OSError("Diagnostic symlink refused")
    fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), 0o600)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise OSError("Diagnostic special file refused")
    return fd


@contextmanager
def _locked(directory, *, write):
    # Containers and supported production hosts are Linux. Import lazily so an
    # unavailable file-lock facility cannot break business application startup.
    import fcntl

    if directory.is_symlink() or not directory.is_dir():
        raise OSError("Diagnostic directory unavailable")
    fd = _open_regular(directory / ".lock", os.O_RDWR | os.O_CREAT)
    try:
        deadline = time.monotonic() + LOCK_TIMEOUT
        mode = fcntl.LOCK_EX if write else fcntl.LOCK_SH
        while True:
            try:
                fcntl.flock(fd, mode | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN} or time.monotonic() >= deadline:
                    raise
                time.sleep(0.005)
        yield
    finally:
        os.close(fd)


def _file(directory, index=0):
    return directory / ("events.jsonl" + (f".{index}" if index else ""))


def record_runtime_event(event, *, request=None, task_id=None, exception=None, status_code=None):
    level, message = EVENTS[event]
    match = getattr(request, "resolver_match", None)
    record = {
        "id": str(uuid.uuid4()), "createdAt": timezone.now().isoformat(),
        "event": event, "level": level, "message": message,
        "requestId": _uuid(getattr(request, "request_id", None)),
        "taskId": _positive_int(task_id),
        "operation": _identifier(getattr(match, "view_name", None)),
        "method": getattr(request, "method", None) if getattr(request, "method", None) in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"} else None,
        "statusCode": status_code if type(status_code) is int and 100 <= status_code <= 599 else None,
        "exceptionType": _identifier(type(exception).__name__) if exception is not None else None,
        "frames": _frames(exception),
    }
    try:
        encoded = (json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > LINE_BYTES:
            raise ValueError("Diagnostic record too large")
        directory = Path(settings.RUNTIME_LOG_DIR)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with _locked(directory, write=True):
            current = _file(directory)
            if current.is_symlink():
                raise OSError("Diagnostic symlink refused")
            if current.exists() and current.stat().st_size + len(encoded) > FILE_BYTES:
                for index in range(BACKUPS, 0, -1):
                    previous = _file(directory, index - 1)
                    target = _file(directory, index)
                    if previous.is_symlink() or target.is_symlink():
                        raise OSError("Diagnostic symlink refused")
                    if previous.exists():
                        os.replace(previous, target)
            fd = _open_regular(current, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
            with os.fdopen(fd, "wb") as output:
                output.write(encoded)
        return True
    except (OSError, ValueError, ImportError) as exc:
        # Never log the exception string: it can contain a filesystem path.
        logger.warning("Runtime diagnostic recording unavailable error_type=%s", type(exc).__name__)
        return False


def _clean_record(raw):
    # Reconstruct from an allowlist on read as well. Ignore additional fields in
    # old/manually altered files; never return raw message or arbitrary JSON.
    if not isinstance(raw, dict) or raw.get("event") not in EVENTS:
        return None
    stamp = raw.get("createdAt")
    if not isinstance(stamp, str) or len(stamp) > 40:
        return None
    date = parse_datetime(stamp)
    record_id = _uuid(raw.get("id"))
    if date is None or timezone.is_naive(date) or record_id is None:
        return None
    level, message = EVENTS[raw["event"]]
    frames = []
    for frame in raw.get("frames", [])[:12] if isinstance(raw.get("frames"), list) else []:
        if not isinstance(frame, dict):
            continue
        module, function, line = _identifier(frame.get("module")), _identifier(frame.get("function")), _positive_int(frame.get("line"))
        if module and function and line:
            frames.append({"module": module, "function": function, "line": line})
    return {
        "id": record_id, "createdAt": date.isoformat(), "event": raw["event"],
        "level": level, "message": message, "requestId": _uuid(raw.get("requestId")),
        "taskId": _positive_int(raw.get("taskId")), "operation": _identifier(raw.get("operation")),
        "method": raw.get("method") if raw.get("method") in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"} else None,
        "statusCode": raw.get("statusCode") if type(raw.get("statusCode")) is int and 100 <= raw["statusCode"] <= 599 else None,
        "exceptionType": _identifier(raw.get("exceptionType")), "frames": frames,
    }


def query_runtime_events(*, limit=50, request_id=None, task_id=None, level=None, since=None):
    directory = Path(settings.RUNTIME_LOG_DIR)
    result = {"results": [], "limit": limit, "hasMore": False, "scanTruncated": False, "skippedRecords": 0}
    remaining = SCAN_BYTES
    try:
        if not directory.exists() and not directory.is_symlink():
            return result
        with _locked(directory, write=False):
            for index in range(BACKUPS + 1):
                path = _file(directory, index)
                if not path.exists() and not path.is_symlink():
                    continue
                if remaining <= 0:
                    result["scanTruncated"] = True
                    break
                fd = _open_regular(path, os.O_RDONLY)
                with os.fdopen(fd, "rb") as source:
                    size = os.fstat(source.fileno()).st_size
                    offset = max(0, size - remaining)
                    source.seek(offset)
                    content = source.read(remaining)
                remaining -= len(content)
                if offset:
                    result["scanTruncated"] = True
                    content = content.partition(b"\n")[2]
                for line_bytes in reversed(content.splitlines()):
                    try:
                        if len(line_bytes) > LINE_BYTES:
                            raise ValueError("Oversized diagnostic line")
                        entry = _clean_record(json.loads(line_bytes))
                    except (ValueError, TypeError, RecursionError):
                        entry = None
                    if entry is None:
                        result["skippedRecords"] += 1
                        continue
                    if request_id and entry["requestId"] != str(request_id):
                        continue
                    if task_id and entry["taskId"] != task_id:
                        continue
                    if level and entry["level"] != level:
                        continue
                    if since and parse_datetime(entry["createdAt"]) < since:
                        continue
                    result["results"].append(entry)
        # File order is append order under one shared lock. Sort the bounded
        # window by event time for worker threads that prepared an event earlier.
        result["results"].sort(key=lambda entry: parse_datetime(entry["createdAt"]), reverse=True)
        result["hasMore"] = len(result["results"]) > limit
        result["results"] = result["results"][:limit]
        return result
    except (OSError, ValueError, ImportError) as exc:
        raise RuntimeLogUnavailable from exc
