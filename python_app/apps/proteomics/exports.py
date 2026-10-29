"""Safe, permission-checked tabular exports for persisted proteomics results."""

import csv
import json
import math
from io import BytesIO, StringIO
from xml.sax.saxutils import escape

from django.db.models import F
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from .models import ProteomicsRowResult


EXPORT_COLUMNS = [
    ("row_index", "行"),
    ("original_label", "原始标识"),
    ("protein_name", "蛋白名称"),
    ("normalized_symbol", "规范标识"),
    ("mapping_status", "映射状态"),
    ("mapping_source", "映射来源"),
    ("external_identifiers", "稳定 ID（来源/版本）"),
    ("log2_fold_change", "log2FC"),
    ("p_value", "P值"),
    ("fdr", "FDR"),
    ("direction", "方向"),
    ("selected", "通过筛选"),
    ("exclusion_reasons", "排除原因"),
    ("qc_warnings", "质量警告"),
]
PDF_RESULT_ROW_LIMIT = 500
PDF_FONT_NAME = "STSong-Light"
REFERENCE_SYMBOL_NOTE = (
    "参考符号对照只比较通过筛选的符号与输入参考符号的名称集合，可能包含未核实项；"
    "名称重叠不代表同物种身份已确认或生物学交叉验证。“参考中未入选”不等于实验未测到。"
)
NUMERIC_FORMAT_REASON_LABELS = {
    "ambiguous_numeric_format": "含逗号数值格式，含义不明确，未转换",
    "ambiguous_log2fc_numeric_format": "log2FC 含逗号数值格式，含义不明确，未转换",
    "ambiguous_p_value_numeric_format": "P 值含逗号数值格式，含义不明确，未转换",
    "ambiguous_fdr_numeric_format": "FDR 含逗号数值格式，含义不明确，未转换",
    "ambiguous_sample_numeric_format": "样本值含逗号数值格式，含义不明确，未转换",
}


def _quality_reason_text(reason):
    prefix = "ambiguous_sample_numeric_format:"
    if isinstance(reason, str) and reason.startswith(prefix):
        return f"样本列 {reason[len(prefix):]} 含逗号数值格式，含义不明确，未转换"
    return NUMERIC_FORMAT_REASON_LABELS.get(reason, reason)


def _register_pdf_font():
    if PDF_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT_NAME))


def _pdf_text(value, *, limit=600):
    text = str(value if value is not None else "")
    text = "".join(character for character in text if character in "\n\r\t" or ord(character) >= 32)
    return escape(text[:limit]).replace("\n", "<br/>").replace("\r", "")


def _pdf_number(value):
    if value is None:
        return "—"
    try:
        number = float(value)
        return f"{number:.6g}" if math.isfinite(number) else "—"
    except (TypeError, ValueError):
        return "—"


def _pdf_table(rows, *, widths, header=True, cell_style=None):
    table = LongTable(rows, colWidths=widths, repeatRows=1 if header else 0, splitByRow=1, hAlign="LEFT")
    style = [
        ("FONTNAME", (0, 0), (-1, -1), PDF_FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d5dfdc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style.extend([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#176b61")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ])
    if cell_style:
        style.extend(cell_style)
    table.setStyle(TableStyle(style))
    return table


def _pdf_page_footer(canvas, document):
    canvas.saveState()
    canvas.setFont(PDF_FONT_NAME, 7)
    canvas.setFillColor(colors.HexColor("#60716c"))
    canvas.drawString(15 * mm, 9 * mm, "研究用途报告 - 结果仅用于科研分析，应结合数据来源与实验设计复核")
    canvas.drawRightString(282 * mm, 9 * mm, f"第 {document.page} 页")
    canvas.restoreState()


def export_proteomics_pdf(task, rows):
    """Create a bounded, Chinese-capable report while leaving the full table in CSV/XLSX exports."""
    _register_pdf_font()
    result = task.result if isinstance(task.result, dict) else {}
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    qc = result.get("qc") if isinstance(result.get("qc"), dict) else {}
    raw_matrix_qc = qc.get("rawMatrix") if isinstance(qc.get("rawMatrix"), dict) else {}
    parameters = task.input_parameters if isinstance(task.input_parameters, dict) else {}
    thresholds = result.get("thresholds") or parameters.get("thresholds") or {}
    mapping = result.get("mapping") if isinstance(result.get("mapping"), dict) else {}
    method = result.get("differentialAnalysis") if isinstance(result.get("differentialAnalysis"), dict) else {}

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitleCJK", parent=styles["Title"], fontName=PDF_FONT_NAME,
        fontSize=19, leading=25, textColor=colors.HexColor("#163d37"),
        alignment=TA_CENTER, spaceAfter=5 * mm,
    )
    heading_style = ParagraphStyle(
        "ReportHeadingCJK", parent=styles["Heading2"], fontName=PDF_FONT_NAME,
        fontSize=12, leading=16, textColor=colors.HexColor("#176b61"),
        spaceBefore=4 * mm, spaceAfter=2 * mm,
    )
    body_style = ParagraphStyle(
        "ReportBodyCJK", parent=styles["BodyText"], fontName=PDF_FONT_NAME,
        fontSize=8.5, leading=12, wordWrap="CJK", textColor=colors.HexColor("#273633"),
    )
    cell_style = ParagraphStyle(
        "ReportCellCJK", parent=body_style, fontSize=7.2, leading=9, wordWrap="CJK",
    )
    header_cell_style = ParagraphStyle(
        "ReportHeaderCJK", parent=cell_style, textColor=colors.white,
    )
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=17 * mm,
        title=f"蛋白组学分析报告 - 任务 {task.pk}",
        subject="蛋白组学可追溯分析摘要",
    )
    story = [Paragraph("蛋白组学分析报告", title_style)]

    dataset = task.dataset
    metadata_rows = [[
        Paragraph("项目", header_cell_style),
        Paragraph("内容", header_cell_style),
    ]]
    metadata = [
        ("任务编号", task.pk),
        ("输入数据行", (result.get("dataset") or {}).get("rowCount", "—")),
        ("数据集", getattr(dataset, "name", "") or "—"),
        ("原始文件", getattr(dataset, "original_filename", "") or "—"),
        ("文件 SHA-256", getattr(dataset, "content_sha256", "") or "—"),
        ("算法版本", result.get("algorithmVersion", "—")),
        ("创建时间", task.created_at.isoformat() if task.created_at else "—"),
        ("完成时间", task.finished_at.isoformat() if task.finished_at else "—"),
    ]
    for label, value in metadata:
        metadata_rows.append([Paragraph(_pdf_text(label), cell_style), Paragraph(_pdf_text(value), cell_style)])
    story.extend([_pdf_table(metadata_rows, widths=[38 * mm, 220 * mm]), Spacer(1, 3 * mm)])

    story.append(Paragraph("分析摘要", heading_style))
    dataset_metadata = result.get("dataset") if isinstance(result.get("dataset"), dict) else {}
    summary_labels = [
        ("输入行", dataset_metadata.get("rowCount", "—")),
        ("筛选行", "selectedRowCount"),
        ("规范化标识", "normalizedCount"),
        ("稳定标识", "stableIdentifierCount"),
        ("本地映射", "databaseMappedCount"),
        ("外部映射", "externalMappedCount"),
        ("未映射", "unmappedCount"),
        ("入选符号重叠", "candidateOverlapCount"),
        ("通路数", "pathwayCount"),
    ]
    summary_rows = []
    for label, key_or_value in summary_labels:
        value = summary.get(key_or_value) if isinstance(key_or_value, str) and key_or_value in summary else key_or_value
        summary_rows.append([
            Paragraph(_pdf_text(label), cell_style),
            Paragraph(_pdf_text(_pdf_number(value)), cell_style),
        ])
    story.append(_pdf_table(
        summary_rows,
        widths=[58 * mm, 35 * mm],
        header=False,
        cell_style=[("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef4f1"))],
    ))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(_pdf_text(REFERENCE_SYMBOL_NOTE), body_style))

    story.append(Paragraph("筛选与方法", heading_style))
    parameter_rows = [[Paragraph("项目", header_cell_style), Paragraph("设定", header_cell_style)]]
    parameter_values = [
        ("阈值", json.dumps(thresholds, ensure_ascii=False, sort_keys=True)),
        ("列映射", json.dumps(mapping, ensure_ascii=False, sort_keys=True)),
    ]
    if method:
        parameter_values.extend([
            ("实验设计", method.get("designType", "—")),
            ("统计检验", method.get("test", "—")),
            ("效应量定义", method.get("effect", "—")),
            ("多重校正", method.get("pValueAdjustment", "—")),
        ])
        if method.get("contrast"):
            parameter_values.append(("主要对比", json.dumps(method["contrast"], ensure_ascii=False, sort_keys=True)))
    for label, value in parameter_values:
        parameter_rows.append([Paragraph(_pdf_text(label), cell_style), Paragraph(_pdf_text(value), cell_style)])
    story.append(_pdf_table(parameter_rows, widths=[38 * mm, 220 * mm]))

    if raw_matrix_qc:
        story.append(Paragraph("原始矩阵质量检查", heading_style))
        qc_labels = [
            ("样本数", "sampleCount"),
            ("通过检验行", "rowsTested"),
            ("设计排除行", "rowsExcludedByMatrixDesign"),
            ("缺失单元格", "missingSampleValueCount"),
            ("非法单元格", "invalidSampleValueCount"),
            ("模型参数数", "modelParameterCount"),
            ("残差自由度", "modelResidualDegreesOfFreedom"),
        ]
        raw_rows = [[Paragraph("质量指标", header_cell_style), Paragraph("数值", header_cell_style)]]
        raw_rows.extend([
            Paragraph(_pdf_text(label), cell_style),
            Paragraph(_pdf_text(_pdf_number(raw_matrix_qc.get(key))), cell_style),
        ] for label, key in qc_labels if key in raw_matrix_qc)
        if len(raw_rows) > 1:
            story.append(_pdf_table(raw_rows, widths=[58 * mm, 35 * mm]))

    excluded_reason_counts = qc.get("excludedReasonCounts")
    format_reason_counts = {
        reason: count for reason, count in excluded_reason_counts.items()
        if reason in NUMERIC_FORMAT_REASON_LABELS or reason.startswith("ambiguous_sample_numeric_format:")
    } if isinstance(excluded_reason_counts, dict) else {}
    if format_reason_counts:
        story.append(Paragraph("数值格式排除原因", heading_style))
        reason_rows = [[Paragraph("原因", header_cell_style), Paragraph("行数", header_cell_style)]]
        reason_rows.extend([
            Paragraph(_pdf_text(_quality_reason_text(reason)), cell_style),
            Paragraph(_pdf_text(_pdf_number(count)), cell_style),
        ] for reason, count in list(format_reason_counts.items())[:100])
        story.append(_pdf_table(reason_rows, widths=[180 * mm, 35 * mm]))

    releases = list(task.source_releases.select_related("source").order_by("source__name", "version"))
    if releases:
        story.append(Paragraph("数据来源版本", heading_style))
        release_rows = [[
            Paragraph("来源", header_cell_style),
            Paragraph("版本", header_cell_style),
            Paragraph("校验值", header_cell_style),
        ]]
        release_rows.extend([
            Paragraph(_pdf_text(release.source.name), cell_style),
            Paragraph(_pdf_text(release.version), cell_style),
            Paragraph(_pdf_text(release.checksum_sha256 or "—", limit=80), cell_style),
        ] for release in releases)
        story.append(_pdf_table(release_rows, widths=[75 * mm, 70 * mm, 110 * mm]))
    else:
        story.append(Paragraph("数据来源版本", heading_style))
        story.append(Paragraph("该任务未关联版本化数据源记录。", body_style))

    warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
    if warnings:
        story.append(Paragraph("解释与质量提示", heading_style))
        for warning in warnings[:20]:
            story.append(Paragraph(f"- {_pdf_text(warning)}", body_style))
            story.append(Spacer(1, 1.2 * mm))

    selected_rows = list(
        rows.filter(selected=True)
        .order_by(F("fdr").asc(nulls_last=True), "row_index")[:PDF_RESULT_ROW_LIMIT + 1]
    )
    if selected_rows:
        story.append(Paragraph("重点差异结果", heading_style))
        table_rows = [[
            Paragraph(_pdf_text(label), header_cell_style)
            for label in ("原始标识", "规范标识", "稳定 ID", "log2FC", "P 值", "FDR", "方向")
        ]]
        for row in selected_rows[:PDF_RESULT_ROW_LIMIT]:
            stable_identifiers = [
                f"{item.get('namespace')}:{item.get('identifier')}"
                + (f"（{item.get('source')}@{item.get('sourceVersion')}）" if item.get("sourceVersion") else "")
                for item in (row.external_identifiers or [])[:3]
            ]
            if len(row.external_identifiers or []) > 3:
                stable_identifiers.append("…")
            table_rows.append([
                Paragraph(_pdf_text(row.original_label, limit=180), cell_style),
                Paragraph(_pdf_text(row.normalized_symbol or "—", limit=100), cell_style),
                Paragraph(_pdf_text("；".join(stable_identifiers) or "—", limit=220), cell_style),
                Paragraph(_pdf_text(_pdf_number(row.log2_fold_change)), cell_style),
                Paragraph(_pdf_text(_pdf_number(row.p_value)), cell_style),
                Paragraph(_pdf_text(_pdf_number(row.fdr)), cell_style),
                Paragraph(_pdf_text(row.direction or "—"), cell_style),
            ])
        story.append(_pdf_table(
            table_rows,
            widths=[45 * mm, 38 * mm, 52 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm],
        ))
        selected_count = rows.filter(selected=True).count()
        if selected_count > PDF_RESULT_ROW_LIMIT:
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph(
                f"本报告按 FDR 从小到大展示前 {PDF_RESULT_ROW_LIMIT} 项，共有 {selected_count} 项通过筛选；"
                "完整逐行结果（包括未通过筛选的行及原因）请下载 CSV 或 XLSX。",
                body_style,
            ))
    else:
        story.extend([
            Paragraph("重点差异结果", heading_style),
            Paragraph("本次分析没有通过筛选的行。完整 QC、排除原因与逐行输出请查看 CSV/XLSX。", body_style),
        ])

    document.build(story, onFirstPage=_pdf_page_footer, onLaterPages=_pdf_page_footer)
    return buffer.getvalue()


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
        elif name == "external_identifiers":
            value = json.dumps(value or [], ensure_ascii=False, sort_keys=True)
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
    analysis.append(["参考符号对照说明", REFERENCE_SYMBOL_NOTE])

    worksheet = workbook.create_sheet("逐行结果")
    worksheet.append([label for _name, label in EXPORT_COLUMNS])
    for row in rows.iterator(chunk_size=2000):
        worksheet.append(_row_values(row))
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def rows_for_task(task):
    return ProteomicsRowResult.objects.filter(task=task).order_by("row_index")
