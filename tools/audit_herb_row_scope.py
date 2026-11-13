"""Read-only full-workbook check of the existing legacy row-join primitive.

Uses the production HerbRowSupport with in-memory relation adapters, without
importing a catalogue, changing tasks, calling APIs or certifying identities.
Run with the bundled Python/openpyxl; ORM and importer tests are separate.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import openpyxl


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "python_app/apps/core/services/herb_row_support.py"
SPACE = re.compile(r"\s+")


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def clean(value):
    return "" if value is None else str(value).strip()


def name_key(value):
    return SPACE.sub(" ", value.casefold())


@dataclass(slots=True)
class Edge:
    subject_id: tuple
    object_id: tuple
    source_release_id: int
    source_release: object
    metadata: dict


def scan(provider, filename, release_id, support_class):
    path = ROOT / "python_app/var/legacy-inputs" / filename
    before = sha256(path)
    release = SimpleNamespace(metadata={"connector": "sqlite-herb-compound-target"})
    by_herb, by_compound = defaultdict(list), defaultdict(list)
    labels, identity_proofs = {}, {}
    warnings = Counter()
    warning_examples = defaultdict(list)
    rows_seen, full_rows, formulas, blank_rows = 0, 0, 0, 0
    book = openpyxl.load_workbook(path, read_only=True, data_only=False)

    def warn(kind, row, detail):
        warnings[kind] += 1
        if len(warning_examples[kind]) < 5:
            warning_examples[kind].append({"row": row, **detail})

    try:
        sheet = book.active
        sheet_name = sheet.title
        header = [clean(cell.value) for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
        names = ("Chinese Character", "Compound Name", "Symbol") if provider == "hit" else ("中药", "成分", "靶点基因")
        positions = [header.index(name) for name in names]
        id_positions = [header.index(name) for name in ("Herb ID", "Compound Id", "Target ID")] if provider == "hit" else []
        ref_positions = [header.index(name) for name in ("Pubchem ID", "Chembl ID", "Uniprot")] if provider == "hit" else []
        for row_number, cells in enumerate(sheet.iter_rows(min_row=2), 2):
            rows_seen += 1
            if any(cell.data_type == "f" for cell in cells):
                formulas += 1
                warn("formula_requires_review", row_number, {})
                continue
            values = [clean(cells[index].value) for index in positions]
            if not any(values):
                blank_rows += 1
                continue
            keys = []
            for offset, (kind, value) in enumerate(zip(("herb", "compound", "target"), values)):
                source_id = clean(cells[id_positions[offset]].value) if id_positions else ""
                key = (provider, kind, "id", source_id) if source_id else (provider, kind, "name", name_key(value))
                keys.append(key)
                if not value:
                    warn("missing_entity_label", row_number, {"kind": kind})
                if len(value) > 300:
                    warn("entity_label_over_300", row_number, {"kind": kind})
                if id_positions and not source_id:
                    warn("missing_source_id", row_number, {"kind": kind})
                if source_id:
                    refs = ((clean(cells[ref_positions[0]].value), clean(cells[ref_positions[1]].value)) if kind == "compound"
                            else (clean(cells[ref_positions[2]].value),) if kind == "target" else ())
                    proof = (value, refs)
                    if key in identity_proofs and identity_proofs[key][0] != proof:
                        warn("source_id_assertion_conflict", row_number, {"kind": kind, "sourceId": source_id,
                             "firstRow": identity_proofs[key][1], "firstAssertion": identity_proofs[key][0], "assertion": proof})
                    else:
                        identity_proofs.setdefault(key, (proof, row_number))
            herb_key, compound_key, target_key = keys
            labels[herb_key] = values[0]
            # Keep empty-target contains rows and orphan targets, just as the
            # importer does; only a complete triple can yield a paired proof.
            if values[0] and values[1]:
                by_herb[herb_key].append((row_number, compound_key, target_key if values[2] else None))
            if values[1] and values[2]:
                by_compound[compound_key].append(Edge(compound_key, target_key, release_id, release, {"sourceRowId": row_number}))
            if all(values):
                full_rows += 1
            if rows_seen % 50000 == 0:
                print(json.dumps({"provider": provider, "rowsRead": rows_seen}), flush=True)
    finally:
        book.close()

    cases, issues = [], []
    paired_count = rejected_foreign = candidate_count = 0
    duplicate_proofs = 0
    for herb_key, rows in by_herb.items():
        herb_edges = [Edge(herb_key, compound, release_id, release, {"sourceRowId": row}) for row, compound, _ in rows]
        support = support_class(herb_edges)
        # Independent oracle: exact raw herb rows, compound key and target key.
        expected = Counter((row, compound, target) for row, compound, target in rows if target is not None)
        actual = Counter()
        targets, broad_targets = set(), set()
        candidates = 0
        for compound in {compound for _, compound, _ in rows}:
            for target_edge in by_compound[compound]:
                candidates += 1
                broad_targets.add(target_edge.object_id)
                matching = support.for_target(target_edge)
                if not matching:
                    rejected_foreign += 1
                for herb_edge in matching:
                    actual[(herb_edge.metadata["sourceRowId"], compound, target_edge.object_id)] += 1
                    targets.add(target_edge.object_id)
        missing, extra = expected - actual, actual - expected
        if missing or extra:
            issues.append({"herb": labels[herb_key], "missingProofs": sum(missing.values()), "unexpectedProofs": sum(extra.values())})
        row_targets = [target for _, _, target in rows if target is not None]
        duplicate_proofs += len(row_targets) - len(set(row_targets))
        paired_count += sum(actual.values())
        candidate_count += candidates
        cases.append({"herb": labels[herb_key], "sourceHerbKey": list(herb_key), "rawTripleRows": sum(expected.values()),
                      "sourceTargetKeys": len(targets), "compoundTraversalTargetKeys": len(broad_targets),
                      "candidateRowsExamined": candidates, "exactRowProofsMatch": not missing and not extra})
    cases.sort(key=lambda item: item["herb"])
    after = sha256(path)
    if after != before:
        issues.append({"kind": "workbook_changed_during_read"})
    # A negative control using a shared-compound-only join must differ wherever
    # the data contains foreign herb rows. No production code is monkeypatched.
    negative_detected = rejected_foreign > 0
    if not negative_detected:
        issues.append({"kind": "negative_control_did_not_exercise_foreign_rows"})
    return {"provider": provider, "file": filename, "sheet": sheet_name, "sha256": before,
            "workbookUnchanged": before == after, "rowsRead": rows_seen, "completeTripleRows": full_rows,
            "blankRows": blank_rows, "formulaRowsNotEvaluated": formulas, "herbKeysChecked": len(cases),
            "pairedSourceProofs": paired_count, "candidateRowsExamined": candidate_count,
            "foreignRowCandidatesRejected": rejected_foreign, "repeatTargetProofRowsRetained": duplicate_proofs,
            "allRawTripleProofsRetained": paired_count == full_rows,
            "sharedCompoundOnlyNegativeControlDetected": negative_detected,
            "rowJoinPassed": not issues and paired_count == full_rows, "issues": issues,
            "sourceReadinessWarnings": dict(warnings), "warningExamples": dict(warning_examples), "herbs": cases,
            "scope": "full file, in-memory production row-support primitive; no ORM query limits/import/API or biological verification"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    destination = args.output.resolve()
    if (not destination.is_relative_to((ROOT / "python_app/var").resolve())
            or destination.suffix != ".json" or destination.exists()):
        parser.error("Use a new private JSON path under python_app/var; never overwrite evidence.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location("audit_production_row_support", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    results = [scan(provider, filename, index, module.HerbRowSupport) for index, (provider, filename) in enumerate([
        ("hit", "HIT数据库全部.xlsx"), ("tcmsp", "tcmsp全部数据.xlsx")], 1)]
    result = {"rowJoinPassed": all(item["rowJoinPassed"] for item in results), "productionModuleSha256": sha256(MODULE),
              "workbooks": results, "externalCalls": False, "businessDatabaseTouched": False,
              "identityCertified": False, "scope": "two available full local workbooks; other providers not scanned"}
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({"rowJoinPassed": result["rowJoinPassed"], "report": str(destination), "workbooks": [
        {key: value for key, value in item.items() if key not in {"herbs", "warningExamples"}} for item in results]}, ensure_ascii=False), flush=True)
    if not result["rowJoinPassed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
