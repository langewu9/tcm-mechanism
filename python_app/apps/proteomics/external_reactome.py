"""Opt-in MyGene.info identifier resolution and Reactome enrichment.

Only selected identifier labels are sent to these services. The uploaded file,
non-selected rows, account details, and medical-case data are never included.
"""

import json
import re
from collections import defaultdict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


MYGENE_QUERY_URL = "https://mygene.info/v3/query"
REACTOME_ANALYSIS_URL = "https://reactome.org/AnalysisService/identifiers/projection/?pageSize=100&page=1"
REACTOME_VERSION_URL = "https://reactome.org/ContentService/data/database/version"
MAX_EXTERNAL_LABELS = 500
SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
GENE_SYMBOL_INPUT_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{1,31}$")


class ExternalEnrichmentError(RuntimeError):
    """External-service failure without an echoed identifier or response body."""


def _request_bytes(url, *, data=None, content_type=None, accept="application/json", timeout=25):
    headers = {"Accept": accept, "User-Agent": "TCM-Mechanism-Research/1.0"}
    if content_type:
        headers["Content-Type"] = content_type
    request = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
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

    pathways = []
    for item in payload.get("pathways", []) if isinstance(payload.get("pathways"), list) else []:
        if not isinstance(item, dict) or not item.get("stId") or not item.get("name"):
            continue
        entities = item.get("entities") if isinstance(item.get("entities"), dict) else {}
        matched = _finite_number(entities.get("found"))
        total = _finite_number(entities.get("total"))
        p_value = _finite_number(entities.get("pValue"))
        fdr = _finite_number(entities.get("fdr"))
        coverage = _finite_number(entities.get("ratio"))
        if matched is None or matched < 2 or fdr is None or fdr > 0.05:
            continue
        pathways.append(
            {
                "stableId": str(item["stId"]),
                "name": str(item["name"]),
                "species": (item.get("species") or {}).get("name", "Homo sapiens"),
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
            REACTOME_VERSION_URL, accept="text/plain", timeout=10
        )
        if 200 <= status < 300:
            version = version_bytes.decode("utf-8").strip() or None
    except ExternalEnrichmentError:
        pass

    return {
        "token": (payload.get("summary") or {}).get("token"),
        "sourceVersion": version,
        "pathways": pathways,
        "identifiersNotFound": int(_finite_number(payload.get("identifiersNotFound")) or 0),
        "pathwaysFound": int(_finite_number(payload.get("pathwaysFound")) or 0),
        "submittedIdentifierCount": len(unique_symbols),
        "truncatedIdentifierCount": len(eligible_symbols) - len(unique_symbols),
        "rejectedIdentifierCount": len(all_symbols) - len(eligible_symbols),
    }
