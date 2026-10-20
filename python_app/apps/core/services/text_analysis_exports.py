"""CSV/PDF export of the persisted main text-analysis evidence snapshot."""

import csv
from io import BytesIO, StringIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

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


def export_text_analysis_csv(task):
    result = task.result
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["level", "value"])
    for level, value in result["evidence"].items():
        writer.writerow([level, _spreadsheet_text("; ".join(value) if isinstance(value, list) else value)])
    writer.writerow(["algorithm_version", result["algorithmVersion"]])
    writer.writerow(["rule_source", result["ruleSource"]])
    for source in result["sources"]:
        writer.writerow(["source", _spreadsheet_text(f"{source['sourceSlug']} / {source['version']} / SHA-256 {source['checksumSha256']}")])
    for record in result["evidenceRecords"]:
        writer.writerow(["relation_evidence", _spreadsheet_text(
            f"{record['subjectLabel']} —{record['relationType']}→ {record['objectLabel']}; "
            f"{record['sourceSlug']} {record['sourceVersion']}; {record['sourceRecordId']}; {record['evidenceType']}"
        )])
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def export_text_analysis_pdf(task):
    _register_pdf_font()
    result = task.result
    styles = getSampleStyleSheet()
    body = ParagraphStyle("TextAnalysisBody", parent=styles["BodyText"], fontName=PDF_FONT_NAME,
                          fontSize=10, leading=15, wordWrap="CJK", spaceAfter=3 * mm)
    heading = ParagraphStyle("TextAnalysisHeading", parent=body, fontSize=12, leading=17,
                             textColor=colors.HexColor("#9c2b22"), spaceBefore=4 * mm)
    title = ParagraphStyle("TextAnalysisTitle", parent=heading, fontSize=18, leading=25)
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                                 topMargin=15 * mm, bottomMargin=18 * mm,
                                 title=str(task.input_parameters.get("name", "证候与方药规则分析")))
    story = [
        Paragraph(_pdf_text(task.input_parameters.get("name", "证候与方药规则分析"), limit=200), title),
        Paragraph(f"任务 #{task.pk} / {_pdf_text(task.owner.get_username())} / {_pdf_text(task.created_at.isoformat())}", body),
        Paragraph(_pdf_text(result["summary"], limit=2000), body),
    ]
    for warning in result["warnings"]:
        story.append(Paragraph(_pdf_text(warning, limit=1000), body))
    story.append(Paragraph("关键词规则命中", heading))
    for rule in result["ruleScores"]:
        story.append(Paragraph(_pdf_text(f"{rule['name']}：{rule['score']} 个关键词 / {'、'.join(rule['matchedKeywords']) or '未命中'}"), body))
    for level, value in result["evidence"].items():
        story.append(Paragraph(EVIDENCE_LABELS.get(level, level), heading))
        values = value if isinstance(value, list) else [value]
        for item in values or [""]:
            story.append(Paragraph(_pdf_text(item or "暂无本地来源关联"), body))
    story.extend([Paragraph("算法与来源版本", heading), Paragraph(_pdf_text(result["algorithmVersion"]), body),
                  Paragraph(_pdf_text(result["ruleSource"]), body)])
    for source in result["sources"]:
        story.append(Paragraph(_pdf_text(f"{source['source']} / {source['sourceSlug']} / {source['version']} / SHA-256 {source['checksumSha256']}", limit=1000), body))
    story.append(Paragraph("关系证据记录", heading))
    for record in result["evidenceRecords"]:
        story.append(Paragraph(_pdf_text(
            f"{record['subjectLabel']} —{record['relationType']}→ {record['objectLabel']} / "
            f"{record['sourceSlug']} {record['sourceVersion']} / {record['sourceRecordId']} / {record['evidenceType']}", limit=1500
        ), body))
    story.append(Spacer(1, 3 * mm))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(PDF_FONT_NAME, 8)
        canvas.drawString(15 * mm, 9 * mm, "研究候选与目录关联报告 / 请核对原始资料及来源")
        canvas.drawRightString(195 * mm, 9 * mm, f"第 {document.page} 页")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
