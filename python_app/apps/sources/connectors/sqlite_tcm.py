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
    table_row_counts: dict[str, int]

def validate_sqlite_source_config(config: dict) -> dict[str, str]:
    expected = {
        "databaseFile": "database file",
        "table": "table",
        "herbColumn": "herb column",
        "compoundColumn": "compound column",
        "targetColumn": "target column",
    }
    optional_mappings = {
        "diseaseTargetTable": ("diseaseColumn", "diseaseTargetColumn", "diseaseSourceColumn"),
        "diseaseHerbTargetTable": ("diseaseHerbColumn", "diseaseHerbHerbColumn", "diseaseHerbTargetColumn"),
    }
    parsed = {}
    target_mode = config.get("targetCellMode", "list")
    if not isinstance(target_mode, str) or target_mode not in {"single", "list"}:
        raise SQLiteSourceError("靶点字段内容必须选择 single 或 list。")
    parsed["targetCellMode"] = target_mode
    for key, label in expected.items():
        value = config.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SQLiteSourceError(f"请设置有效的{label}。")
        parsed[key] = value.strip()
    file_name = Path(parsed["databaseFile"])
    if file_name.is_absolute() or ".." in file_name.parts or "\x00" in parsed["databaseFile"]:
        raise SQLiteSourceError("数据库文件必须是受控目录内的相对路径。")
    for table_key, mapping_keys in optional_mappings.items():
        table_name = str(config.get(table_key, "") or "").strip()
        populated = [str(config.get(key, "") or "").strip() for key in mapping_keys]
        if table_name or any(populated):
            if not table_name or not all(populated):
                raise SQLiteSourceError(f"{table_key} 对应的数据表和全部字段映射必须一起填写。")
            parsed[table_key] = table_name
            parsed.update({key: value for key, value in zip(mapping_keys, populated)})
    for key in (
        "table", "herbColumn", "compoundColumn", "targetColumn",
        "diseaseTargetTable", "diseaseColumn", "diseaseTargetColumn", "diseaseSourceColumn",
        "diseaseHerbTargetTable", "diseaseHerbColumn", "diseaseHerbHerbColumn", "diseaseHerbTargetColumn",
    ):
        if key not in parsed:
            continue
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
        mappings = [("herb", "table", ("herbColumn", "compoundColumn", "targetColumn"))]
        if config.get("diseaseTargetTable"):
            mappings.append(("diseaseTarget", "diseaseTargetTable", ("diseaseColumn", "diseaseTargetColumn", "diseaseSourceColumn")))
        if config.get("diseaseHerbTargetTable"):
            mappings.append(("diseaseHerbTarget", "diseaseHerbTargetTable", ("diseaseHerbColumn", "diseaseHerbHerbColumn", "diseaseHerbTargetColumn")))
        columns = []
        table_row_counts = {}
        for _, table_key, column_keys in mappings:
            table = config[table_key]
            table_columns = tuple(
                str(column[1]) for column in connection.execute(f"PRAGMA table_info({_quoted(table)})")
            )
            if not table_columns:
                raise SQLiteSourceError(f"指定的数据表“{table}”不存在或没有可读取字段。")
            required = {config[key] for key in column_keys}
            missing = required - set(table_columns)
            if missing:
                raise SQLiteSourceError(f"数据表“{table}”缺少所需字段：{', '.join(sorted(missing))}。")
            connection.execute(f"SELECT rowid FROM {_quoted(table)} LIMIT 0")
            columns.extend(f"{table}.{column}" for column in table_columns)
            table_row_counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {_quoted(table)}").fetchone()[0])
    except sqlite3.Error as exc:
        raise SQLiteSourceError("无法检查 SQLite 数据表，请核对表名和字段映射。") from exc
    finally:
        connection.close()
    row_count = sum(table_row_counts.values())
    if row_count > settings.SQLITE_SOURCE_MAX_ROWS:
        raise SQLiteSourceError("SQLite 数据表超过配置的最大导入行数。")
    if _hash_database(path) != checksum:
        raise SQLiteSourceError("SQLite 文件在连接检查期间发生变化，请暂停写入后重试。")
    return SQLiteSourceSnapshot(checksum, path.stat().st_size, row_count, tuple(columns), table_row_counts)


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


def iter_configured_rows(configuration: dict) -> Iterator[tuple[str, int, object, object, object]]:
    """Yield rows from the three-table schema produced by main's cache_builder.py."""
    _, config = _source_path(configuration)
    yield from (("herb", *row) for row in iter_source_rows(configuration))
    table_specs = (
        ("diseaseTarget", "diseaseTargetTable", "diseaseColumn", "diseaseTargetColumn", "diseaseSourceColumn"),
        ("diseaseHerbTarget", "diseaseHerbTargetTable", "diseaseHerbColumn", "diseaseHerbHerbColumn", "diseaseHerbTargetColumn"),
    )
    for kind, table_key, first_column, second_column, third_column in table_specs:
        if not config.get(table_key):
            continue
        path, _ = _source_path(configuration)
        connection = _connect(path)
        table = _quoted(config[table_key])
        first = _quoted(config[first_column])
        second = _quoted(config[second_column])
        third = _quoted(config[third_column])
        query = f"SELECT rowid, {first}, {second}, {third} FROM {table} WHERE rowid > ? ORDER BY rowid LIMIT ?"
        cursor = -(2**63)
        try:
            while True:
                try:
                    rows = connection.execute(query, (cursor, BATCH_SIZE)).fetchall()
                except sqlite3.Error as exc:
                    raise SQLiteSourceError("无法读取来源数据表；请确认数据表支持 SQLite rowid。") from exc
                if not rows:
                    break
                for row in rows:
                    cursor = int(row[0])
                    yield kind, cursor, row[1], row[2], row[3]
        finally:
            connection.close()


def clean_cell(value: object) -> str:
    return "" if value is None else str(value).strip()


def split_targets(value: object) -> list[str]:
    return [item.strip() for item in _TARGET_DELIMITERS.split(clean_cell(value)) if item.strip()]
