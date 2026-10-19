"""Prepare an explicitly bounded legacy Excel sample for the existing SQLite importer.

Keeps original workbook bytes unchanged; source row IDs and checksums are retained.
The generated SQLite contains a sample, not the complete source database.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.source_catalog import SOURCE_FILES


def prepare(workbook_path, *, provider, output, row_limit=100):
    if not 1 <= row_limit <= 10000:
        raise ValueError("Preview rows must be between 1 and 10000.")
    output = Path(output)
    if output.exists():
        raise FileExistsError("Preview output already exists; never overwrite a registered source.")
    workbook_path = Path(workbook_path)
    source_sha256 = hashlib.sha256(workbook_path.read_bytes()).hexdigest()
    mapping = SOURCE_FILES[provider]
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        header = [str(value).strip() if value is not None else "" for value in next(sheet.iter_rows(values_only=True))]
        positions = [header.index(mapping[field]) for field in ["herb", "component", "target"]]
        records = []
        for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
            values = [str(row[index]).strip() if index < len(row) and row[index] is not None else "" for index in positions]
            if not any(values):
                continue
            if any(len(value) > 300 for value in values[:2]):
                raise ValueError(f"Source row {row_number} contains an oversized entity label; review it before importing.")
            records.append((row_number, provider, *values, json.dumps({"workbookSha256": source_sha256, "sheet": sheet.title, "sourceRow": row_number}, ensure_ascii=False)))
            if len(records) == row_limit:
                break
        if not records:
            raise ValueError("The source workbook has no preview records.")
        manifest = {"provider": provider, "sourceFilename": workbook_path.name, "sourceSha256": source_sha256, "sheet": sheet.title, "sourceColumns": [mapping[field] for field in ["herb", "component", "target"]], "rowLimit": row_limit, "sampleRows": len(records), "firstSourceRow": records[0][0], "lastSourceRow": records[-1][0], "completeDataset": False}
        output.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(output) as database:
            database.execute("CREATE TABLE herb_component_target (rowid INTEGER PRIMARY KEY, source TEXT, herb TEXT, component TEXT, target TEXT, extra TEXT)")
            database.executemany("INSERT INTO herb_component_target VALUES (?,?,?,?,?,?)", records)
            database.execute("CREATE TABLE source_manifest (key TEXT PRIMARY KEY, value TEXT)")
            database.executemany("INSERT INTO source_manifest VALUES (?,?)", [(key, json.dumps(value, ensure_ascii=False)) for key, value in manifest.items()])
        manifest["previewSha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
        output.with_suffix(".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        return manifest
    finally:
        workbook.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--provider", required=True, choices=SOURCE_FILES)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rows", type=int, default=100)
    args = parser.parse_args()
    print(json.dumps(prepare(args.workbook, provider=args.provider, output=args.output, row_limit=args.rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
