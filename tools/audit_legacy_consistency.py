"""Read-only reconciliation of a bounded TCMSP workbook sample and local stack.

Run `extract` with bundled Python (pandas/openpyxl), then `compare` with the
Django venv. Reports contain actual comparisons, not previously saved PASS flags.
Neither operation imports data, updates tasks, changes sources or calls models.
"""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def clean(value):
    return "" if value is None else str(value).strip()


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def delta(expected, actual):
    missing, unexpected = Counter(expected) - Counter(actual), Counter(actual) - Counter(expected)
    return {"matches": not missing and not unexpected, "missing": sum(missing.values()),
            "unexpected": sum(unexpected.values())}


def extract(args):
    import openpyxl
    import pandas as pd
    from backend import data_service as main
    from backend.source_catalog import SOURCE_FILES
    path = args.workbook.resolve()
    before = digest(path)
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
    try:
        sheet = workbook.active
        headers = [clean(cell.value) for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
        columns = [SOURCE_FILES["tcmsp"][key] for key in ("herb", "component", "target")]
        positions = [headers.index(column) for column in columns]
        rows = []
        for cells in sheet.iter_rows(min_row=2):
            selected = [cells[index] for index in positions]
            if any(cell.data_type == "f" for cell in selected):
                raise ValueError("Formula cells need an explicit cached-value review before audit.")
            values = [clean(cell.value) for cell in selected]
            if not any(values):
                continue
            rows.append({"sourceRow": cells[0].row, "values": values,
                         "cells": [cell.coordinate for cell in selected]})
            if len(rows) >= args.rows:
                break
        sheet_name = sheet.title
    finally:
        workbook.close()
    if not rows:
        raise ValueError("No source rows to compare.")
    query = rows[0]["values"][0]
    frame = pd.DataFrame([row["values"] for row in rows], columns=columns)
    # Execute the frozen functions against the same bounded in-memory records;
    # do not let the reference code discover external/Windows data directories.
    def source_frame(provider):
        return frame if provider == "tcmsp" else pd.DataFrame(columns=main.SOURCE_FILES[provider]["columns"])
    with patch.object(main, "_cache", return_value=None), patch.object(main, "load_source", side_effect=source_frame):
        excel_result = main.search_herb(query, limit=10000)
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("CREATE TABLE herb_component_target(source, herb, component, target)")
        connection.executemany("INSERT INTO herb_component_target VALUES(?,?,?,?)", [("tcmsp", *row["values"]) for row in rows])
        with patch.object(main, "_cache", return_value=connection):
            cached_result = main.search_herb(query, limit=10000)
    finally:
        connection.close()
    link_targets = {target for link in cached_result["links"] for target in link["targets"]}
    changed_cells = [row["cells"][2] for row in rows
                     if row["values"][2] and main._split_targets(row["values"][2]) != [row["values"][2]]]
    after = digest(path)
    if before != after:
        raise ValueError("Source workbook changed while being audited.")
    return {"sampleOnly": True, "sourcePath": str(path), "sourceSha256": before,
            "sheet": sheet_name, "columns": columns, "rows": rows,
            "mainReference": {"codeSha256": digest(ROOT / "backend/data_service.py"),
                              "query": query, "excelCounts": excel_result["counts"],
                              "cacheCounts": cached_result["counts"], "cacheLinkTargetCount": len(link_targets),
                              "delimiterCells": changed_cells}}


def compare(args):
    sys.path.insert(0, str(ROOT / "python_app"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()
    from django.conf import settings
    from django.core.files.storage import default_storage
    from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, VisualizationArtifact
    from apps.core.services.visualization import build_chart_payload
    from apps.sources.connectors.sqlite_tcm import _source_path, inspect_sqlite_source
    assert settings.DEBUG and settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3", "Use only the isolated local preview."
    sample = json.loads(args.sample.read_text())
    source = DataSource.objects.get(pk=args.source_id)
    if source.configuration.get("targetCellMode") != "single":
        raise ValueError("This TCMSP audit requires reviewed single-target cells.")
    path, config = _source_path(source.configuration)
    if args.output.resolve().is_relative_to(Path(settings.SQLITE_SOURCE_ROOT).resolve()):
        raise ValueError("Audit reports must not be written into the source database directory.")
    manifest = json.loads(path.with_suffix(".manifest.json").read_text())
    before = digest(path)
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as database:
        database.execute("PRAGMA query_only = ON")
        sqlite_rows = [(row[0], *[clean(value) for value in row[1:]]) for row in database.execute(
            f'SELECT rowid,"{config["herbColumn"]}","{config["compoundColumn"]}","{config["targetColumn"]}" FROM "{config["table"]}" ORDER BY rowid')]
        embedded = {key: json.loads(value) for key, value in database.execute("SELECT key,value FROM source_manifest")}
        row_origins = [(row_id, json.loads(extra)) for row_id, extra in database.execute(f'SELECT rowid,extra FROM "{config["table"]}" ORDER BY rowid')]
    original_rows = [(row["sourceRow"], *row["values"]) for row in sample["rows"]]
    expected_records, expected_entities = [], set()
    for row_id, herb, compound, target in original_rows:
        for kind, value in (("herb", herb), ("compound", compound), ("protein", target)):
            if value:
                expected_entities.add((kind, value))
        if herb and compound:
            expected_records.append((row_id, "contains", herb, compound))
        if compound and target:
            expected_records.append((row_id, "targets", compound, target))
    relations = list(EvidenceRelation.objects.filter(source_release__source=source, is_active=True).select_related("subject", "object", "source_release"))
    actual_records = [(row.metadata.get("sourceRowId"), row.relation_type, row.subject.label, row.object.label) for row in relations]
    entities = list(KnowledgeEntity.objects.filter(source_release__source=source, is_active=True))
    task = AnalysisTask.objects.get(pk=args.task_id)
    result = task.result
    payload = build_chart_payload(task, "evidence_network")
    live_ids = {entity.pk for entity in entities}
    expected_links = [(f"entity:{row.subject_id}", f"entity:{row.object_id}", row.source_record_id, row.source_release_id) for row in relations]
    saved_links = [(row["source"], row["target"], row["sourceRecordId"], row["sourceReleaseId"]) for row in result["network"]["links"]]
    unique_edges = {tuple(sorted((left, right))) for left, right, *_ in expected_links}
    r_edges = {tuple(sorted((edge["source"], edge["target"]))) for edge in payload["edges"]}
    files = list(VisualizationArtifact.objects.filter(task=task, chart_key="evidence_network", input_sha256=payload["inputSha256"]))
    checks = {
        "workbookUnchanged": digest(sample["sourcePath"]) == sample["sourceSha256"],
        "manifestMatchesWorkbook": manifest["sourceSha256"] == sample["sourceSha256"] == embedded["sourceSha256"],
        "sqliteFileMatchesManifest": before == manifest["previewSha256"],
        "sampleIsExplicitlyBounded": manifest["completeDataset"] is False and len(original_rows) == manifest["sampleRows"],
        "rowOrigins": all(origin == {"workbookSha256": sample["sourceSha256"], "sheet": sample["sheet"], "sourceRow": row_id}
                          for row_id, origin in row_origins) and len(row_origins) == len(original_rows),
        "workbookToSqlite": delta(original_rows, sqlite_rows),
        "workbookToEvidence": delta(expected_records, actual_records),
        "workbookToEntities": delta(expected_entities, [(entity.entity_type, entity.label) for entity in entities]),
        "noInactiveEndpoints": all(row.subject.is_active and row.object.is_active for row in relations),
        "releaseChecksum": all(row.source_release.checksum_sha256 == inspect_sqlite_source(source.configuration).checksum_sha256 for row in relations[:1]),
        "snapshotEvidenceIds": {row["id"] for row in result["evidenceRecords"]} == {row.pk for row in relations},
        "snapshotEvidenceFields": delta(
            [(row.pk, row.subject_id, row.object_id, row.subject.label, row.object.label, row.relation_type, row.source_record_id, row.source_release_id, row.source_release.version) for row in relations],
            [(row["id"], row["subjectId"], row["objectId"], row["subject"], row["object"], row["relationType"], row["sourceRecordId"], row["sourceReleaseId"], row["sourceVersion"]) for row in result["evidenceRecords"]]),
        "snapshotLinks": delta(expected_links, saved_links),
        "snapshotNodes": {node["entityId"] for node in result["network"]["nodes"]} == live_ids,
        "snapshotNodeLabels": delta([(entity.pk, entity.label, entity.stable_id) for entity in entities],
                                    [(node["entityId"], node["label"], node["stableId"]) for node in result["network"]["nodes"]]),
        "rNodes": {node["id"] for node in payload["data"]} == {f"entity:{pk}" for pk in live_ids},
        "rEdges": unique_edges == r_edges,
        "fourPrivateArtifacts": {item.file_format for item in files} == {"svg", "png", "pdf", "html"},
        "artifactBytesAndOwner": bool(files) and all(item.owner_id == task.owner_id and digest(default_storage.path(item.storage_key)) == item.content_sha256 for item in files),
        "sourceSqliteUnchanged": digest(path) == before,
    }
    if args.http:
        from smoke_local_workspace import LocalClient
        administrator = LocalClient(json.loads((ROOT / "python_app/var/local-preview-login.json").read_text()))
        _, response = administrator.request("/api/v1/catalog/herb-evidence/batch/", method="POST", data={"queryType": result["queryType"], "queries": result["queries"]})
        api_records = {row["id"] for item in response["results"] for row in item["relations"]}
        checks["httpEvidenceIds"] = api_records == {row.pk for row in relations}
        checks["httpResultMatchesSavedQuery"] = response["resultSha256"] == result["resultSha256"]
    passed = all(value["matches"] if isinstance(value, dict) else value for value in checks.values())
    return {"passed": passed, "sampleOnly": True, "sourceId": source.pk, "taskId": task.pk,
            "sourceSha256": sample["sourceSha256"], "sourceRange": f'{sample["sheet"]}!A1:C{max(row[0] for row in original_rows)}',
            "counts": {"workbookRows": len(original_rows), "sqliteRows": len(sqlite_rows), "entities": len(entities),
                       "sourceRecords": len(relations), "uniqueEdges": len(unique_edges), "rNodes": len(payload["data"]), "rEdges": len(payload["edges"])},
            "checks": checks, "mainReference": sample["mainReference"],
            "targetIdentifierStatuses": dict(Counter(entity.metadata.get("identifierStatus", "unspecified") for entity in entities if entity.entity_type == "protein")),
            "limitations": ["Only the declared TCMSP sample is compared.", "The frozen main splits punctuation within some protein names; this difference is recorded, not copied.", "No canonical HGNC/UniProt identity or biological validity is established by row consistency."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    extraction = commands.add_parser("extract")
    extraction.add_argument("workbook", type=Path)
    extraction.add_argument("--rows", type=int, default=100)
    audit = commands.add_parser("compare")
    audit.add_argument("sample", type=Path)
    audit.add_argument("--source-id", type=int, required=True)
    audit.add_argument("--task-id", type=int, required=True)
    audit.add_argument("--http", action="store_true")
    for command in (extraction, audit):
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    original_input = args.workbook if args.command == "extract" else args.sample
    if args.output.suffix.lower() != ".json" or args.output.resolve() == original_input.resolve():
        parser.error("Write the report to a separate .json file; source inputs cannot be overwritten.")
    if args.command == "extract" and not 1 <= args.rows <= 10000:
        parser.error("Sample rows must be between 1 and 10000.")
    report = extract(args) if args.command == "extract" else compare(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, ensure_ascii=False, indent=2))
    if report.get("passed") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
