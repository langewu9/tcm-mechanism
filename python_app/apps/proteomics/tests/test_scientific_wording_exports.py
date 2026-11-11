"""Exercise generated exports against persisted synthetic legacy results only."""

import csv
from io import BytesIO, StringIO
import re
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from openpyxl import load_workbook
from reportlab import rl_config

from apps.core.models import AnalysisTask
from apps.proteomics.exports import (
    REFERENCE_SYMBOL_NOTE,
    export_proteomics_csv,
    export_proteomics_pdf,
    export_proteomics_xlsx,
    rows_for_task,
)
from apps.proteomics.models import ProteomicsRowResult


def _uncompressed_pdf_text(content):
    """Read ReportLab's own uncompressed UTF-16 CJK Tj strings, without a new PDF dependency."""
    strings = []
    escapes = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}
    for stream in re.findall(rb"stream\r?\n(.*?)endstream", content, re.S):
        for text in re.findall(rb"\(((?:\\.|[^\\)])*)\)\s*Tj", stream):
            def decode_escape(match):
                token = match.group(1)
                return bytes([int(token, 8)]) if token[:1] in b"01234567" else escapes.get(token, token)

            decoded = re.sub(rb"\\([0-7]{1,3}|[nrtbf()\\])", decode_escape, text)
            strings.append(decoded.decode("utf-16-be", errors="ignore"))
    return "".join(strings)


class ScientificWordingExportTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="synthetic-wording-owner")
        # No new comparison/identity fields are needed to render a historical result.
        self.task = AnalysisTask.objects.create(
            owner=self.owner,
            task_type=AnalysisTask.TaskType.PROTEOMICS,
            status=AnalysisTask.Status.SUCCEEDED,
            result={
                "algorithmVersion": "SYNTHETIC_LEGACY",
                "dataset": {"rowCount": 2},
                "summary": {"selectedRowCount": 1, "normalizedCount": 1,
                            "databaseMappedCount": 0, "unmappedCount": 0,
                            "candidateOverlapCount": 1, "pathwayCount": 0},
                "qc": {"excludedReasonCounts": {"ambiguous_numeric_format": 1}},
                "validation": {"referenceTargets": ["SHARED", "REFERENCE_ONLY"],
                               "overlap": ["SHARED"], "proteomicsOnly": [],
                               "referenceOnly": ["REFERENCE_ONLY"]},
            },
        )
        ProteomicsRowResult.objects.create(
            task=self.task, row_index=0, original_label="SHARED", normalized_symbol="SHARED",
            mapping_status=ProteomicsRowResult.MappingStatus.UNVERIFIED,
            log2_fold_change=2, p_value=0.01, fdr=0.02, selected=True,
        )
        ProteomicsRowResult.objects.create(
            task=self.task, row_index=1, original_label="AMBIGUOUS_NUMBER",
            mapping_status=ProteomicsRowResult.MappingStatus.UNMAPPED,
            selected=False, exclusion_reasons=["ambiguous_numeric_format"],
            qc_warnings=["ambiguous_fdr_numeric_format", "ambiguous_sample_numeric_format:Sample<1>"],
        )

    def test_pdf_generates_real_legacy_values_and_explains_scope_and_exclusion(self):
        before = self.task.result.copy()
        with patch.object(rl_config, "pageCompression", 0):
            content = export_proteomics_pdf(self.task, rows_for_task(self.task))
        self.assertTrue(content.startswith(b"%PDF-"))
        self.assertGreater(len(content), 1000)
        text = _uncompressed_pdf_text(content)
        self.assertIn("入选符号重叠1", text)
        self.assertIn("可能包含未核实项", text)
        self.assertIn("名称重叠不代表同物种身份已确认或生物学交叉验证", text)
        self.assertIn("不等于实验未测到", text)
        self.assertIn("含逗号数值格式，含义不明确，未转换1", text)
        self.assertIn("SHARED", text)
        for old in ["候选交集", "共同靶点", "组学特有", "候选未检出"]:
            self.assertNotIn(old, text)
        self.task.refresh_from_db()
        self.assertEqual(self.task.result, before)

    def test_csv_and_xlsx_preserve_rows_codes_and_values_with_xlsx_scope_note(self):
        rows = rows_for_task(self.task)
        csv_rows = list(csv.DictReader(StringIO(export_proteomics_csv(rows).decode("utf-8-sig"))))
        workbook = load_workbook(BytesIO(export_proteomics_xlsx(self.task, rows)), data_only=False)
        metadata = dict(workbook["分析信息"].values)
        self.assertEqual(metadata["参考符号对照说明"], REFERENCE_SYMBOL_NOTE)
        worksheet = workbook["逐行结果"]
        header, *xlsx_values = list(worksheet.values)
        xlsx_rows = [dict(zip(header, row)) for row in xlsx_values]
        self.assertEqual(len(csv_rows), 2)
        self.assertEqual(len(xlsx_rows), 2)
        for output_rows in [csv_rows, xlsx_rows]:
            self.assertEqual(output_rows[0]["原始标识"], "SHARED")
            self.assertEqual(float(output_rows[0]["log2FC"]), 2)
            self.assertEqual(float(output_rows[0]["P值"]), 0.01)
            self.assertEqual(float(output_rows[0]["FDR"]), 0.02)
            self.assertEqual(output_rows[0]["映射状态"], "unverified")
            self.assertEqual(output_rows[0]["通过筛选"], "通过")
            self.assertEqual(output_rows[1]["排除原因"], "ambiguous_numeric_format")
            self.assertEqual(output_rows[1]["质量警告"], "ambiguous_fdr_numeric_format; ambiguous_sample_numeric_format:Sample<1>")
            self.assertEqual(output_rows[1]["通过筛选"], "排除")
        self.assertEqual(list(self.task.proteomics_rows.values_list("selected", flat=True)), [True, False])

    def test_pdf_numeric_reason_mapping_escapes_dynamic_columns_as_text(self):
        self.task.result["qc"]["excludedReasonCounts"] = {
            "ambiguous_log2fc_numeric_format": 1,
            "ambiguous_p_value_numeric_format": 1,
            "ambiguous_fdr_numeric_format": 1,
            "ambiguous_sample_numeric_format": 1,
            "ambiguous_sample_numeric_format:Sample<1>": 1,
        }
        with patch.object(rl_config, "pageCompression", 0):
            content = export_proteomics_pdf(self.task, rows_for_task(self.task))
        text = _uncompressed_pdf_text(content)
        for label in ["log2FC 含逗号数值格式", "P 值含逗号数值格式", "FDR 含逗号数值格式",
                      "样本值含逗号数值格式", "样本列 Sample<1> 含逗号数值格式"]:
            self.assertIn(label, text)
