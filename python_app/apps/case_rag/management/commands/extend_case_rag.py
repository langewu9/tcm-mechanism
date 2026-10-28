"""Publish a combined immutable corpus without deleting earlier releases."""
import hashlib
import json
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.case_rag.models import CaseCorpusDocument, RagCorpusRelease
from apps.case_rag.services import CORPUS_SLUG, active_release
from .import_case_rag import _canonical_json, _cell_text, _file_sha256


DATABASE_ALIAS = "case_rag"
SHEET_NAME = "医家案例2000例"
REQUIRED_HEADERS = {"编号", "医家", "主诉", "主诉标注情况", "病历文本", "辨证", "治法", "处方"}
DOCUMENT_FIELDS = (
    "source_record_id", "source_sheet", "source_workbook", "source_workbook_sha256",
    "category", "title", "source_reference", "source_link", "source_doctor", "original_text",
    "structured_data", "search_text", "extraction_status", "content_sha256",
)


def make_general_document(headers, values, row_number, workbook_name, checksum):
    row = {header: _cell_text(values[index]) if index < len(values) else ""
           for index, header in enumerate(headers) if header in REQUIRED_HEADERS}
    number, original = row.get("编号", ""), row.get("病历文本", "")
    if not number or not original:
        raise CommandError(f"{SHEET_NAME} 第 {row_number} 行缺少编号或病历正文。")
    if len(number) > 100:
        raise CommandError(f"{SHEET_NAME} 第 {row_number} 行编号过长。")
    clinical = {key: row.get(key) or None for key in ("主诉", "辨证", "治法", "处方", "主诉标注情况")}
    payload = {
        "source_record_id": f"linglan:{number}", "source_sheet": SHEET_NAME,
        "source_workbook": workbook_name, "source_workbook_sha256": checksum,
        "category": CaseCorpusDocument.Category.GENERAL,
        "title": f"综合 · {row.get('医家') or '医家案例'} · {number}"[:300],
        "source_reference": "LingLan 医家案例整理表", "source_link": "",
        "source_doctor": row.get("医家", "")[:160], "original_text": original,
        "structured_data": clinical,
        "search_text": "\n".join(value for value in ["综合", number, row.get("医家"), original, *clinical.values()] if value),
        "extraction_status": "原表整理，未标注人工核校状态",
    }
    payload["content_sha256"] = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return payload


class Command(BaseCommand):
    help = "将 LingLan 医家案例加入综合分类，发布包含现有医案的新版本。"

    def add_arguments(self, parser):
        parser.add_argument("workbook", type=Path)
        parser.add_argument("--expected-source-count", type=int, default=2000)
        parser.add_argument("--expected-total", type=int, default=4500)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        path = options["workbook"].expanduser().resolve()
        if not path.is_file() or path.suffix.lower() != ".xlsx":
            raise CommandError("请提供存在的 .xlsx 工作簿路径。")
        from openpyxl import load_workbook

        checksum = _file_sha256(path)
        workbook = load_workbook(path, read_only=True, data_only=True)
        incoming = []
        try:
            if SHEET_NAME not in workbook.sheetnames:
                raise CommandError(f"工作簿缺少工作表：{SHEET_NAME}。")
            rows = workbook[SHEET_NAME].iter_rows(values_only=True)
            headers = [_cell_text(value) for value in next(rows, ())]
            if REQUIRED_HEADERS.difference(headers) or len(headers) != len(set(headers)):
                raise CommandError("表头缺失或重复，请核对编号、医家、主诉、主诉标注情况、病历文本、辨证、治法和处方。")
            for row_number, values in enumerate(rows, start=2):
                if any(_cell_text(value) for value in values):
                    incoming.append(make_general_document(headers, values, row_number, path.name, checksum))
        finally:
            workbook.close()
        if len(incoming) != options["expected_source_count"]:
            raise CommandError(f"预期 {options['expected_source_count']} 条来源记录，实际发现 {len(incoming)} 条。")
        if len({item["source_record_id"] for item in incoming}) != len(incoming):
            raise CommandError("来源表存在重复编号，未执行导入。")

        base = active_release()
        if base is None:
            raise CommandError("当前没有生效的基础医案库，请先导入原有医案。")
        documents = list(CaseCorpusDocument.objects.using(DATABASE_ALIAS).filter(release=base).values(*DOCUMENT_FIELDS))
        if len(documents) != base.record_count:
            raise CommandError("基础医案库记录数与版本声明不一致，未执行导入。")
        for document in documents:
            document["source_workbook"] = document["source_workbook"] or base.workbook_name
            document["source_workbook_sha256"] = document["source_workbook_sha256"] or base.checksum_sha256
        existing = {item["source_record_id"]: item for item in documents}
        added = 0
        for document in incoming:
            previous = existing.get(document["source_record_id"])
            if previous:
                if previous["content_sha256"] != document["content_sha256"]:
                    raise CommandError(f"编号 {document['source_record_id']} 已存在且内容不同，请核对来源后建立新的版本规则。")
                continue
            documents.append(document)
            added += 1
        if len(documents) != options["expected_total"]:
            raise CommandError(f"合并后预期 {options['expected_total']} 条，实际 {len(documents)} 条。")
        manifest = sorted({(item["source_workbook"], item["source_workbook_sha256"]) for item in documents})
        digest = hashlib.sha256(_canonical_json({
            "sources": manifest,
            "records": sorted((item["source_record_id"], item["content_sha256"]) for item in documents),
        }).encode("utf-8")).hexdigest()
        version = f"sha256-{digest[:16]}-five-categories-v1"
        counts = dict(Counter(item["category"] for item in documents))
        result = {"version": version, "checksumSha256": digest, "sourceChecksumSha256": checksum,
                  "sourceCount": len(incoming), "addedCount": added, "recordCount": len(documents),
                  "categoryCounts": counts, "dryRun": options["dry_run"]}
        if not options["dry_run"]:
            with transaction.atomic(using=DATABASE_ALIAS):
                if active_release().pk != base.pk:
                    raise CommandError("基础版本已变化，请重新运行导入。")
                release = RagCorpusRelease.objects.using(DATABASE_ALIAS).filter(corpus_slug=CORPUS_SLUG, version=version).first()
                if release:
                    if (release.checksum_sha256 != digest or
                            release.documents.using(DATABASE_ALIAS).count() != len(documents)):
                        raise CommandError("同一版本的校验值或记录数量不同，未切换版本。")
                    if not release.is_active:
                        raise CommandError("该合并版本已停用，未自动回退当前版本。")
                    result["alreadyImported"] = True
                else:
                    release = RagCorpusRelease.objects.using(DATABASE_ALIAS).create(
                        corpus_slug=CORPUS_SLUG, name="中医参考医案库", version=version,
                        workbook_name="多来源医案库（逐条记录保留原工作簿）", checksum_sha256=digest,
                        record_count=len(documents), is_active=False,
                        metadata={"importer": "case-rag-linglan-merge-v1", "categoryCounts": counts,
                                  "baseReleaseId": base.pk, "baseVersion": base.version,
                                  "sourceManifest": [{"workbook": name, "checksumSha256": sha} for name, sha in manifest]},
                    )
                    CaseCorpusDocument.objects.using(DATABASE_ALIAS).bulk_create(
                        [CaseCorpusDocument(release=release, **item) for item in documents], batch_size=150,
                    )
                    RagCorpusRelease.objects.using(DATABASE_ALIAS).filter(corpus_slug=CORPUS_SLUG).exclude(pk=release.pk).update(is_active=False)
                    release.is_active = True
                    release.save(using=DATABASE_ALIAS, update_fields=["is_active"])
                    result["alreadyImported"] = False
                result["releaseId"] = release.pk
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
