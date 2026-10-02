"""Versioned STRING identifier crosswalk for existing human gene/protein entities.

This connector intentionally maps the platform's curated entities rather than
downloading STRING's full organism catalogue or creating/merging entities.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

from apps.core.models import EntityIdentifier, KnowledgeEntity
from apps.core.services.external_analysis import ExternalAnalysisError, _open_string, _string_api_release


STRING_SOURCE_SLUG = "string"
STRING_CONNECTOR = "string-human-identifier-crosswalk"
STRING_API_ROOT = "https://string-db.org/api"
MAX_LOCAL_ENTITIES = 50_000
MAPPING_BATCH_SIZE = 500
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_QUERY_LENGTH = 160
STRING_ID = re.compile(r"^9606\.ENSP[0-9]+$")
_GENE_SYMBOL = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{1,31}$")


class StringCatalogError(Exception):
    """Safe, user-facing error for retrieving or validating STRING mappings."""


@dataclass(frozen=True)
class StringProteinMapping:
    entity_id: int
    entity_stable_id: str
    query: str
    string_id: str
    preferred_name: str
    annotation: str


@dataclass(frozen=True)
class StringCatalogSnapshot:
    mappings: tuple[StringProteinMapping, ...]
    source_version: str
    api_endpoint: str
    checksum_sha256: str
    local_entity_count: int
    submitted_query_count: int
    ambiguous_local_count: int
    unmapped_query_count: int
    ambiguous_remote_count: int

    @property
    def release_version(self) -> str:
        return f"{self.source_version}+{self.checksum_sha256[:12]}"


def _canonical(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _is_human(entity: KnowledgeEntity) -> bool:
    if entity.organism.strip().casefold() in {"homo sapiens", "human"}:
        return True
    metadata = entity.metadata if isinstance(entity.metadata, dict) else {}
    taxon = metadata.get("taxonId", metadata.get("taxid"))
    if str(taxon or "").strip() == "9606":
        return True
    return str(metadata.get("organism") or metadata.get("species") or "").strip().casefold() in {
        "homo sapiens", "human"
    }


def _entity_query(entity: KnowledgeEntity, uniprot_accessions: list[str]) -> str:
    if uniprot_accessions:
        return sorted(uniprot_accessions)[0]
    metadata = entity.metadata if isinstance(entity.metadata, dict) else {}
    value = (
        metadata.get("symbol")
        or metadata.get("gene_symbol")
        or metadata.get("geneSymbol")
        or (entity.label if entity.entity_type == KnowledgeEntity.EntityType.GENE else "")
    )
    query = str(value or "").strip()
    if not query or len(query) > MAX_QUERY_LENGTH or any(ord(char) < 32 for char in query):
        return ""
    if entity.entity_type == KnowledgeEntity.EntityType.GENE and not _GENE_SYMBOL.fullmatch(query):
        return ""
    return query


def _local_query_groups() -> tuple[dict[str, list[tuple[KnowledgeEntity, str]]], int]:
    entities = KnowledgeEntity.objects.filter(
        entity_type__in=[KnowledgeEntity.EntityType.GENE, KnowledgeEntity.EntityType.PROTEIN],
        is_active=True,
    ).only("id", "entity_type", "stable_id", "label", "organism", "metadata")
    human_uniprot_entity_ids = set(
        EntityIdentifier.objects.filter(
            namespace="uniprot",
            is_active=True,
            source_release__source__slug="uniprot-human",
        ).values_list("entity_id", flat=True)
    )
    human_entities = []
    for entity in entities.iterator():
        if _is_human(entity) or entity.pk in human_uniprot_entity_ids:
            human_entities.append(entity)
            if len(human_entities) > MAX_LOCAL_ENTITIES:
                raise StringCatalogError("待映射的人类实体超过安全上限，请先分批整理本地知识目录。")

    accessions_by_entity: dict[int, list[str]] = {}
    entity_ids = [entity.pk for entity in human_entities]
    for offset in range(0, len(entity_ids), 1000):
        for entity_id, accession in EntityIdentifier.objects.filter(
            namespace="uniprot",
            is_active=True,
            source_release__source__slug="uniprot-human",
            entity_id__in=entity_ids[offset : offset + 1000],
        ).order_by("identifier").values_list("entity_id", "identifier"):
            accessions_by_entity.setdefault(entity_id, []).append(accession)

    groups: dict[str, list[tuple[KnowledgeEntity, str]]] = {}
    for entity in human_entities:
        query = _entity_query(entity, accessions_by_entity.get(entity.pk, []))
        if query:
            groups.setdefault(_canonical(query), []).append((entity, query))
    return groups, len(human_entities)


def parse_string_identifier_response(payload: bytes, queries: tuple[str, ...]) -> dict[int, tuple[str, str, str]]:
    """Validate one echo_query JSON response, keyed by the submitted query index."""
    try:
        records = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StringCatalogError("STRING 返回的标识映射不是有效 JSON。") from exc
    if not isinstance(records, list):
        raise StringCatalogError("STRING 返回的标识映射结构无效。")

    grouped: dict[int, list[tuple[str, str, str]]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise StringCatalogError("STRING 返回了无效的标识映射记录。")
        try:
            index = int(record.get("queryIndex"))
        except (TypeError, ValueError) as exc:
            raise StringCatalogError("STRING 映射缺少有效的查询序号。") from exc
        if index < 0 or index >= len(queries):
            raise StringCatalogError("STRING 映射的查询序号超出本批输入范围。")
        query_item = str(record.get("queryItem") or "").strip()
        if _canonical(query_item) != _canonical(queries[index]):
            raise StringCatalogError("STRING 映射返回的原始标识与请求不匹配。")
        if str(record.get("ncbiTaxonId") or "").strip() != "9606":
            raise StringCatalogError("STRING 返回了非人类蛋白映射，已停止同步。")
        string_id = str(record.get("stringId") or "").strip()
        if not STRING_ID.fullmatch(string_id):
            raise StringCatalogError("STRING 返回了无效的人类蛋白标识，已停止同步。")
        preferred_name = str(record.get("preferredName") or "").strip()[:300]
        annotation = str(record.get("annotation") or "").strip()[:2000]
        grouped.setdefault(index, []).append((string_id, preferred_name, annotation))

    # The API documents one best match per query. Refuse unexpected multiple
    # candidates rather than silently selecting one if that contract changes.
    return {index: values[0] for index, values in grouped.items() if len(values) == 1}


def _request_string_ids(queries: tuple[str, ...], api_base: str, *, delay_before_request: bool) -> dict[int, tuple[str, str, str]]:
    if delay_before_request:
        # STRING asks clients to leave at least one second between API calls.
        time.sleep(1)
    request = Request(
        f"{api_base}/json/get_string_ids",
        data=urlencode({
            "identifiers": "\r".join(queries),
            "species": "9606",
            "echo_query": "1",
            "caller_identity": "tcm_mechanism_platform",
        }).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "TCM-Mechanism-Research/1.0",
        },
        method="POST",
    )
    for attempt in range(3):
        try:
            with _open_string(request, timeout=45) as response:
                if response.status != 200:
                    raise StringCatalogError(f"STRING 标识映射失败（HTTP {response.status}）。")
                payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise StringCatalogError("STRING 单批映射超过安全响应大小限制。")
            return parse_string_identifier_response(payload, queries)
        except HTTPError as exc:
            if exc.code == 404:
                # STRING documents 404 when none of the identifiers resolve.
                return {}
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise StringCatalogError(f"STRING 标识映射失败（HTTP {exc.code}）。") from exc
            try:
                delay = min(10.0, max(1.0, float(exc.headers.get("Retry-After", 0))))
            except (TypeError, ValueError):
                delay = float(2**attempt)
            time.sleep(delay)
        except StringCatalogError:
            raise
        except (ExternalAnalysisError, URLError, TimeoutError, OSError) as exc:
            if attempt == 2:
                raise StringCatalogError("暂时无法连接 STRING，请稍后重试。") from exc
            time.sleep(float(2**attempt))
    raise StringCatalogError("STRING 标识映射失败，请稍后重试。")


def fetch_string_human_identifier_snapshot() -> StringCatalogSnapshot:
    groups, local_entity_count = _local_query_groups()
    ambiguous_local_keys = {key for key, rows in groups.items() if len({row[0].pk for row in rows}) != 1}
    unambiguous_groups = {key: rows for key, rows in groups.items() if key not in ambiguous_local_keys}
    query_entity = {key: rows[0] for key, rows in unambiguous_groups.items()}
    query_keys = sorted(query_entity)
    if not query_keys:
        raise StringCatalogError("本地没有可安全映射的人类基因/蛋白实体；请先导入并标注人类实体。")

    try:
        source_version, api_base, discovered = _string_api_release()
    except ExternalAnalysisError as exc:
        raise StringCatalogError(str(exc)) from exc

    mapped_by_query: dict[str, tuple[str, str, str]] = {}
    for offset in range(0, len(query_keys), MAPPING_BATCH_SIZE):
        batch_keys = query_keys[offset : offset + MAPPING_BATCH_SIZE]
        queries = tuple(query_entity[key][1] for key in batch_keys)
        # A version-discovery call immediately precedes the first batch when
        # no operator-pinned version is configured.
        delay = discovered or offset > 0
        response = _request_string_ids(queries, api_base, delay_before_request=delay)
        for index, value in response.items():
            mapped_by_query[batch_keys[index]] = value

    mappings: list[StringProteinMapping] = []
    for key, (entity, query) in query_entity.items():
        remote = mapped_by_query.get(key)
        if remote:
            string_id, preferred_name, annotation = remote
            mappings.append(StringProteinMapping(
                entity_id=entity.pk,
                entity_stable_id=entity.stable_id,
                query=query,
                string_id=string_id,
                preferred_name=preferred_name,
                annotation=annotation,
            ))

    entity_ids_by_string_id: dict[str, set[int]] = {}
    for mapping in mappings:
        entity_ids_by_string_id.setdefault(mapping.string_id, set()).add(mapping.entity_id)
    ambiguous_string_ids = {key for key, ids in entity_ids_by_string_id.items() if len(ids) > 1}
    safe_mappings = tuple(sorted(
        (row for row in mappings if row.string_id not in ambiguous_string_ids),
        key=lambda item: (item.entity_id, item.string_id),
    ))
    if not safe_mappings:
        raise StringCatalogError("STRING 没有返回可安全应用的人类标识映射；本次不会停用现有标识。")
    unmapped_query_count = len(query_keys) - len(mapped_by_query)
    checksum_payload = {
        "version": source_version,
        "endpoint": api_base,
        "entities": [
            {"id": entity.pk, "stableId": entity.stable_id, "query": query}
            for key, (entity, query) in sorted(query_entity.items())
        ],
        "ambiguousLocal": sorted(ambiguous_local_keys),
        "mappings": [
            {
                "entityId": row.entity_id,
                "stableId": row.entity_stable_id,
                "query": row.query,
                "stringId": row.string_id,
                "preferredName": row.preferred_name,
                "annotation": row.annotation,
            }
            for row in sorted(safe_mappings, key=lambda item: (item.entity_id, item.string_id))
        ],
        "ambiguousStringIds": sorted(ambiguous_string_ids),
    }
    checksum = hashlib.sha256(
        json.dumps(checksum_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return StringCatalogSnapshot(
        mappings=safe_mappings,
        source_version=source_version,
        api_endpoint=api_base,
        checksum_sha256=checksum,
        local_entity_count=local_entity_count,
        submitted_query_count=len(query_keys),
        ambiguous_local_count=sum(len({row[0].pk for row in rows}) for key, rows in groups.items() if key in ambiguous_local_keys),
        unmapped_query_count=unmapped_query_count,
        ambiguous_remote_count=len(ambiguous_string_ids),
    )
