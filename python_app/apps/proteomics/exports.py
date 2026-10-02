"""Safe, permission-checked tabular exports for persisted proteomics results."""

import csv
from io import BytesIO, StringIO

from openpyxl import Workbook

from .models import ProteomicsRowResult


EXPORT_COLUMNS = [
    ("row_index", "行"),
    ("original_label", "原始标识"),
    ("protein_name", "蛋白名称"),
    ("normalized_symbol", "规范标识"),
    ("mapping_status", "映射状态"),
    ("mapping_source", "映射来源"),
    ("log2_fold_change", "log2FC"),
    ("p_value", "P值"),
    ("fdr", "FDR"),
    ("direction", "方向"),
    ("selected", "通过筛选"),
    ("exclusion_reasons", "排除原因"),
    ("qc_warnings", "质量警告"),
]


def _safe_spreadsheet_value(value):
    """Prevent user-provided identifiers from being interpreted as formulas."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def _row_values(row):
    values = []
    for name, _label in EXPORT_COLUMNS:
        value = getattr(row, name)
        if name in {"exclusion_reasons", "qc_warnings"}:
            value = "; ".join(value or [])
        elif name == "row_index":
            value += 1
        elif name == "selected":
            value = "通过" if value else "排除"
        values.append(_safe_spreadsheet_value(value))
    return values


def export_proteomics_csv(rows):
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow([label for _name, label in EXPORT_COLUMNS])
    for row in rows.iterator(chunk_size=2000):
        writer.writerow(_row_values(row))
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def export_proteomics_xlsx(task, rows):
    workbook = Workbook(write_only=True)
    analysis = workbook.create_sheet("分析信息")
    analysis.append(["字段", "值"])
    analysis.append(["任务编号", task.pk])
    analysis.append(["数据集", _safe_spreadsheet_value(task.dataset.name if task.dataset else "")])
    analysis.append(["原始文件", _safe_spreadsheet_value(task.dataset.original_filename if task.dataset else "")])
    analysis.append(["SHA-256", task.dataset.content_sha256 if task.dataset else ""])
    analysis.append(["算法版本", task.result.get("algorithmVersion", "")])
    analysis.append(["分析参数", str(task.input_parameters)])

    worksheet = workbook.create_sheet("逐行结果")
    worksheet.append([label for _name, label in EXPORT_COLUMNS])
    for row in rows.iterator(chunk_size=2000):
        worksheet.append(_row_values(row))
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def rows_for_task(task):
    return ProteomicsRowResult.objects.filter(task=task).order_by("row_index")
