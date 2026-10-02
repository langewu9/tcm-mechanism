"""Reactome pathway catalogue connector migrated from the main-branch logic."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CATALOG_URL = "https://reactome.org/download/current/ReactomePathways.txt"
VERSION_URL = "https://reactome.org/ContentService/data/database/version"
MAX_CATALOG_BYTES = 40 * 1024 * 1024
MAX_PATHWAYS = 100_000
HUMAN_SPECIES = "Homo sapiens"
_HUMAN_PATHWAY_ID = re.compile(r"^R-HSA-[0-9]+$")


class ReactomeCatalogError(Exception):
    """Safe, user-facing error for retrieving or parsing a catalogue snapshot."""


@dataclass(frozen=True)
class ReactomePathway:
    stable_id: str
    name: str
    species: str = HUMAN_SPECIES


@dataclass(frozen=True)
class ReactomeCatalogSnapshot:
    pathways: tuple[ReactomePathway, ...]
    source_version: str | None
    checksum_sha256: str
    endpoint: str = CATALOG_URL

    @property
    def release_version(self) -> str:
        prefix = (self.source_version or "unversioned")[:106]
        return f"{prefix}+{self.checksum_sha256[:12]}"


def _read_url(url: str, *, timeout: int, max_bytes: int | None = None) -> bytes:
    request = Request(url, headers={"Accept": "text/plain", "User-Agent": "TCM-Mechanism/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise ReactomeCatalogError(f"Reactome 请求失败（HTTP {response.status}）。")
            payload = response.read((max_bytes + 1) if max_bytes else -1)
    except HTTPError as exc:
        raise ReactomeCatalogError(f"Reactome 请求失败（HTTP {exc.code}）。") from exc
    except (TimeoutError, URLError, OSError) as exc:
        raise ReactomeCatalogError("暂时无法连接 Reactome，请稍后重试。") from exc
    if max_bytes is not None and len(payload) > max_bytes:
        raise ReactomeCatalogError("Reactome 通路目录超过安全导入大小限制。")
    return payload


def parse_human_pathway_catalog(payload: bytes) -> tuple[ReactomePathway, ...]:
    try:
        content = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ReactomeCatalogError("Reactome 通路目录不是有效的 UTF-8 文本。") from exc

    unique: dict[str, ReactomePathway] = {}
    for line in content.splitlines():
        columns = line.split("\t")
        if len(columns) < 3:
            continue
        stable_id, name, species = (column.strip() for column in columns[:3])
        if not _HUMAN_PATHWAY_ID.fullmatch(stable_id) or not name or species != HUMAN_SPECIES:
            continue
        unique[stable_id] = ReactomePathway(stable_id=stable_id, name=name)
        if len(unique) > MAX_PATHWAYS:
            raise ReactomeCatalogError("Reactome 通路目录超过安全记录数限制。")

    if not unique:
        raise ReactomeCatalogError("Reactome 目录中未找到有效的人类通路记录。")
    return tuple(unique[key] for key in sorted(unique))


def fetch_reactome_human_pathway_catalog() -> ReactomeCatalogSnapshot:
    """Fetch current human pathways and their content checksum."""
    payload = _read_url(CATALOG_URL, timeout=60, max_bytes=MAX_CATALOG_BYTES)
    try:
        version_bytes = _read_url(VERSION_URL, timeout=10, max_bytes=4096)
        source_version = version_bytes.decode("utf-8").strip() or None
    except ReactomeCatalogError:
        # The catalogue endpoint is the source of truth; version lookup is optional.
        source_version = None
    return ReactomeCatalogSnapshot(
        pathways=parse_human_pathway_catalog(payload),
        source_version=source_version,
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
    )
