"""CSV/PDF export of the persisted main text-analysis evidence snapshot."""

import csv
import json
from io import BytesIO, StringIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate

from apps.proteomics.exports import PDF_FONT_NAME, _pdf_text, _register_pdf_font


EVIDENCE_LABELS = {
    "syndrome": "证候候选", "formula": "关联方剂", "herbs": "中药", "compounds": "成分",
    "targets": "靶点", "genes": "基因", "pathways": "通路",
}


def _spreadsheet_text(value):
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def _relation_text(record):
    text = (f"{record['subjectLabel']} -[{record['relationType']}]-> {record['objectLabel']}; "
            f"{record['sourceSlug']} {record['sourceVersion']}; {record['sourceRecordId']}; {record['evidenceType']}")
    # Historical snapshots stay usable without filling fields from today's
    # catalogue. Only identity fields actually frozen in this task are added.
    for key in ("sourceRowId", "sourceReleaseId", "sourceChecksumSha256", "subjectStableId", "objectStableId"):
        if record.get(key) is not None:
            text += f"; {key}={record[key]}"
    return text


def export_text_analysis_csv(task):
    result = task.result
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["level", "value"])
    for level in EVIDENCE_LABELS:
        value = result["evidence"].get(level, "")
        writer.writerow([level, _spreadsheet_text("; ".join(value) if isinstance(value, list) else value)])
    writer.writerow(["algorithm_version", result["algorithmVersion"]])
    writer.writerow(["rule_source", result["ruleSource"]])
    for level, value in (
        ("task_id", task.pk), ("name", task.input_parameters.get("name", "")),
        ("query", task.input_parameters.get("query", "")), ("match_status", result.get("matchStatus", "")),
        ("summary", result.get("summary", "")),
        ("scope_limits", json.dumps(result.get("limits", {}), ensure_ascii=False, sort_keys=True)),
    ):
        writer.writerow([level, _spreadsheet_text(value)])
    for warning in result.get("warnings", []):
        writer.writerow(["warning", _spreadsheet_text(warning)])
    for source in result["sources"]:
        writer.writerow(["source", _spreadsheet_text(f"{source['sourceSlug']} / {source['version']} / SHA-256 {source['checksumSha256']}")])
    for record in result["evidenceRecords"]:
        writer.writerow(["relation_evidence", _spreadsheet_text(_relation_text(record))])
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def export_text_analysis_pdf(task):
    _register_pdf_font()
    result = task.result
    styles = getSampleStyleSheet()
    body = ParagraphStyle("TextAnalysisBody", parent=styles["BodyText"], fontName=PDF_FONT_NAME,
                          fontSize=10, leading=15, wordWrap="CJK", spaceAfter=3 * mm)
    heading = ParagraphStyle("TextAnalysisHeading", parent=body, fontSize=12, leading=17,
                             textColor=colors.HexColor("#9c2b22"), spaceBefore=4 * mm, keepWithNext=True)
    title = ParagraphStyle("TextAnalysisTitle", parent=heading, fontSize=18, leading=25)
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                                 topMargin=15 * mm, bottomMargin=18 * mm,
                                 title=str(task.input_parameters.get("name", "证候与方药规则分析")))
    story = [
        Paragraph(_pdf_text(task.input_parameters.get("name", "证候与方药规则分析"), limit=200), title),
        Paragraph(f"任务 #{task.pk} / {_pdf_text(task.owner.get_username())} / {_pdf_text(task.created_at.isoformat())}", body),
        Paragraph("分析输入", heading),
        Paragraph(_pdf_text(task.input_parameters.get("query", ""), limit=20000), body),
        Paragraph(_pdf_text(result["summary"], limit=2000), body),
    ]
    for warning in result["warnings"]:
        story.append(Paragraph(_pdf_text(warning, limit=1000), body))
    story.append(Paragraph("关键词规则命中", heading))
    for rule in result["ruleScores"]:
        story.append(Paragraph(_pdf_text(f"{rule['name']}：{rule['score']} 个关键词 / {'、'.join(rule['matchedKeywords']) or '未命中'}"), body))
    missing = []
    for level in EVIDENCE_LABELS:
        value = result["evidence"].get(level, "")
        if not value:
            missing.append(EVIDENCE_LABELS[level])
            continue
        story.append(Paragraph(EVIDENCE_LABELS.get(level, level), heading))
        values = value if isinstance(value, list) else [value]
        for item in values or [""]:
            story.append(Paragraph(_pdf_text(item or "暂无本地来源关联"), body))
    if missing:
        story.append(Paragraph(_pdf_text("暂无本地来源关联：" + "、".join(missing)), body))
    story.extend([Paragraph("算法与来源版本", heading), Paragraph(_pdf_text(result["algorithmVersion"]), body),
                  Paragraph(_pdf_text(result["ruleSource"]), body)])
    for source in result["sources"]:
        story.append(Paragraph(_pdf_text(f"{source['source']} / {source['sourceSlug']} / {source['version']} / SHA-256 {source['checksumSha256']}", limit=1000), body))
    if result["evidenceRecords"]:
        story.append(Paragraph("关系证据记录", heading))
    for record in result["evidenceRecords"]:
        story.append(Paragraph(_pdf_text(_relation_text(record), limit=3000), body))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(PDF_FONT_NAME, 8)
        canvas.drawString(15 * mm, 9 * mm, "研究候选与目录关联报告 / 请核对原始资料及来源")
        canvas.drawRightString(195 * mm, 9 * mm, f"第 {document.page} 页")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
