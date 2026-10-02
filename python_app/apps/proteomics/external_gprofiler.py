"""Bounded, opt-in GO/KEGG enrichment through the official g:Profiler API."""

from __future__ import annotations

import json
import hashlib
import math
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


GPROFILER_BASE_URL = "https://biit.cs.ut.ee/gprofiler/api"
GPROFILER_PROFILE_URL = f"{GPROFILER_BASE_URL}/gost/profile/"
GPROFILER_VERSIONS_URL = f"{GPROFILER_BASE_URL}/util/data_versions/?organism=hsapiens"
GPROFILER_SOURCES = ("GO:BP", "GO:CC", "GO:MF", "KEGG")
MAX_QUERY_IDENTIFIERS = 500
MAX_BACKGROUND_IDENTIFIERS = 25_000
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class GProfilerError(RuntimeError):
    """Safe external-service error without identifiers or response bodies."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def _unique(values):
    output = []
    seen = set()
    for value in values:
        item = str(value or "").strip()
        key = item.casefold()
        if item and key not in seen:
            output.append(item)
            seen.add(key)
    return output


def _read_json(url, *, payload=None, timeout=45):
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={
            "Accept": "application/json",
            "User-Agent": "TCM-Mechanism-Research/1.0",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
        method="POST" if data is not None else "GET",
    )
    try:
        with build_opener(_NoRedirect).open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise GProfilerError(f"g:Profiler 返回 HTTP {exc.code}。") from None
    except (URLError, TimeoutError, OSError):
        raise GProfilerError("g:Profiler 服务暂时无法连接。") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise GProfilerError("g:Profiler 响应超过大小限制。")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise GProfilerError("g:Profiler 返回的数据格式无效。") from None
    if not isinstance(parsed, dict):
        raise GProfilerError("g:Profiler 返回的数据格式无效。")
    return parsed


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _count(value):
    number = _number(value)
    return int(number) if number is not None else None


def _version_label(versions):
    if not isinstance(versions, dict):
        raise GProfilerError("g:Profiler 未提供可追溯的数据版本。")
    service_version = str(versions.get("gprofiler_version") or versions.get("version") or "").strip()
    source_versions = versions.get("data_version") or versions.get("sources")
    if not service_version:
        raise GProfilerError("g:Profiler 未提供可追溯的服务版本。")
    if isinstance(source_versions, (dict, list)):
        suffix = json.dumps(source_versions, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if len(suffix) > 70:
            suffix = f"sources-{hashlib.sha256(suffix.encode()).hexdigest()[:16]}"
        else:
            suffix = suffix.replace(" ", "")
        return f"{service_version}:{suffix}"[:120]
    return service_version[:120]


def _safe_version_metadata(versions):
    """Keep provider release metadata bounded and JSON-safe for provenance storage."""
    def clean(value, depth=0):
        if depth > 3:
            return str(value)[:240]
        if isinstance(value, dict):
            return {
                str(key)[:120]: clean(item, depth + 1)
                for key, item in list(value.items())[:100]
            }
        if isinstance(value, list):
            return [clean(item, depth + 1) for item in value[:100]]
        if isinstance(value, str):
            return value[:240]
        if value is None or isinstance(value, (int, float, bool)):
            return value
        return str(value)[:240]

    return clean(versions)


def analyze_human_go_kegg(query_symbols, background_symbols):
    """Run custom-background over-representation analysis for human GO/KEGG terms."""
    query = _unique(query_symbols)
    background = _unique(background_symbols)
    if len(query) < 2:
        raise ValueError("GO/KEGG 富集至少需要 2 个可用的人类基因符号。")
    if len(query) > MAX_QUERY_IDENTIFIERS:
        query = query[:MAX_QUERY_IDENTIFIERS]
    if len(background) > MAX_BACKGROUND_IDENTIFIERS:
        raise ValueError(f"GO/KEGG 自定义背景最多支持 {MAX_BACKGROUND_IDENTIFIERS} 个标识。")
    if not set(symbol.casefold() for symbol in query).issubset(
        set(symbol.casefold() for symbol in background)
    ):
        background = _unique([*query, *background])
        if len(background) > MAX_BACKGROUND_IDENTIFIERS:
            raise ValueError(f"GO/KEGG 自定义背景最多支持 {MAX_BACKGROUND_IDENTIFIERS} 个标识。")

    versions = _read_json(GPROFILER_VERSIONS_URL, timeout=20)
    version = _version_label(versions)
    response = _read_json(
        GPROFILER_PROFILE_URL,
        payload={
            "organism": "hsapiens",
            "query": query,
            "background": background,
            "domain_scope": "custom",
            "sources": list(GPROFILER_SOURCES),
            "user_threshold": 0.05,
            "significance_threshold_method": "fdr",
            "all_results": False,
            "no_evidences": False,
        },
    )
    records = response.get("result")
    if not isinstance(records, list):
        raise GProfilerError("g:Profiler 返回的富集结果格式无效。")

    terms = []
    for item in records:
        if not isinstance(item, dict) or item.get("source") not in GPROFILER_SOURCES:
            continue
        native = str(item.get("native") or "").strip()
        name = str(item.get("name") or "").strip()
        adjusted = _number(item.get("p_value"))
        if not native or not name or adjusted is None or adjusted > 0.05:
            continue
        intersections = item.get("intersections")
        matched_ids = []
        if isinstance(intersections, list):
            for group in intersections:
                if isinstance(group, list):
                    matched_ids.extend(str(value)[:80] for value in group if value)
                elif isinstance(group, str) and group:
                    matched_ids.append(group[:80])
        terms.append({
            "termId": native[:160],
            "name": name[:500],
            "source": str(item["source"]),
            "pValue": None,
            "adjustedPValue": adjusted,
            "correctionMethod": "FDR",
            "intersectionSize": _count(item.get("intersection_size")),
            "querySize": _count(item.get("query_size")),
            "geneRatio": _number(item.get("precision")),
            "termSize": _count(item.get("term_size")),
            "effectiveDomainSize": _count(item.get("effective_domain_size")),
            "precision": _number(item.get("precision")),
            "recall": _number(item.get("recall")),
            "matchedIdentifiers": list(dict.fromkeys(matched_ids))[:500],
        })
    terms.sort(key=lambda term: (term["adjustedPValue"], term["source"], term["termId"]))
    metadata = response.get("meta") if isinstance(response.get("meta"), dict) else {}
    return {
        "sourceVersion": version,
        "dataVersions": _safe_version_metadata(versions),
        "terms": terms[:500],
        "queryCount": len(query),
        "queryTruncatedCount": max(0, len(_unique(query_symbols)) - len(query)),
        "backgroundCount": len(background),
        "backgroundType": "measured_identifiers_custom",
        "organism": "Homo sapiens",
        "sources": list(GPROFILER_SOURCES),
        "threshold": 0.05,
        "correctionMethod": "FDR",
        "rawPValuesReturned": False,
        "providerMetadata": {
            str(key)[:80]: str(value)[:240]
            for key, value in metadata.items()
            if isinstance(value, (str, int, float, bool))
        },
    }
