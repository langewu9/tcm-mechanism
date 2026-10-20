"""Exact-pattern disease query aliases migrated from origin/main@078d374."""

from __future__ import annotations

import json
import re
from pathlib import Path

from django.db.models import Q

from apps.core.models import KnowledgeEntity


ALIAS_DATA = json.loads((Path(__file__).resolve().parents[1] / "data" / "disease_aliases.json").read_text(encoding="utf-8"))
MAX_QUERY_LENGTH = 120
MAX_EXPANDED_QUERIES = 40


def expand_disease_queries(query: str) -> list[str]:
    original = str(query or "").strip()
    if not original:
        raise ValueError("请输入疾病名称。")
    if len(original) > MAX_QUERY_LENGTH or any(ord(character) < 32 for character in original):
        raise ValueError("疾病名称过长或包含不支持的控制字符。")

    aliases = [original]
    for entry in ALIAS_DATA["records"]:
        patterns = entry.get("patterns", [])
        if any(re.search(pattern["pattern"], original) for pattern in patterns):
            aliases.extend(entry.get("aliases", []))
    unique = list(dict.fromkeys(term.strip() for term in aliases if term.strip()))
    return unique[:MAX_EXPANDED_QUERIES]


def _entity_search_texts(entity: KnowledgeEntity) -> list[str]:
    values = [entity.label, entity.stable_id]
    synonyms = entity.synonyms
    if isinstance(synonyms, list):
        values.extend(value for value in synonyms if isinstance(value, str))
    elif isinstance(synonyms, dict):
        values.extend(value for value in synonyms.values() if isinstance(value, str))
    return [value.casefold() for value in values if value]


def matched_disease_queries(entity: KnowledgeEntity, queries: list[str]) -> list[str]:
    search_texts = _entity_search_texts(entity)
    return [
        query for query in queries
        if any(query.casefold() in value for value in search_texts)
    ]


def disease_entity_queryset(queries: list[str]):
    conditions = Q()
    for query in queries:
        conditions |= (
            Q(label__icontains=query)
            | Q(stable_id__icontains=query)
            | Q(synonyms__icontains=query)
        )
    return KnowledgeEntity.objects.filter(
        entity_type=KnowledgeEntity.EntityType.DISEASE,
        is_active=True,
        source_release__source__enabled=True,
    ).filter(conditions).select_related("source_release", "source_release__source").distinct().order_by("label", "stable_id")
