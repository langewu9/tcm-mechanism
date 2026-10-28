import hashlib
import json
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.case_rag.models import CaseCorpusDocument, RagCorpusRelease


CORPUS_SLUG = "curated-tcm-cases"
CORPUS_NAME = "四类中医医案集"
DATABASE_ALIAS = "case_rag"
SHEETS = {
    "肺系疾病": CaseCorpusDocument.Category.PULMONARY,
    "中风": CaseCorpusDocument.Category.STROKE,
    "胃病": CaseCorpusDocument.Category.STOMACH,
    "咽炎": CaseCorpusDocument.Category.PHARYNGITIS,
}
REQUIRED_HEADERS_BY_SHEET = {
    "肺系疾病": {"编号", "疾病分型", "原始医案文本"},
    "中风": {"编号", "疾病分型", "原始医案文本"},
    "胃病": {"编号", "疾病（中医）", "疾病（西医）", "主诉", "现病史", "舌象", "脉象", "证型", "治法", "方剂名称", "具体药物"},
    "咽炎": {"编号", "现病史", "舌质", "舌苔", "脉象", "第一中医诊断", "第一中医证型", "主诉症状"},
}
STRUCTURED_HEADERS = [
    "编号", "疾病分型", "性别", "年龄", "西医诊断", "中医病名", "中医证型（原文）",
    "主诉", "病程及现病史", "主要症状体征", "舌象", "脉象", "辨证/病机依据",
    "治法/治则", "识别方剂", "处方与药物原文", "剂量/疗程摘录", "疗效/转归",
    "来源医生", "来源", "DOI/期刊/出处链接", "原始编号", "来源文件", "材料类型",
]
STOMACH_HEADERS = [
    "编号", "性别", "年龄", "疾病（中医）", "疾病（西医）", "主诉", "现病史", "刻下症",
    "舌象", "脉象", "疾病", "证型", "治法", "方剂名称", "具体药物",
    "中医信息采集-主诉", "中医信息采集-现病史", "中医信息采集-刻下症",
    "中医信息采集-脉象", "中医诊断：疾病：", "中成药处方", "症状标签", "药物标签",
    "名老中医点评精粹", "传承弟子心得",
]
PHARYNGITIS_HEADERS = [
    "编号", "性别", "年龄", "现病史", "既往史", "体格检查", "检查检验医嘱",
    "中药处方内容", "西成药处方内容", "治疗项目", "舌质", "舌苔", "脉象",
    "第一中医诊断", "第一中医证型", "第二中医诊断", "第二中医证型",
    "第三中医诊断", "第三中医证型", "第一西医诊断", "第二西医诊断",
    "第三西医诊断", "第四西医诊断", "第五西医诊断", "咽痒", "咽痛", "咽干",
    "咳嗽", "咽异物感", "声嘶", "咽后壁", "扁桃体", "声带", "新生物",
    "主诉症状", "持续时间", "不良事件", "随访",
]
STRUCTURED_HEADERS_BY_SHEET = {
    "肺系疾病": STRUCTURED_HEADERS,
    "中风": STRUCTURED_HEADERS,
    "胃病": STOMACH_HEADERS,
    "咽炎": PHARYNGITIS_HEADERS,
}
TITLE_FIELD_BY_SHEET = {
    "肺系疾病": "疾病分型",
    "中风": "疾病分型",
    "胃病": "疾病（中医）",
    "咽炎": "第一中医诊断",
}
EXTRACTION_STATUS_HEADER = "抽取状态"
ORIGINAL_TEXT_HEADER = "原始医案文本"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _cell_text(value) -> str:
    return "" if value is None else str(value).strip()


def _canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _make_document(sheet_name, category, row_number, headers, values):
    row = {
        header: _cell_text(values[index]) if index < len(values) else ""
        for index, header in enumerate(headers)
        if header
    }
    record_number = row.get("编号") or f"row-{row_number}"
    structured_headers = STRUCTURED_HEADERS_BY_SHEET[sheet_name]
    clinical_values = [row.get(header) for header in structured_headers if header != "编号"]
    if not row.get(ORIGINAL_TEXT_HEADER) and not any(clinical_values):
        raise CommandError(f"{sheet_name} 第 {row_number} 行没有可检索的医案内容。")

    structured = {header: row.get(header) or None for header in structured_headers}
    original_text = row.get(ORIGINAL_TEXT_HEADER, "")
    search_text = "\n".join(
        value for value in [*clinical_values, sheet_name, record_number] if value
    )
    source_reference = "；".join(
        f"{label}：{row[label]}"
        for label in ("来源", "原始编号", "来源文件", "材料类型", "来源表")
        if row.get(label)
    )
    source_link = row.get("DOI/期刊/出处链接", "")
    source_doctor = row.get("来源医生", "")
    title_detail = (
        row.get(TITLE_FIELD_BY_SHEET[sheet_name])
        or row.get("疾病（西医）")
        or row.get("疾病")
        or category.label
    )
    title = f"{sheet_name} · {title_detail} · {record_number}"[:300]
    source_record_id = f"{sheet_name}:{record_number}"
    payload = {
        "source_record_id": source_record_id,
        "source_sheet": sheet_name,
        "category": category,
        "title": title,
        "source_reference": source_reference,
        "source_link": source_link,
        "source_doctor": source_doctor,
        "original_text": original_text,
        "structured_data": structured,
        "search_text": search_text,
        "extraction_status": row.get(EXTRACTION_STATUS_HEADER, ""),
    }
    payload["content_sha256"] = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return payload


class Command(BaseCommand):
    help = "Import the four curated TCM case sheets into the separate RAG database."

    def add_arguments(self, parser):
        parser.add_argument("workbook", type=Path)
        parser.add_argument("--corpus-version", default="", help="Optional immutable corpus release name.")
        parser.add_argument("--expected-total", type=int, default=2500)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        path = options["workbook"].expanduser().resolve()
        if not path.is_file() or path.suffix.lower() != ".xlsx":
            raise CommandError("请提供存在的 .xlsx 工作簿路径。")
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise CommandError("缺少 openpyxl；请先安装 python_app/requirements.txt。") from exc

        checksum = _file_sha256(path)
        workbook = load_workbook(path, read_only=True, data_only=True)
        documents = []
        counts = Counter()
        try:
            missing_sheets = set(SHEETS).difference(workbook.sheetnames)
            if missing_sheets:
                raise CommandError(f"工作簿缺少工作表：{', '.join(sorted(missing_sheets))}。")
            for sheet_name, category in SHEETS.items():
                sheet = workbook[sheet_name]
                rows = sheet.iter_rows(values_only=True)
                header_row = next(rows, None)
                if not header_row:
                    raise CommandError(f"工作表“{sheet_name}”没有表头。")
                headers = [_cell_text(value) for value in header_row]
                missing_headers = REQUIRED_HEADERS_BY_SHEET[sheet_name].difference(headers)
                if missing_headers:
                    raise CommandError(
                        f"工作表“{sheet_name}”缺少必要字段：{', '.join(sorted(missing_headers))}。"
                    )
                for row_number, values in enumerate(rows, start=2):
                    if not any(_cell_text(value) for value in values):
                        continue
                    payload = _make_document(sheet_name, category, row_number, headers, values)
                    documents.append(payload)
                    counts[sheet_name] += 1
        finally:
            workbook.close()

        record_ids = [item["source_record_id"] for item in documents]
        if len(record_ids) != len(set(record_ids)):
            raise CommandError("工作簿存在重复的工作表/编号，无法建立稳定且可追溯的病例 ID。")
        expected_total = options["expected_total"]
        if expected_total and len(documents) != expected_total:
            raise CommandError(
                f"预期 {expected_total} 条四类医案，实际发现 {len(documents)} 条：{dict(counts)}。"
            )

        version = options["corpus_version"].strip() or f"sha256-{checksum[:16]}-four-categories-v1"
        result = {
            "database": DATABASE_ALIAS,
            "workbook": path.name,
            "version": version,
            "checksumSha256": checksum,
            "recordCount": len(documents),
            "categoryCounts": dict(counts),
            "dryRun": options["dry_run"],
        }
        if options["dry_run"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
            return

        try:
            with transaction.atomic(using=DATABASE_ALIAS):
                existing = RagCorpusRelease.objects.using(DATABASE_ALIAS).filter(
                    corpus_slug=CORPUS_SLUG, version=version
                ).first()
                if existing:
                    existing_count = CaseCorpusDocument.objects.using(DATABASE_ALIAS).filter(
                        release=existing
                    ).count()
                    if existing.checksum_sha256 != checksum or existing_count != len(documents):
                        raise CommandError(
                            "该版本号已用于不同的文件或记录数；请使用新的 --corpus-version 保留原始发布记录。"
                        )
                    result["releaseId"] = existing.pk
                    result["alreadyImported"] = True
                else:
                    release = RagCorpusRelease.objects.using(DATABASE_ALIAS).create(
                        corpus_slug=CORPUS_SLUG,
                        name=CORPUS_NAME,
                        version=version,
                        workbook_name=path.name,
                        checksum_sha256=checksum,
                        record_count=len(documents),
                        metadata={
                            "importer": "case-rag-xlsx-v1",
                            "sheetCounts": dict(counts),
                            "recordStatus": "保留原表抽取状态；未提供状态的工作表不推定已经人工校核",
                        },
                    )
                    CaseCorpusDocument.objects.using(DATABASE_ALIAS).bulk_create(
                        [CaseCorpusDocument(release=release, **item) for item in documents],
                        batch_size=200,
                    )
                    RagCorpusRelease.objects.using(DATABASE_ALIAS).filter(
                        corpus_slug__in=[CORPUS_SLUG, "pulmonary-stroke-cases"]
                    ).exclude(pk=release.pk).update(is_active=False)
                    result["releaseId"] = release.pk
                    result["alreadyImported"] = False
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(
                "医案 RAG 数据库未准备好。请先运行 `python manage.py migrate --database=case_rag`，再重试导入。"
            ) from exc

        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
