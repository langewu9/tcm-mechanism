"""Read-only retrieval of versioned reference cases from the sidecar database."""
from __future__ import annotations

import re
from django.db import OperationalError, ProgrammingError
from django.db.models import Case, Count, IntegerField, Q, Value, When
from .models import CaseCorpusDocument, RagCorpusRelease

CORPUS_SLUG = "curated-tcm-cases"
CATEGORIES = dict(CaseCorpusDocument.Category.choices)
DOMAIN_TERMS = {
    "pulmonary": ("肺", "肺系", "肺系疾病", "咳嗽", "咳痰", "喘息", "哮喘", "肺痿", "肺痈", "咯血"),
    "stroke": ("中风", "卒中", "脑梗", "脑出血", "偏瘫", "失语", "口眼歪斜"),
    "stomach": ("胃", "胃病", "胃痛", "胃脘", "脾胃", "胃炎", "胃胀", "反酸", "呃逆"),
    "pharyngitis": ("咽", "咽炎", "咽痛", "咽痒", "咽干", "咽异物感"),
}
STOP_WORDS = {"请问", "帮我", "分析", "检索", "查询", "总结", "有哪些", "如何", "什么", "相关", "这个", "这些", "根据", "结合", "目前", "主要", "可以", "以及", "关于", "患者", "医案", "病案", "病例", "案例", "记录", "证据", "资料", "临床", "中医药", "常见", "进行", "中的"}
PROVENANCE_FIELDS = {"编号", "来源医生", "来源", "DOI/期刊/出处链接", "原始编号", "来源文件", "材料类型", "来源表"}
CLINICAL_PRIORITY = ("主诉", "主诉症状", "疾病分型", "中医病名", "疾病（中医）", "第一中医诊断", "中医证型（原文）", "证型", "辨证", "第一中医证型", "治法/治则", "治法", "方剂名称", "识别方剂", "处方", "具体药物", "中药处方内容", "处方与药物原文", "舌象", "舌质", "舌苔", "脉象", "现病史", "主要症状体征", "主诉标注情况")


class CaseCorpusUnavailable(ValueError):
    pass


def query_terms(question: str) -> list[str]:
    text = str(question or "").strip().lower()
    terms = {}
    for values in DOMAIN_TERMS.values():
        for term in values:
            if len(term) >= 2 and term in text:
                terms[term] = 8 + len(term)
    for term in ("气虚", "阴虚", "阳虚", "血瘀", "痰湿", "痰热", "风寒", "风热", "痰瘀", "脾虚", "气滞", "血虚", "肝郁"):
        if term in text:
            terms[term] = 10
    # Chinese input does not require spaces; retain bounded short fragments for recall.
    for word in re.findall(r"[\u3400-\u9fff]{2,}|[a-z][a-z0-9_:-]{1,}", text):
        if word in STOP_WORDS:
            continue
        if len(word) <= 18:
            terms[word] = max(terms.get(word, 0), 5 + min(len(word), 8))
        if re.fullmatch(r"[\u3400-\u9fff]+", word):
            for size in (3, 2):
                for start in range(len(word) - size + 1):
                    gram = word[start:start + size]
                    if gram not in STOP_WORDS:
                        terms[gram] = max(terms.get(gram, 0), size)
    return sorted(terms, key=lambda term: (-terms[term], -len(term), term))[:18]


def query_domain(question: str) -> str | None:
    domains = [key for key, words in DOMAIN_TERMS.items() if any(word in question for word in words)]
    return domains[0] if len(domains) == 1 else None


def active_release():
    try:
        return RagCorpusRelease.objects.using("case_rag").filter(
            corpus_slug=CORPUS_SLUG, is_active=True,
        ).order_by("-created_at", "-pk").first()
    except (OperationalError, ProgrammingError):
        return None


def corpus_summary(release=None):
    release = release or active_release()
    result = {"available": bool(release), "sourceName": release.name if release else "中医参考医案库",
              "version": release.version if release else None,
              "checksumSha256": release.checksum_sha256 if release else None,
              "recordCount": release.record_count if release else 0,
              "retrievalMethod": "keyword", "categories": []}
    if release:
        counts = dict(CaseCorpusDocument.objects.using("case_rag").filter(release=release)
                      .values("category").annotate(total=Count("pk")).values_list("category", "total"))
        result["categories"] = [{"key": key, "label": label, "count": counts.get(key, 0)}
                                for key, label in CATEGORIES.items()]
    return result


def ranked_documents(release, question="", category="", *, infer_category=False):
    query = CaseCorpusDocument.objects.using("case_rag").filter(release=release)
    if category:
        query = query.filter(category=category)
    elif infer_category and (inferred := query_domain(question)):
        # General cases can concern any disease; include them in automatic recall.
        query = query.filter(Q(category=inferred) | Q(category=CaseCorpusDocument.Category.GENERAL))
    terms = query_terms(question)
    if not question.strip():
        return query.order_by("category", "source_record_id"), terms
    identifier = question.strip()
    if re.fullmatch(r"[\w:-]{1,160}", identifier) and any(character.isdigit() for character in identifier):
        by_id = query.filter(Q(source_record_id__iexact=identifier) | Q(source_record_id__iendswith=":" + identifier))
        if by_id.exists():
            return by_id.order_by("category", "source_record_id"), terms
    if not terms:
        return query.none(), terms
    condition = Q()
    score = Value(0, output_field=IntegerField())
    for term in terms:
        hit = Q(search_text__icontains=term) | Q(original_text__icontains=term)
        condition |= hit
        score += Case(When(hit, then=Value(3 + min(len(term), 8))), default=Value(0), output_field=IntegerField())
    # Rank the complete matching set before slicing; late records must remain eligible.
    return query.filter(condition).annotate(relevance_score=score).order_by("-relevance_score", "source_record_id"), terms


def excerpt(text, terms, limit=1100):
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    starts = {0}
    for term in terms:
        position = text.lower().find(term.lower())
        if position >= 0:
            starts.add(max(0, position - limit // 3))
    start = max(starts, key=lambda value: (sum(term.lower() in text[value:value + limit].lower() for term in terms), -value))
    return ("…" if start else "") + text[start:start + limit] + ("…" if start + limit < len(text) else "")


def serialize_document(document, *, terms=(), detail=False):
    structured = document.structured_data or {}
    clinical = {key: str(value) for key, value in structured.items()
                if key not in PROVENANCE_FIELDS and value is not None and str(value).strip()}
    clinical = dict(sorted(clinical.items(), key=lambda item: CLINICAL_PRIORITY.index(item[0]) if item[0] in CLINICAL_PRIORITY else len(CLINICAL_PRIORITY)))
    result = {"id": document.pk, "refId": f"case:{document.pk}", "caseId": document.source_record_id,
              "category": document.category, "categoryLabel": CATEGORIES.get(document.category, document.category),
              "title": document.title, "clinicalFeatures": clinical if detail else {key: value[:300] for key, value in list(clinical.items())[:7]},
              "source": document.source_reference, "sourceLink": document.source_link,
              "sourceDoctor": document.source_doctor, "sourceSheet": document.source_sheet,
              "sourceVersion": document.release.version, "recordStatus": document.extraction_status or "未标注人工核校状态",
              "originalExcerpt": excerpt(document.original_text, list(terms), 1100 if detail else 240)}
    if detail:
        result.update(originalText=document.original_text, structuredData=structured,
                      workbookName=document.source_workbook or document.release.workbook_name,
                      contentSha256=document.content_sha256,
                      sourceChecksumSha256=document.source_workbook_sha256 or document.release.checksum_sha256)
    return result


def build_case_snapshot(question: str, case_ids=None, category="") -> dict:
    release = active_release()
    result = {**corpus_summary(release), "matchedCount": 0, "truncated": False, "documents": []}
    if not release:
        if case_ids:
            raise CaseCorpusUnavailable("参考医案库尚不可用，请稍后重试。")
        return result
    ids = list(dict.fromkeys(case_ids or []))
    selected = list(CaseCorpusDocument.objects.using("case_rag").filter(release=release, pk__in=ids).select_related("release"))
    if len(selected) != len(ids):
        raise CaseCorpusUnavailable("所选参考医案已不属于当前版本，请回到医案库重新选择。")
    if not str(question).strip() and not ids:
        return result
    query, terms = ranked_documents(release, question, category, infer_category=True)
    result["matchedCount"] = query.count()
    selected.sort(key=lambda document: ids.index(document.pk))
    remaining = max(0, 4 - len(selected))
    documents = selected + list(query.exclude(pk__in=ids).select_related("release")[:remaining])
    for document in documents:
        record = serialize_document(document, terms=terms, detail=True)
        # Model input and task snapshots are bounded; full text stays in the reference library.
        record.pop("originalText")
        record.pop("structuredData")
        budget = 1700
        clinical = {}
        for key, value in record["clinicalFeatures"].items():
            if budget <= 0:
                break
            limit = min(240, budget)
            clinical[key] = value[:limit] + ("…" if len(value) > limit else "")
            budget -= len(key) + len(clinical[key])
        record["clinicalFeatures"] = clinical
        record["selected"] = document.pk in ids
        result["documents"].append(record)
    result["truncated"] = result["matchedCount"] > query.filter(pk__in=[document.pk for document in documents]).count()
    return result
