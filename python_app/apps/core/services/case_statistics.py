"""Bounded, private workbook summary for case-statistics visualization."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections import Counter, defaultdict

from openpyxl import load_workbook
from .case_analysis_figures import build_case_figures, prescription_herbs, formula_names
from .case_knowledge_graph import build_case_knowledge_graph


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 40 * 1024 * 1024
MAX_ROWS = 10_000
MAX_COLUMNS = 30
ADAPTER_VERSION = "case-analysis-v3"
CASE_ID = re.compile(r"^((?:[A-Z]+-)?R\d+-C\d+)-(\d+)$")

# The workbook intentionally contains two columns named "就诊时间"; select by
# position so the second value is never overwritten by a dict keyed by header.
HEADERS = [
    "就诊编号", "来源", "就诊时间", "姓名", "性别", "年龄", "职业", "住址", "诊次", "就诊时间",
    "主诉", "现病史", "既往史", "舌象", "脉象", "体格检查", "辅助检查", "西医诊断依据", "西医病名",
    "中医诊断依据", "中医病名", "证型", "治法治则", "处方", "方药（含剂量）", "煎服法", "其他治法", "医嘱", "预后", "按语点评",
]

METRICS = {
    "sex": ("性别", "病例组"),
    "age_group": ("年龄分组", "病例组"),
    "visit_count": ("诊次数", "病例组"),
    "western_diagnosis": ("西医病名", "诊次记录"),
    "tcm_diagnosis": ("中医病名", "诊次记录"),
    "syndrome": ("证型", "诊次记录"),
    "treatment": ("治法治则", "诊次记录"),
    "tongue": ("舌象", "诊次记录"),
    "pulse": ("脉象", "诊次记录"),
}


class CaseWorkbookError(ValueError):
    pass


def _value(value):
    if value is None:
        return None
    text = " ".join(str(value).replace("\u3000", " ").split())
    if not text or text in {"未提及", "未注明", "未知", "—", "-", "."}:
        return None
    return text


def _age_group(value):
    value = _value(value)
    if not value:
        return None
    if value == "老年":
        return "未注明年龄（原记录：老年）"
    match = re.search(r"(?<!\d)(\d{1,3})(?:\s*岁)?", value)
    if not match:
        return "其他 / 无法按年龄数值分组"
    age = int(match.group(1))
    if age > 120:
        return "其他 / 无法按年龄数值分组"
    if age < 18:
        return "0–17 岁"
    if age < 40:
        return "18–39 岁"
    if age < 60:
        return "40–59 岁"
    if age < 80:
        return "60–79 岁"
    return "80 岁及以上"


def _short_label(value):
    if len(value) <= 100:
        return value
    suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{value[:88]}… [{suffix}]"


def _count(values, total):
    counts = Counter(value for value in values if value is not None)
    missing = total - sum(counts.values())
    if missing:
        counts["未记录"] = missing
    rows = [{"label": _short_label(label), "count": count}
            for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
    return rows


def summarize_case_workbook(upload, unit="first_visit"):
    """Read xlsx in memory and return de-identified aggregate counts only."""
    if unit not in {"first_visit", "all_visits"}:
        raise CaseWorkbookError("统计单位无效。")
    if upload.size > MAX_UPLOAD_BYTES:
        raise CaseWorkbookError("文件超过 5 MiB 上传上限。")
    content = upload.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise CaseWorkbookError("文件超过 5 MiB 上传上限。")
    if not content:
        raise CaseWorkbookError("上传文件为空。")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if len(archive.infolist()) > 500 or sum(item.file_size for item in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
                raise CaseWorkbookError("Excel 文件解压后超过安全上限。")
            if any(item.file_size > MAX_UNCOMPRESSED_BYTES for item in archive.infolist()):
                raise CaseWorkbookError("Excel 文件内单个部件超过安全上限。")
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except CaseWorkbookError:
        raise
    except Exception as exc:
        raise CaseWorkbookError("无法读取 Excel 文件，请上传有效的 .xlsx 工作簿。") from exc

    try:
        sheet = workbook["实体模板"] if "实体模板" in workbook.sheetnames else workbook[workbook.sheetnames[0]]
        # Some exported workbooks omit the optional <dimension> element. In
        # read-only mode openpyxl then reports max_row/max_column as None, so
        # determine the actual bounds from the worksheet stream before using
        # the limits or indexing cells.
        try:
            sheet.calculate_dimension(force=True)
        except Exception as exc:
            raise CaseWorkbookError("无法读取工作表范围，请检查 Excel 文件后重试。") from exc
        if (not sheet.max_row or not sheet.max_column
                or sheet.max_column > MAX_COLUMNS or sheet.max_row > MAX_ROWS + 1):
            raise CaseWorkbookError("工作表超过 10,000 行或 30 列上限。")
        headers = [sheet.cell(1, column).value for column in range(1, len(HEADERS) + 1)]
        if headers != HEADERS or sheet.max_column != len(HEADERS):
            raise CaseWorkbookError("工作表字段与当前医案抽取模板不一致；请上传含 30 个标准字段的模板。")

        records = []
        for source_row, values in enumerate(sheet.iter_rows(min_row=2, max_col=len(HEADERS), values_only=True), start=2):
            if not any(value is not None for value in values):
                continue
            match = CASE_ID.fullmatch(_value(values[0]) or "")
            if not match:
                raise CaseWorkbookError("发现无法识别的就诊编号，未生成统计结果。")
            ordinal = int(match.group(2))
            if not 1 <= ordinal <= 1000:
                raise CaseWorkbookError("诊次编号超出合理范围。")
            prescription_text = _value(values[24])
            row = {"case_group": match.group(1), "ordinal": ordinal, "source_row": source_row,
                   "sex": _value(values[4]), "age": _age_group(values[5]),
                   "prescription_text": prescription_text}
            row["herbs"] = prescription_herbs(prescription_text)
            row["formulas"] = formula_names(_value(values[23]))
            for key, index in (("western_diagnosis", 18), ("tcm_diagnosis", 20), ("syndrome", 21),
                               ("treatment", 22), ("tongue", 13), ("pulse", 14)):
                value = _value(values[index])
                row[key] = _short_label(value) if value else None
            records.append(row)
        if not records:
            raise CaseWorkbookError("工作表中没有医案记录。")
        groups = defaultdict(list)
        for row in records:
            groups[row["case_group"]].append(row)
        if unit == "first_visit":
            selected = [min(rows, key=lambda row: row["ordinal"]) for rows in groups.values()]
        else:
            selected = records

        metrics = {}
        for key, (label, unit_label) in METRICS.items():
            if key == "visit_count":
                values = [str(len({row["ordinal"] for row in rows})) for rows in groups.values()]
                denominator = len(groups)
            elif key == "age_group":
                values = [row["age"] for row in selected]
                denominator = len(selected)
            elif key == "sex":
                values = [{"男": "男", "男性": "男", "女": "女", "女性": "女"}.get(row["sex"], row["sex"]) for row in selected]
                denominator = len(selected)
            else:
                values = [row[key] for row in selected]
                denominator = len(selected)
            if key == "visit_count":
                unit_label = "病例组"
            else:
                unit_label = "病例组" if unit == "first_visit" else "诊次记录"
            metrics[key] = {"label": label, "unit": unit_label, "denominator": denominator, "rows": _count(values, denominator)}

        analysis = build_case_figures(selected, "首诊病例组" if unit == "first_visit" else "全部诊次记录")
        metrics.update(analysis.pop("metrics"))
        knowledge_graph = build_case_knowledge_graph(records, sheet.title[:80])
        return {
            **analysis,
            "knowledgeGraph": knowledge_graph,
            "adapterVersion": ADAPTER_VERSION,
            "testData": True,
            "unit": unit,
            "unitLabel": "首诊病例组" if unit == "first_visit" else "全部诊次记录",
            "recordCount": len(records),
            "caseGroupCount": len(groups),
            "analysisCount": len(selected),
            "sheetName": sheet.title[:80],
            "fileSha256": hashlib.sha256(content).hexdigest(),
            "metrics": metrics,
        }
    finally:
        workbook.close()
