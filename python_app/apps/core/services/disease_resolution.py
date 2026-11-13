"""Resolve intersection queries without merging broad disease search terms.

Exact catalogue/observed names and whole-term translations may select multiple
source-scoped entities. They remain distinct; their targets still join by PK.
The old regex/subtype expansion is useful for suggestions, not automatic union.
"""
import json
from pathlib import Path

from .catalog_identity import exact_entity_queryset
from .disease_names import MAX_QUERY_LENGTH, expand_disease_queries


EXACT_ALIASES = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "disease_exact_aliases.json").read_text(encoding="utf-8")
)
ENTITY_LIMIT = 50


def exact_disease_terms(query):
    """Return validated, curated whole-term translations shared by readers."""
    original = str(query or "").strip()
    if not original:
        raise ValueError("请输入疾病名称。")
    if len(original) > MAX_QUERY_LENGTH or any(ord(character) < 32 for character in original):
        raise ValueError("疾病名称过长或包含不支持的控制字符。")
    translations = EXACT_ALIASES["aliases"].get(original, [])
    return list(dict.fromkeys([original, *translations]))


def resolve_intersection_disease(query, *, entity_limit=ENTITY_LIMIT):
    requested_terms = exact_disease_terms(query)
    original = requested_terms[0]
    entities = {}
    resolved_terms = []
    truncated = False
    exact_found = False
    for term in requested_terms:
        rows = list(exact_entity_queryset("disease", term).select_related(
            "source_release", "source_release__source"
        ).order_by("stable_id")[:entity_limit + 1])
        if rows:
            resolved_terms.append(term)
            exact_found |= term == original
        truncated |= len(rows) > entity_limit
        for entity in rows[:entity_limit]:
            entities[entity.pk] = entity
    truncated |= len(entities) > entity_limit
    selected = sorted(entities.values(), key=lambda entity: entity.stable_id)[:entity_limit]

    # A missing translation must not fall back to a broader term or subtype.
    candidates = {}
    if not selected and len(original) <= MAX_QUERY_LENGTH:
        for term in expand_disease_queries(original):
            for entity in exact_entity_queryset("disease", term).select_related(
                "source_release", "source_release__source"
            ).order_by("stable_id")[:entity_limit]:
                candidate = candidates.setdefault(entity.label, {"label": entity.label, "sourceSlugs": set()})
                if entity.source_release:
                    candidate["sourceSlugs"].add(entity.source_release.source.slug)
    resolution = {
        "status": ("exact" if exact_found else "alias") if selected else (
            "needs_selection" if candidates else "unmatched"
        ),
        "input": original,
        "resolvedTerms": resolved_terms,
        "aliasVersion": EXACT_ALIASES["version"],
        "entitiesTruncated": truncated,
        "candidates": [
            {"label": label, "sourceSlugs": sorted(item["sourceSlugs"])}
            for label, item in sorted(candidates.items())
        ][:entity_limit],
    }
    return selected, resolution
