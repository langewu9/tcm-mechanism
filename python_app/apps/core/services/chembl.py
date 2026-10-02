"""Small, opt-in queries against the official ChEMBL Data Web Services."""

from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.core.cache import cache
from django.utils import timezone


CHEMBL_API_BASE = "https://www.ebi.ac.uk/chembl/api/data"
CHEMBL_COMPOUND_URL = "https://www.ebi.ac.uk/chembl/compound_report_card/{chembl_id}/"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MOLECULE_LIMIT = 10
ACTIVITY_LIMIT = 50
CHEMBL_ID_RE = re.compile(r"^CHEMBL[0-9]+$", re.IGNORECASE)


class ChemblServiceError(RuntimeError):
    """A safe upstream failure that contains no provider response body."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def _request_json(resource: str, params: dict[str, str] | None = None) -> dict:
    if resource not in {"status.json", "molecule/search.json", "activity.json"}:
        raise ValueError("Unsupported ChEMBL resource.")
    query = f"?{urlencode(params)}" if params else ""
    request = Request(
        f"{CHEMBL_API_BASE}/{resource}{query}",
        headers={"Accept": "application/json", "User-Agent": "TCM-Mechanism-Research/1.0"},
        method="GET",
    )
    try:
        with build_opener(_NoRedirect).open(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ChemblServiceError("ChEMBL 返回的数据超过单次查询限制。")
        payload = json.loads(raw.decode("utf-8"))
    except ChemblServiceError:
        raise
    except HTTPError as exc:
        raise ChemblServiceError(f"ChEMBL 返回 HTTP {exc.code}。") from None
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ChemblServiceError("ChEMBL 服务暂时无法连接或返回了无效数据。") from None
    if not isinstance(payload, dict):
        raise ChemblServiceError("ChEMBL 返回的数据格式无效。")
    return payload


def _source_release() -> dict[str, str]:
    cached = cache.get("chembl:release:v1")
    if isinstance(cached, dict) and cached.get("version"):
        return cached
    payload = _request_json("status.json")
    version = payload.get("chembl_db_version")
    release_date = payload.get("chembl_release_date")
    if payload.get("status") != "UP" or not isinstance(version, str) or not re.fullmatch(r"ChEMBL_[0-9]+", version):
        raise ChemblServiceError("ChEMBL 未能确认当前数据版本，请稍后重试。")
    release = {
        "version": version,
        "releaseDate": release_date if isinstance(release_date, str) else "",
    }
    cache.set("chembl:release:v1", release, timeout=3600)
    return release


def _clean_text(value, max_length: int = 500) -> str:
    return value[:max_length] if isinstance(value, str) else ""


def search_molecules(query: str) -> dict:
    release = _source_release()
    payload = _request_json(
        "molecule/search.json",
        {
            "q": query,
            "limit": str(MOLECULE_LIMIT),
            "only": "molecule_chembl_id,pref_name,molecule_type,max_phase,first_approval,natural_product,molecule_structures",
        },
    )
    raw_molecules = payload.get("molecules")
    if not isinstance(raw_molecules, list):
        raise ChemblServiceError("ChEMBL 化合物结果格式无效。")
    molecules = []
    for item in raw_molecules[:MOLECULE_LIMIT]:
        if not isinstance(item, dict):
            continue
        chembl_id = item.get("molecule_chembl_id")
        if not isinstance(chembl_id, str) or not CHEMBL_ID_RE.fullmatch(chembl_id):
            continue
        structure = item.get("molecule_structures")
        smiles = structure.get("canonical_smiles") if isinstance(structure, dict) else None
        molecules.append({
            "chemblId": chembl_id,
            "preferredName": _clean_text(item.get("pref_name") or item.get("preferred_name"), 250),
            "moleculeType": _clean_text(item.get("molecule_type"), 80),
            "maxPhase": _clean_text(item.get("max_phase"), 20),
            "firstApproval": _clean_text(item.get("first_approval"), 20),
            "naturalProduct": item.get("natural_product") if item.get("natural_product") in (0, 1) else None,
            "canonicalSmiles": _clean_text(smiles, 1000),
            "recordUrl": CHEMBL_COMPOUND_URL.format(chembl_id=chembl_id),
        })
    return {
        "source": "ChEMBL",
        "sourceVersion": release["version"],
        "releaseDate": release["releaseDate"],
        "query": query,
        "endpoint": f"{CHEMBL_API_BASE}/molecule/search",
        "retrievedAt": timezone.now().isoformat(),
        "limit": MOLECULE_LIMIT,
        "results": molecules,
    }


def molecule_activities(chembl_id: str) -> dict:
    normalized_id = chembl_id.upper()
    if not CHEMBL_ID_RE.fullmatch(normalized_id):
        raise ValueError("请输入有效的 ChEMBL 化合物编号。")
    release = _source_release()
    fields = "activity_id,molecule_chembl_id,standard_type,standard_relation,standard_value,standard_units,pchembl_value,target_chembl_id,target_pref_name,assay_chembl_id,assay_description,assay_type,document_chembl_id"
    common = {"molecule_chembl_id": normalized_id, "offset": "0", "only": fields}

    # Match main's `standard_value IS NOT NULL OR pchembl_value IS NOT NULL`
    # and `pchembl_value DESC NULLS LAST` without letting upstream null ordering
    # consume the capped first page.
    pchembl_payload = _request_json(
        "activity.json",
        {
            **common,
            "limit": str(ACTIVITY_LIMIT),
            "order_by": "-pchembl_value",
            "pchembl_value__isnull": "false",
        },
    )
    pchembl_activities = pchembl_payload.get("activities")
    if not isinstance(pchembl_activities, list):
        raise ChemblServiceError("ChEMBL 活性结果格式无效。")
    raw_activities = pchembl_activities[:ACTIVITY_LIMIT]
    first_meta = pchembl_payload.get("page_meta")
    first_total = first_meta.get("total_count") if isinstance(first_meta, dict) else None
    total = first_total if isinstance(first_total, int) else len(pchembl_activities)

    remaining = ACTIVITY_LIMIT - len(raw_activities)
    standard_payload = _request_json(
        "activity.json",
        {
            **common,
            "limit": str(max(remaining, 1)),
            "order_by": "standard_type",
            "standard_value__isnull": "false",
            "pchembl_value__isnull": "true",
        },
    )
    standard_activities = standard_payload.get("activities")
    if not isinstance(standard_activities, list):
        raise ChemblServiceError("ChEMBL 活性结果格式无效。")
    raw_activities.extend(standard_activities[:remaining])
    second_meta = standard_payload.get("page_meta")
    if isinstance(second_meta, dict):
        second_total = second_meta.get("total_count")
        if isinstance(second_total, int):
            total += second_total
    else:
        total += len(standard_activities)

    activities = []
    for item in raw_activities:
        if not isinstance(item, dict):
            continue
        activities.append({
            "activityId": item.get("activity_id") if isinstance(item.get("activity_id"), int) else None,
            "standardType": _clean_text(item.get("standard_type"), 80),
            "relation": _clean_text(item.get("standard_relation"), 20),
            "value": _clean_text(item.get("standard_value"), 50),
            "units": _clean_text(item.get("standard_units"), 40),
            "pchemblValue": _clean_text(item.get("pchembl_value"), 40),
            "targetId": _clean_text(item.get("target_chembl_id"), 30),
            "targetName": _clean_text(item.get("target_pref_name"), 250),
            "assayId": _clean_text(item.get("assay_chembl_id"), 30),
            "assayDescription": _clean_text(item.get("assay_description"), 1000),
            "assayType": _clean_text(item.get("assay_type"), 10),
            "documentId": _clean_text(item.get("document_chembl_id"), 30),
        })
    return {
        "source": "ChEMBL",
        "sourceVersion": release["version"],
        "releaseDate": release["releaseDate"],
        "chemblId": normalized_id,
        "endpoint": f"{CHEMBL_API_BASE}/activity",
        "retrievedAt": timezone.now().isoformat(),
        "resultLimit": ACTIVITY_LIMIT,
        "totalCount": total if isinstance(total, int) else len(activities),
        "truncated": isinstance(total, int) and total > len(activities),
        "results": activities,
    }
