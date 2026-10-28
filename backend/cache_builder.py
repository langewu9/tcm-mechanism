from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import openpyxl

from .config import DATABASE_DIR, PROJECT_ROOT
from .source_catalog import SOURCE_FILES


CACHE_DB = PROJECT_ROOT / "tcm_pharmacology_platform" / "data_cache.db"


def _cell(row, index: int):
    value = row[index] if index is not None and index < len(row) else None
    return str(value).strip() if value is not None else ""


def _column_index(header: list[str], name: str) -> int:
    try:
        return header.index(name)
    except ValueError as exc:
        raise RuntimeError(f"Column {name!r} not found in {header}") from exc


def init_schema(con: sqlite3.Connection):
    con.executescript(
        """
        drop table if exists herb_component_target;
        drop table if exists disease_herb_target;
        drop table if exists disease_target;
        create table herb_component_target (
            source text not null,
            herb text,
            component text,
            target text,
            extra text
        );
        create table disease_herb_target (
            disease text,
            herb text,
            target text
        );
        create table disease_target (
            disease text,
            target text,
            source_file text
        );
        """
    )


def build_herb_tables(con: sqlite3.Connection):
    insert_sql = "insert into herb_component_target(source, herb, component, target, extra) values (?, ?, ?, ?, ?)"
    for source, meta in SOURCE_FILES.items():
        path = DATABASE_DIR / meta["file"]
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        header = [str(v).strip() if v is not None else "" for v in next(ws.iter_rows(values_only=True))]
        herb_i = _column_index(header, meta["herb"])
        comp_i = _column_index(header, meta["component"])
        target_i = _column_index(header, meta["target"])
        extra_indexes = [header.index(c) for c in meta["columns"] if c in header and c not in {meta["herb"], meta["component"], meta["target"]}]
        batch = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            herb = _cell(row, herb_i)
            comp = _cell(row, comp_i)
            target = _cell(row, target_i)
            if not (herb or comp or target):
                continue
            extra = {header[i]: _cell(row, i) for i in extra_indexes if _cell(row, i)}
            batch.append((source, herb, comp, target, json.dumps(extra, ensure_ascii=False)))
            if len(batch) >= 5000:
                con.executemany(insert_sql, batch)
                con.commit()
                batch.clear()
        if batch:
            con.executemany(insert_sql, batch)
            con.commit()
        wb.close()


def build_disease_tables(con: sqlite3.Connection):
    wb = openpyxl.load_workbook(DATABASE_DIR / "疾病_中药.xlsx", read_only=True, data_only=True)
    ws = wb.active
    header = [str(v).strip() if v is not None else "" for v in next(ws.iter_rows(values_only=True))]
    disease_i = _column_index(header, "疾病")
    herb_i = _column_index(header, "中药")
    target_i = _column_index(header, "靶点基因")
    batch = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        batch.append((_cell(row, disease_i), _cell(row, herb_i), _cell(row, target_i)))
        if len(batch) >= 5000:
            con.executemany("insert into disease_herb_target(disease, herb, target) values (?, ?, ?)", batch)
            con.commit()
            batch.clear()
    if batch:
        con.executemany("insert into disease_herb_target(disease, herb, target) values (?, ?, ?)", batch)
        con.commit()
    wb.close()

    wb = openpyxl.load_workbook(DATABASE_DIR / "combined_results.xlsx", read_only=True, data_only=True)
    ws = wb.active
    header = [str(v).strip() if v is not None else "" for v in next(ws.iter_rows(values_only=True))]
    target_i = _column_index(header, "靶点基因")
    disease_i = _column_index(header, "疾病")
    source_i = _column_index(header, "来源文件")
    batch = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        batch.append((_cell(row, disease_i), _cell(row, target_i), _cell(row, source_i)))
        if len(batch) >= 5000:
            con.executemany("insert into disease_target(disease, target, source_file) values (?, ?, ?)", batch)
            con.commit()
            batch.clear()
    if batch:
        con.executemany("insert into disease_target(disease, target, source_file) values (?, ?, ?)", batch)
        con.commit()
    wb.close()


def build_indexes(con: sqlite3.Connection):
    con.executescript(
        """
        create index idx_hct_herb on herb_component_target(herb);
        create index idx_hct_component on herb_component_target(component);
        create index idx_hct_target on herb_component_target(target);
        create index idx_dht_disease on disease_herb_target(disease);
        create index idx_dt_disease on disease_target(disease);
        """
    )
    con.commit()


def build_cache():
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(CACHE_DB) as con:
        init_schema(con)
        build_herb_tables(con)
        build_disease_tables(con)
        build_indexes(con)
    return CACHE_DB


if __name__ == "__main__":
    print(build_cache())

