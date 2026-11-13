"""Read complete selected herb rows for an isolated serial cap benchmark.

Does not edit workbooks, clean missing fields, import a catalogue or call APIs.
The first 2,000 complete unselected rows/provider provide bounded background;
they do not reproduce the full production catalogue size.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
CAPS = [300, 600, 1200, 2400, 4800, 12000]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def clean(value):
    return "" if value is None else str(value).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "python_app/var").resolve()) or output.exists() or output.suffix != ".json":
        parser.error("Use a new private JSON report path; never overwrite sources/evidence.")
    previous = json.loads((ROOT / "python_app/var/herb-row-validation-2026-10-21/full-workbook-row-scope.json").read_text())
    result = {"caps": CAPS, "workbooks": [], "cases": [], "rows": [], "externalCalls": False,
              "scope": "complete rows for eight selected herbs + bounded background, not full database import"}
    for workbook in previous["workbooks"]:
        provider = workbook["provider"]
        cases = sorted(workbook["herbs"], key=lambda row: (row["rawTripleRows"], row["herb"]))
        choices = [("median", cases[len(cases)//2]), ("p90", cases[len(cases)*9//10]),
                   ("reference", next(row for row in cases if row["herb"] == "石榴皮")), ("largest", cases[-1])]
        label_counts = Counter(row["herb"] for row in cases)
        assert all(label_counts[row["herb"]] == 1 for _, row in choices), "Review ambiguous herb names separately."
        selected_names = {row["herb"] for _, row in choices}
        path = ROOT / "python_app/var/legacy-inputs" / workbook["file"]
        assert digest(path) == workbook["sha256"]
        names = ("Chinese Character", "Compound Name", "Symbol") if provider == "hit" else ("中药", "成分", "靶点基因")
        chosen_counts, background_count = Counter(), 0
        book = openpyxl.load_workbook(path, read_only=True, data_only=False)
        try:
            sheet = book.active
            headers = [clean(cell.value) for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
            positions = [headers.index(name) for name in names]
            identity_columns = {"herbId": "Herb ID", "compoundId": "Compound Id", "targetId": "Target ID",
                                "targetSymbol": "Symbol", "uniprot": "Uniprot", "pubchem": "Pubchem ID", "chembl": "Chembl ID"}
            for row_id, cells in enumerate(sheet.iter_rows(min_row=2), 2):
                values = [clean(cells[index].value) for index in positions]
                if not all(values):
                    continue  # Missing-field records remain untouched, outside this benchmark.
                selected = values[0] in selected_names
                if not selected and background_count >= 2000:
                    continue
                assert not any(cell.data_type == "f" for cell in cells), "Formula needs separate review."
                record = None
                if provider == "hit":
                    record = {"schemaVersion": "legacy-source-identity-1", "workbookSha256": workbook["sha256"],
                              "sheet": sheet.title, "sourceRow": row_id,
                              "identity": {key: clean(cells[headers.index(column)].value) for key, column in identity_columns.items()},
                              "rawFields": dict(zip(headers, [cell.value for cell in cells]))}
                    assert all(record["identity"][key] for key in ("herbId", "compoundId", "targetId"))
                result["rows"].append({"provider": provider, "row": row_id, "values": values, "record": record, "selected": selected})
                if selected:
                    chosen_counts[values[0]] += 1
                else:
                    background_count += 1
        finally:
            book.close()
        assert digest(path) == workbook["sha256"]
        for stratum, row in choices:
            assert chosen_counts[row["herb"]] == row["rawTripleRows"]
            result["cases"].append({"provider": provider, "stratum": stratum, "herb": row["herb"],
                                    "rawTripleRows": row["rawTripleRows"], "sourceTargets": row["sourceTargetKeys"]})
        result["workbooks"].append({"provider": provider, "file": workbook["file"], "sha256": workbook["sha256"],
            "workbookUnchanged": True, "selectedRows": sum(chosen_counts.values()), "backgroundRows": background_count,
            "singleHerbRowCountDistribution": [{"cap": cap, "herbKeys": len(cases),
                "herbKeysWithinCap": sum(row["rawTripleRows"] <= cap for row in cases),
                "note": "count-based estimate only; not an API completeness assertion"} for cap in CAPS]})
        print(json.dumps({"provider": provider, "selectedRows": sum(chosen_counts.values()), "backgroundRows": background_count}), flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    print(json.dumps({"report": str(output), "cases": result["cases"], "rows": len(result["rows"])} ,ensure_ascii=False))


if __name__ == "__main__":
    main()
