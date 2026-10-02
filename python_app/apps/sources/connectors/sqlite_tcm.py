"""Read-only, root-confined adapter for the legacy herb/compound/target SQLite source."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from django.conf import settings


BATCH_SIZE = 250
MAX_TARGETS_PER_ROW = 100
_IDENTIFIER = re.compile(r"^\w+$", re.UNICODE)
_TARGET_DELIMITERS = re.compile(r"[;,，；/|]+")


class SQLiteSourceError(Exception):
    """Safe error for legacy SQLite connection and schema failures."""


@dataclass(frozen=True)
class SQLiteSourceSnapshot:
    checksum_sha256: str
    file_size: int
    row_count: int
    columns: tuple[str, ...]

def validate_sqlite_source_config(config: dict) -> dict[str, str]:
    expected = {
        "databaseFile": "database file",
        "table": "table",
        "herbColumn": "herb column",
        "compoundColumn": "compound column",
        "targetColumn": "target column",
    }
    parsed = {}
    for key, label in expected.items():
        value = config.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SQLiteSourceError(f"请设置有效的{label}。")
        parsed[key] = value.strip()
    file_name = Path(parsed["databaseFile"])
    if file_name.is_absolute() or ".." in file_name.parts or "\x00" in parsed["databaseFile"]:
        raise SQLiteSourceError("数据库文件必须是受控目录内的相对路径。")
    for key in ("table", "herbColumn", "compoundColumn", "targetColumn"):
        if not _IDENTIFIER.fullmatch(parsed[key]):
            raise SQLiteSourceError(f"数据表字段映射 {key} 只允许字母、数字和下划线。")
    return parsed


def _source_path(config: dict) -> tuple[Path, dict[str, str]]:
    parsed = validate_sqlite_source_config(config)
    root_value = str(getattr(settings, "SQLITE_SOURCE_ROOT", "") or "").strip()
    if not root_value:
        raise SQLiteSourceError("服务器尚未配置 SQLITE_SOURCE_ROOT，暂不能连接本地数据文件。")
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise SQLiteSourceError("服务器配置的 SQLite 数据目录不可用。")
    path = (root / parsed["databaseFile"]).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise SQLiteSourceError("数据库文件必须位于服务器配置的数据目录内。") from exc
    if not path.is_file():
        raise SQLiteSourceError("服务器受控数据目录中找不到指定的 SQLite 文件。")
    try:
        size = path.stat().st_size
        wal = Path(f"{path}-wal")
        if wal.exists():
            size += wal.stat().st_size
    except OSError as exc:
        raise SQLiteSourceError("无法读取 SQLite 文件信息。") from exc
    if size > settings.SQLITE_SOURCE_MAX_BYTES:
        raise SQLiteSourceError("SQLite 文件超过配置的导入大小限制。")
    return path, parsed


def _connect(path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=10)
        connection.execute("PRAGMA query_only = ON")
        return connection
    except sqlite3.Error as exc:
        raise SQLiteSourceError("无法以只读方式打开 SQLite 文件。") from exc


def _hash_database(path: Path) -> str:
    digest = hashlib.sha256()
    related_files = (path, Path(f"{path}-wal"))
    total_size = 0
    try:
        for related in related_files:
            if not related.is_file():
                continue
            digest.update(related.name.encode("utf-8"))
            with related.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    total_size += len(chunk)
                    if total_size > settings.SQLITE_SOURCE_MAX_BYTES:
                        raise SQLiteSourceError("SQLite 文件超过配置的导入大小限制。")
                    digest.update(chunk)
    except OSError as exc:
        raise SQLiteSourceError("无法计算 SQLite 文件校验值。") from exc
    if total_size == 0:
        raise SQLiteSourceError("SQLite 文件为空。")
    return digest.hexdigest()


def _quoted(identifier: str) -> str:
    if not _IDENTIFIER.fullmatch(identifier):
        raise SQLiteSourceError("数据表字段映射无效。")
    return f'"{identifier}"'


def inspect_sqlite_source(configuration: dict) -> SQLiteSourceSnapshot:
    path, config = _source_path(configuration)
    checksum = _hash_database(path)
    connection = _connect(path)
    try:
        columns = tuple(
            str(column[1]) for column in connection.execute(f"PRAGMA table_info({_quoted(config['table'])})")
        )
        if not columns:
            raise SQLiteSourceError("指定的数据表不存在或没有可读取字段。")
        required = {config["herbColumn"], config["compoundColumn"], config["targetColumn"]}
        missing = required - set(columns)
        if missing:
            raise SQLiteSourceError(f"数据表缺少所需字段：{', '.join(sorted(missing))}。")
        connection.execute(f"SELECT rowid FROM {_quoted(config['table'])} LIMIT 0")
        row_count = int(connection.execute(f"SELECT COUNT(*) FROM {_quoted(config['table'])}").fetchone()[0])
    except sqlite3.Error as exc:
        raise SQLiteSourceError("无法检查 SQLite 数据表，请核对表名和字段映射。") from exc
    finally:
        connection.close()
    if row_count > settings.SQLITE_SOURCE_MAX_ROWS:
        raise SQLiteSourceError("SQLite 数据表超过配置的最大导入行数。")
    if _hash_database(path) != checksum:
        raise SQLiteSourceError("SQLite 文件在连接检查期间发生变化，请暂停写入后重试。")
    return SQLiteSourceSnapshot(checksum, path.stat().st_size, row_count, columns)


def iter_source_rows(configuration: dict) -> Iterator[tuple[int, object, object, object]]:
    path, config = _source_path(configuration)
    connection = _connect(path)
    query = (
        f"SELECT rowid AS __source_rowid, {_quoted(config['herbColumn'])}, "
        f"{_quoted(config['compoundColumn'])}, {_quoted(config['targetColumn'])} "
        f"FROM {_quoted(config['table'])} WHERE rowid > ? ORDER BY rowid LIMIT ?"
    )
    cursor = -(2**63)
    try:
        while True:
            try:
                rows = connection.execute(query, (cursor, BATCH_SIZE)).fetchall()
            except sqlite3.Error as exc:
                raise SQLiteSourceError("无法读取数据表；请确认该表支持 SQLite rowid。") from exc
            if not rows:
                break
            for row in rows:
                row_id = int(row[0])
                cursor = row_id
                yield row_id, row[1], row[2], row[3]
    finally:
        connection.close()


def clean_cell(value: object) -> str:
    return "" if value is None else str(value).strip()


def split_targets(value: object) -> list[str]:
    return [item.strip() for item in _TARGET_DELIMITERS.split(clean_cell(value)) if item.strip()]
