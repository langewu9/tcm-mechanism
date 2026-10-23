"""Read-only, aggregate-only inventory of the supplied legacy case workbook.

No extraction, network, Django/database access, row export, or patient-row hashes.
The archive must be explicitly supplied; personal chat paths are not embedded.
"""

import argparse
from collections import Counter
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import stat
import sys
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
WORKBOOK_NAME = "8个名医汇总800-学生大作业___改2(1).xlsx"
SHEETS = tuple("ABCDEFGH") + ("Sheet1",)
COMMON_FIELDS = ("姓名缩写", "性别", "疾病(中医)", "疾病(西医)", "舌象", "脉象", "具体药物")
KEY_FIELDS = ("方剂名称", "具体药物", "治法", "证型", "患者编号", "姓名缩写")
SAFE_HEADERS = set(COMMON_FIELDS) | set(KEY_FIELDS) | {"工作室", "疾病", "主诉", "现病史", "刻下症"}
MAX_WORKBOOK_BYTES = 32 * 1024 * 1024


class InventoryError(ValueError):
    """Safe error text that never includes worksheet cell contents."""


def file_sha256(path):
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def has_value(value):
    return value is not None and bool(str(value).strip())


def header_key(value):
    # Header alignment only: never use this to merge scientific assertions.
    return str(value).strip().replace("（", "(").replace("）", ")")


def exact_value(value):
    # Preserve type, whitespace, spelling, punctuation, units, and modifiers.
    return type(value).__name__, str(value)


def label_counts(records, field):
    values = [row[field] for row in records if has_value(row.get(field))]
    return {
        "nonemptyCells": len(values),
        "rawDistinct": len({exact_value(value) for value in values}),
        "trimmedWhitespaceDistinct": len({str(value).strip() for value in values}),
    }


def inventory_workbook(raw, member):
    from openpyxl import load_workbook

    book = load_workbook(BytesIO(raw), read_only=True, data_only=False, keep_links=False)
    records_by_sheet = {}
    sheets = []
    try:
        if set(book.sheetnames) != set(SHEETS):
            raise InventoryError("工作表结构与已盘点资料不符；未输出未知表头或数据。")
        for name in SHEETS:
            sheet = book[name]
            iterator = sheet.iter_rows(values_only=True)
            raw_headers = next(iterator, ())
            headers = [header_key(value) for value in raw_headers]
            required = set(COMMON_FIELDS) | ({"证型", "患者编号"} if name == "Sheet1" else {"方剂名称", "治法"})
            if (any(key not in SAFE_HEADERS for key in headers)
                    or len(headers) != len(set(headers)) or not required.issubset(headers)):
                raise InventoryError("表头不符合已核对字段白名单；未输出未知字段或数据。")
            records = [dict(zip(headers, row)) for row in iterator if any(has_value(value) for value in row)]
            records_by_sheet[name] = records
            sheets.append({
                "sheet": name,
                "headers": [str(value) for value in raw_headers],
                "nonemptyDataRows": len(records),
                "nonemptyKeyFields": {
                    key: sum(has_value(row.get(key)) for row in records)
                    for key in KEY_FIELDS if key in headers
                },
                "sourceCitationColumns": [],
                "containsDirectOrIndirectPatientIdentifierColumns": True,
            })
    finally:
        book.close()

    detail = [row for name in SHEETS[:-1] for row in records_by_sheet[name]]
    summary = records_by_sheet["Sheet1"]
    keys = Counter(tuple(exact_value(row.get(key)) for key in COMMON_FIELDS) for row in detail)
    matches = [keys[tuple(exact_value(row.get(key)) for key in COMMON_FIELDS)] for row in summary]
    return {
        "member": member,
        "bytes": len(raw),
        "sha256": sha256(raw).hexdigest(),
        "sheets": sheets,
        "detailGroup": {
            "sheets": list(SHEETS[:-1]), "nonemptyDataRows": len(detail),
            "formulaAndDrugsNonempty": sum(has_value(row.get("方剂名称")) and has_value(row.get("具体药物")) for row in detail),
            "formulaLabels": label_counts(detail, "方剂名称"),
        },
        "summaryGroup": {
            "sheet": "Sheet1", "nonemptyDataRows": len(summary),
            "syndromeAndDrugsNonempty": sum(has_value(row.get("证型")) and has_value(row.get("具体药物")) for row in summary),
            "syndromeLabels": label_counts(summary, "证型"),
        },
        "exactSharedFieldComparison": {
            "fields": list(COMMON_FIELDS), "valueNormalization": "none; original value type and whitespace retained",
            "summaryRowsWithAnyExactDetailMatch": sum(count > 0 for count in matches),
            "summaryRowsWithOneExactDetailMatch": sum(count == 1 for count in matches),
            "summaryRowsWithMultipleExactDetailMatches": sum(count > 1 for count in matches),
            "individualMatchesExported": False,
        },
    }


def inventory_archive(archive):
    archive = Path(archive)
    if not archive.is_file():
        raise InventoryError("指定 ZIP 不存在；请通过 --archive 传入本机已授权文件。")
    before = file_sha256(archive)
    with ZipFile(archive) as container:
        candidates = [info for info in container.infolist() if Path(info.filename).name == WORKBOOK_NAME]
        if len(candidates) != 1:
            raise InventoryError("ZIP 中未找到唯一的已知医案工作簿；未读取其他数据表。")
        member = candidates[0]
        if member.file_size > MAX_WORKBOOK_BYTES:
            raise InventoryError("候选工作簿超过只读盘点大小边界。")
        workbook = inventory_workbook(container.read(member), member.filename)
    after = file_sha256(archive)
    if before != after:
        raise InventoryError("盘点期间 ZIP 校验值发生变化；未保存盘点结果。")
    return {
        "schemaVersion": "case-formula-source-inventory-1",
        "archive": {"name": archive.name, "bytes": archive.stat().st_size, "sha256": before, "unchangedAfterRead": True},
        "workbook": workbook,
        "reviewStatus": "need_review",
        "reviewReasons": ["source_citation_and_permission_unverified", "patient_identifier_columns_present",
                          "relationship_between_detail_and_summary_unverified", "raw_labels_are_not_canonical_entities",
                          "real_world_authenticity_and_record_ownership_unverified"],
        "boundaries": {"databaseAccess": False, "networkAccess": False, "archiveExtraction": False,
                       "archiveCodeExecuted": False, "clinicalRowsExported": False, "patientRowHashesExported": False,
                       "imported": False, "canonicalCompositionGenerated": False},
    }


def write_private_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise InventoryError("输出目录需为仅当前用户可访问的目录；未修改既有目录权限。")
    # Never silently replace earlier evidence or a user-provided source file.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True, help="Explicitly authorized local original ZIP; no home-directory search.")
    parser.add_argument("--output", type=Path, default=ROOT / "python_app/var/source-material-inventory-2026-10-23/report.json")
    args = parser.parse_args()
    try:
        if args.output.resolve() == args.archive.resolve():
            raise InventoryError("输出不能覆盖原 ZIP。")
        if args.output.exists():
            raise InventoryError("输出已存在；请使用新的 --output 路径以保留既有证据。")
        report = inventory_archive(args.archive)
        write_private_report(args.output, report)
    except InventoryError as error:
        print(str(error), file=sys.stderr)
        return 2
    except Exception as error:
        # Library errors may contain cell contents; expose the type only.
        print(f"无法完成只读盘点（{type(error).__name__}）；未输出病例内容。", file=sys.stderr)
        return 2
    print(json.dumps({"reviewStatus": report["reviewStatus"],
                      "detailRows": report["workbook"]["detailGroup"]["nonemptyDataRows"],
                      "summaryRows": report["workbook"]["summaryGroup"]["nonemptyDataRows"],
                      "exactSharedFieldMatches": report["workbook"]["exactSharedFieldComparison"]["summaryRowsWithAnyExactDetailMatch"],
                      "imported": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
