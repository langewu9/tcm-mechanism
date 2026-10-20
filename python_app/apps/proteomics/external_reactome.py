"""Opt-in MyGene.info identifier resolution and Reactome enrichment.

Only selected identifier labels are sent to these services. The uploaded file,
non-selected rows, account details, and medical-case data are never included.
"""

import json
import re
from collections import defaultdict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


MYGENE_QUERY_URL = "https://mygene.info/v3/query"
REACTOME_ANALYSIS_URL = "https://reactome.org/AnalysisService/identifiers/projection/?pageSize=100&page=1"
REACTOME_VERSION_URL = "https://reactome.org/ContentService/data/database/version"
MAX_EXTERNAL_LABELS = 500
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
GENE_SYMBOL_INPUT_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{1,31}$")


class ExternalEnrichmentError(RuntimeError):
    """External-service failure without an echoed identifier or response body."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def _request_bytes(url, *, data=None, content_type=None, accept="application/json", timeout=25, max_bytes=MAX_RESPONSE_BYTES):
    headers = {"Accept": accept, "User-Agent": "TCM-Mechanism-Research/1.0"}
    if content_type:
        headers["Content-Type"] = content_type
    request = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        # Keep main's official endpoints, but do not forward selected identifiers
        # to a redirect destination or read an unbounded provider response.
        with build_opener(_NoRedirect).open(request, timeout=timeout) as response:
            if not 200 <= response.status < 300:
                raise ExternalEnrichmentError(f"外部服务返回 HTTP {response.status}。")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ExternalEnrichmentError("外部服务返回内容超过单次响应大小限制。")
            return response.status, body
    except HTTPError as exc:
        raise ExternalEnrichmentError(f"外部服务返回 HTTP {exc.code}。") from None
    except (URLError, TimeoutError, OSError) as exc:
        raise ExternalEnrichmentError("外部服务暂时无法连接。") from None


def _request_json(url, *, data=None, content_type=None, timeout=25):
    status, body = _request_bytes(url, data=data, content_type=content_type, timeout=timeout)
    if not 200 <= status < 300:
        raise ExternalEnrichmentError(f"外部服务返回 HTTP {status}。")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ExternalEnrichmentError("外部服务返回的数据无法解析。") from None


def _canonical(value):
    return str(value or "").strip().strip('"').upper()


def _unique_labels(values):
    output = []
    seen = set()
    for value in values:
        label = str(value or "").strip()
        key = _canonical(label)
        if label and key not in seen:
            output.append(label)
            seen.add(key)
    return output


def _query_mygene(labels, *, scopes, size):
    quoted = []
    for label in labels:
        escaped = label.replace("\\", "\\\\").replace('"', '\\"')
        quoted.append(f'"{escaped}"')
    data = urlencode(
        {
            "q": ",".join(quoted),
            "scopes": scopes,
            "fields": "symbol,name,entrezgene,taxid",
            "species": "human",
            "size": str(size),
        }
    ).encode("utf-8")
    response = _request_json(
        MYGENE_QUERY_URL,
        data=data,
        content_type="application/x-www-form-urlencoded",
        timeout=25,
    )
    if not isinstance(response, list):
        raise ExternalEnrichmentError("MyGene.info 返回的数据格式无效。")
    allowed = {_canonical(label) for label in labels}
    grouped = defaultdict(list)
    for item in response:
        if not isinstance(item, dict) or item.get("notfound"):
            continue
        query = _canonical(item.get("query"))
        symbol = str(item.get("symbol") or "").strip()
        taxid = item.get("taxid")
        if query not in allowed or not SYMBOL_PATTERN.fullmatch(symbol):
            continue
        if taxid is not None and str(taxid) != "9606":
            continue
        grouped[query].append(item)
    return grouped


def _mapping_record(label, hit):
    return {
        "query": label,
        "symbol": str(hit.get("symbol", "")).strip(),
        "name": str(hit.get("name") or "").strip() or None,
        "entrezGeneId": str(hit["entrezgene"]) if hit.get("entrezgene") is not None else None,
    }


def resolve_human_identifiers(labels):
    """Resolve exact human symbols first; keep fuzzy multi-hit names ambiguous."""
    unique_labels = _unique_labels(labels)
    eligible_labels = [label for label in unique_labels if len(label) <= 120]
    submitted = eligible_labels[:MAX_EXTERNAL_LABELS]
    if not submitted:
        return {
            "mappings": [], "ambiguous": [], "unmapped": [], "rejected": unique_labels,
            "truncatedCount": 0, "rejectedCount": len(unique_labels),
        }

    symbol_labels = [label for label in submitted if GENE_SYMBOL_INPUT_PATTERN.fullmatch(label)]
    mapped_by_key = {}
    ambiguous = set()
    if symbol_labels:
        exact_hits = _query_mygene(symbol_labels, scopes="symbol", size=1)
        for label in symbol_labels:
            candidates = exact_hits.get(_canonical(label), [])
            exact = next(
                (hit for hit in candidates if _canonical(hit.get("symbol")) == _canonical(label)),
                None,
            )
            if exact:
                mapped_by_key[_canonical(label)] = _mapping_record(label, exact)

    remaining = [label for label in submitted if _canonical(label) not in mapped_by_key]
    if remaining:
        fuzzy_hits = _query_mygene(remaining, scopes="symbol,alias,name", size=10)
        for label in remaining:
            hits = fuzzy_hits.get(_canonical(label), [])
            by_symbol = {}
            for hit in hits:
                by_symbol.setdefault(_canonical(hit.get("symbol")), hit)
            if len(by_symbol) == 1:
                mapped_by_key[_canonical(label)] = _mapping_record(label, next(iter(by_symbol.values())))
            elif len(by_symbol) > 1:
                ambiguous.add(_canonical(label))

    mappings = [mapped_by_key[_canonical(label)] for label in submitted if _canonical(label) in mapped_by_key]
    ambiguous_labels = [label for label in submitted if _canonical(label) in ambiguous]
    unmapped = [
        label for label in submitted
        if _canonical(label) not in mapped_by_key and _canonical(label) not in ambiguous
    ]
    return {
        "mappings": mappings,
        "ambiguous": ambiguous_labels,
        "unmapped": unmapped,
        "rejected": [label for label in unique_labels if len(label) > 120],
        "truncatedCount": len(eligible_labels) - len(submitted),
        "rejectedCount": len(unique_labels) - len(eligible_labels),
    }


def _finite_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 and number < float("inf") else None


def analyze_reactome_human_pathways(symbols):
    """Submit human symbols to the same projection endpoint used by main."""
    all_symbols = _unique_labels(symbols)
    eligible_symbols = [symbol for symbol in all_symbols if len(symbol) <= 120]
    unique_symbols = eligible_symbols[:MAX_EXTERNAL_LABELS]
    if not unique_symbols:
        return {
            "token": None,
            "sourceVersion": None,
            "pathways": [],
            "identifiersNotFound": 0,
            "pathwaysFound": 0,
            "submittedIdentifierCount": 0,
            "truncatedIdentifierCount": 0,
            "rejectedIdentifierCount": len(all_symbols),
        }

    payload = _request_json(
        REACTOME_ANALYSIS_URL,
        data="\n".join(unique_symbols).encode("utf-8"),
        content_type="text/plain;charset=utf-8",
        timeout=45,
    )
    if not isinstance(payload, dict):
        raise ExternalEnrichmentError("Reactome 返回的数据格式无效。")
    raw_pathways = payload.get("pathways")
    if not isinstance(raw_pathways, list):
        raise ExternalEnrichmentError("Reactome 返回的通路列表格式无效。")
    summary = payload.get("summary")
    if summary is None:
        summary = {}
    if not isinstance(summary, dict) or (summary.get("token") is not None and not isinstance(summary["token"], str)):
        raise ExternalEnrichmentError("Reactome 返回的分析摘要格式无效。")

    pathways = []
    for item in raw_pathways:
        if not isinstance(item, dict) or not isinstance(item.get("stId"), str) or not item["stId"] or not isinstance(item.get("name"), str) or not item["name"]:
            raise ExternalEnrichmentError("Reactome 返回的通路标识或名称格式无效。")
        entities = item.get("entities")
        if not isinstance(entities, dict):
            raise ExternalEnrichmentError("Reactome 返回的通路统计格式无效。")
        matched = _finite_number(entities.get("found"))
        total = _finite_number(entities.get("total"))
        p_value = _finite_number(entities.get("pValue"))
        fdr = _finite_number(entities.get("fdr"))
        coverage = _finite_number(entities.get("ratio"))
        if (
            matched is None or not matched.is_integer() or fdr is None or fdr > 1
            or (entities.get("total") is not None and (total is None or not total.is_integer() or total < matched))
            or (entities.get("pValue") is not None and (p_value is None or p_value > 1))
            or (entities.get("ratio") is not None and (coverage is None or coverage > 1))
        ):
            raise ExternalEnrichmentError("Reactome 返回的通路计数或概率值无效。")
        if matched < 2 or fdr > 0.05:
            continue
        species = item.get("species")
        if species is None:
            species = {}
        if not isinstance(species, dict) or (species.get("name") is not None and not isinstance(species["name"], str)):
            raise ExternalEnrichmentError("Reactome 返回的通路物种格式无效。")
        species_name = species.get("name") or "Homo sapiens"
        if species_name != "Homo sapiens":
            continue
        pathways.append(
            {
                "stableId": str(item["stId"]),
                "name": str(item["name"]),
                "species": species_name,
                "matchedEntities": int(matched),
                "totalEntities": int(total) if total is not None else None,
                "coverage": coverage,
                "pValue": p_value,
                "fdr": fdr,
            }
        )
    pathways = pathways[:50]

    version = None
    try:
        status, version_bytes = _request_bytes(
            REACTOME_VERSION_URL, accept="text/plain", timeout=10, max_bytes=4096
        )
        if 200 <= status < 300:
            version = version_bytes.decode("utf-8").strip() or None
    except (ExternalEnrichmentError, UnicodeDecodeError):
        pass

    return {
        "token": summary.get("token"),
        "sourceVersion": version,
        "pathways": pathways,
        "identifiersNotFound": int(_finite_number(payload.get("identifiersNotFound")) or 0),
        "pathwaysFound": int(_finite_number(payload.get("pathwaysFound")) or 0),
        "submittedIdentifierCount": len(unique_symbols),
        "truncatedIdentifierCount": len(eligible_symbols) - len(unique_symbols),
        "rejectedIdentifierCount": len(all_symbols) - len(eligible_symbols),
    }
