"""Name normalization and alias resolution migrated from origin/main@078d374."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path


ALIAS_DATA = json.loads((Path(__file__).resolve().parents[1] / "data" / "component_aliases.json").read_text(encoding="utf-8"))
COMPONENT_ALIASES = ALIAS_DATA["records"]
MAX_QUERY_TERMS = 8
MAX_COMPARE_TERMS = 100


def normalize_name(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    normalized = normalized.replace("β", "beta").replace("α", "alpha").replace("γ", "gamma")
    return re.sub(r"[\s_-]+", " ", normalized).strip()


def split_query_list(value: object, *, maximum: int) -> list[str]:
    terms = []
    seen = set()
    for raw in re.split(r"[,，、;；|\n\r]+", str(value or "")):
        term = raw.strip()
        key = normalize_name(term)
        if key and key not in seen:
            terms.append(term)
            seen.add(key)
    if len(terms) > maximum:
        raise ValueError(f"一次最多处理 {maximum} 个名称。")
    return terms


def alias_for_name(value: object) -> dict | None:
    normalized = normalize_name(value)
    if not normalized:
        return None
    for profile in COMPONENT_ALIASES:
        if any(normalize_name(alias) == normalized for alias in profile["aliases"]):
            return profile
    return None


def alias_for_component(value: object) -> dict | None:
    exact = alias_for_name(value)
    if exact:
        return exact
    normalized = normalize_name(value)
    for profile in COMPONENT_ALIASES:
        if profile.get("fuzzy") and any(
            normalize_name(alias) and normalize_name(alias) in normalized
            for alias in profile["aliases"]
        ):
            return profile
    return None


def resolve_component_names(query: str) -> dict:
    queries = split_query_list(query, maximum=MAX_QUERY_TERMS)
    candidates: list[dict] = []
    candidate_keys = set()
    profiles: dict[str, dict] = {}

    for term in queries:
        alias = alias_for_name(term)
        if alias:
            search_terms = alias.get("searchTerms") or [alias["english"]]
            for search_term in search_terms:
                exact = not bool(alias.get("fuzzy"))
                key = (normalize_name(search_term), exact)
                if key not in candidate_keys:
                    candidates.append({"term": search_term, "exact": exact})
                    candidate_keys.add(key)
            profiles[alias["english"]] = {
                **alias,
                "query": term,
                "matchedTerms": "、".join(alias["aliases"]),
            }
        else:
            key = (normalize_name(term), False)
            if key not in candidate_keys:
                candidates.append({"term": term, "exact": False})
                candidate_keys.add(key)

    if len(candidates) > MAX_QUERY_TERMS:
        raise ValueError(f"别名展开后的检索词超过 {MAX_QUERY_TERMS} 个上限；请缩小查询范围。")
    return {"queries": queries, "candidates": candidates, "profiles": list(profiles.values())}


def _resolve_compare_component(raw: str, side: str) -> dict:
    value = str(raw or "").strip()
    exact_alias = alias_for_name(value)
    family_alias = alias_for_component(value)
    alias = exact_alias or family_alias
    canonical_name = exact_alias["english"] if exact_alias else value
    normalized_key = normalize_name(canonical_name)
    family_key = normalize_name(alias["english"]) if alias and alias.get("fuzzy") else normalized_key
    return {
        "side": side,
        "input": value,
        "normalizedKey": normalized_key,
        "familyKey": family_key,
        "chinese": alias["chinese"] if alias else "",
        "english": exact_alias["english"] if exact_alias else value,
        "latin": alias["latin"] if alias else "",
        "matchedTerms": "、".join(alias["aliases"]) if alias else value,
        "exactAlias": bool(exact_alias),
        "familyAlias": bool(family_alias and family_alias.get("fuzzy")),
    }


def _unique_resolved_components(values: str, side: str) -> list[dict]:
    terms = split_query_list(values, maximum=MAX_COMPARE_TERMS)
    seen = set()
    rows = []
    for value in terms:
        row = _resolve_compare_component(value, side)
        if row["normalizedKey"] and row["normalizedKey"] not in seen:
            seen.add(row["normalizedKey"])
            rows.append(row)
    return rows


def compare_components_multilingual(detected_values: str, reference_values: str) -> dict:
    detected = _unique_resolved_components(detected_values, "detected")
    reference = _unique_resolved_components(reference_values, "reference")
    detected_by_key = {row["normalizedKey"]: row for row in detected}
    reference_by_key = {row["normalizedKey"]: row for row in reference}
    exact_keys = [key for key in detected_by_key if key in reference_by_key]
    detected_only = [row for row in detected if row["normalizedKey"] not in reference_by_key]
    reference_only = [row for row in reference if row["normalizedKey"] not in detected_by_key]
    exact_matches = []
    for key in exact_keys:
        left = detected_by_key[key]
        right = reference_by_key[key]
        exact_matches.append({
            "normalizedKey": key,
            "detectedInput": left["input"],
            "referenceInput": right["input"],
            "chinese": left["chinese"] or right["chinese"],
            "english": left["english"] or right["english"],
            "latin": left["latin"] or right["latin"],
            "status": "精确匹配",
        })

    family_matches = []
    for left in detected_only:
        for right in reference_only:
            if left["familyKey"] and left["familyKey"] == right["familyKey"] and left["normalizedKey"] != right["normalizedKey"]:
                family_matches.append({
                    "familyKey": left["familyKey"],
                    "detectedInput": left["input"],
                    "referenceInput": right["input"],
                    "detectedEnglish": left["english"],
                    "referenceEnglish": right["english"],
                    "familyName": left["chinese"] or right["chinese"] or left["english"] or right["english"],
                    "status": "同家族候选",
                })

    rows = [
        {**row, "group": "交集"} for row in exact_matches
    ] + [{
        "group": "仅检测", "normalizedKey": row["normalizedKey"], "input": row["input"],
        "chinese": row["chinese"], "english": row["english"], "latin": row["latin"], "status": "参考库未见",
    } for row in detected_only] + [{
        "group": "仅参考", "normalizedKey": row["normalizedKey"], "input": row["input"],
        "chinese": row["chinese"], "english": row["english"], "latin": row["latin"], "status": "检测值未见",
    } for row in reference_only]
    match_rate = round((len(exact_matches) / len(reference) * 100), 2) if reference else 0
    return {
        "aliasSource": ALIAS_DATA["source"],
        "aliasSourceCommit": ALIAS_DATA["sourceCommit"],
        "detected": detected,
        "reference": reference,
        "exactMatches": exact_matches,
        "detectedOnly": detected_only,
        "referenceOnly": reference_only,
        "familyMatches": family_matches,
        "rows": rows,
        "counts": {
            "detected": len(detected), "reference": len(reference), "matched": len(exact_matches),
            "detectedOnly": len(detected_only), "referenceOnly": len(reference_only),
            "familyMatches": len(family_matches), "matchRate": match_rate,
        },
    }
