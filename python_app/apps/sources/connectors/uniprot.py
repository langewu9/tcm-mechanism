"""Versioned connector for the reviewed human UniProtKB protein catalogue."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen


API_ROOT = "https://rest.uniprot.org"
SEARCH_URL = f"{API_ROOT}/uniprotkb/search"
QUERY = "reviewed:true AND organism_id:9606"
FIELDS = "accession,protein_name,gene_primary,gene_names,organism_name"
PAGE_SIZE = 500
MAX_RECORDS = 50_000
MAX_PAGE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_PAGES = (MAX_RECORDS // PAGE_SIZE) + 2
_NEXT_LINK = re.compile(r'<([^>]+)>\s*;\s*rel="next"', re.IGNORECASE)
_ACCESSION = re.compile(
    r"^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})$"
)


class UniProtCatalogError(Exception):
    """Safe, user-facing error for retrieving or validating a UniProt snapshot."""


@dataclass(frozen=True)
class UniProtProtein:
    accession: str
    protein_name: str
    primary_gene: str
    gene_names: tuple[str, ...]
    organism: str = "Homo sapiens"


@dataclass(frozen=True)
class UniProtCatalogSnapshot:
    proteins: tuple[UniProtProtein, ...]
    source_version: str
    source_release_date: str | None
    checksum_sha256: str
    total_results: int
    page_count: int
    endpoint: str = SEARCH_URL

    @property
    def release_version(self) -> str:
        return f"{self.source_version}+{self.checksum_sha256[:12]}"


def _parse_tsv_page(payload: bytes) -> tuple[UniProtProtein, ...]:
    try:
        lines = payload.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise UniProtCatalogError("UniProt 返回的数据不是有效的 UTF-8 TSV。") from exc
    if not lines:
        raise UniProtCatalogError("UniProt 返回了空白页面。")

    header = lines[0].split("\t")
    expected = ["Entry", "Protein names", "Gene Names (primary)", "Gene Names", "Organism"]
    if header != expected:
        raise UniProtCatalogError("UniProt TSV 列结构发生变化，请先检查接口字段再同步。")

    proteins: list[UniProtProtein] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = line.split("\t")
        if len(cells) != len(expected):
            raise UniProtCatalogError("UniProt TSV 存在列数不一致的记录，已停止同步。")
        accession, protein_name, primary_gene, gene_names, organism = (
            value.strip() for value in cells
        )
        if not _ACCESSION.fullmatch(accession):
            raise UniProtCatalogError("UniProt 返回了无效的 accession，已停止同步。")
        if organism not in {"Homo sapiens", "Homo sapiens (Human)"}:
            raise UniProtCatalogError("UniProt 返回了非人类条目，已停止同步。")
        proteins.append(
            UniProtProtein(
                accession=accession,
                protein_name=protein_name[:300],
                primary_gene=primary_gene[:120],
                gene_names=tuple(dict.fromkeys(gene_names.split()))[:40],
            )
        )
    return tuple(proteins)


def parse_uniprot_human_catalog(payload: bytes, *, source_version: str) -> tuple[UniProtProtein, ...]:
    """Parse one complete TSV payload; useful for imported release snapshots and tests."""
    rows = _parse_tsv_page(payload)
    unique: dict[str, UniProtProtein] = {}
    for row in rows:
        unique[row.accession] = row
    if not unique:
        raise UniProtCatalogError("UniProt 目录中没有有效的人类审核蛋白条目。")
    if len(unique) > MAX_RECORDS:
        raise UniProtCatalogError("UniProt 人类目录超过安全记录数上限。")
    if not source_version.strip() or len(source_version) > 40:
        raise UniProtCatalogError("UniProt 未提供可识别的版本号。")
    return tuple(unique[key] for key in sorted(unique))


def _read_page(url: str) -> tuple[bytes, dict[str, str]]:
    request = Request(
        url,
        headers={
            "Accept": "text/plain",
            "User-Agent": "TCM-Mechanism/1.0 (research catalogue sync)",
        },
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=45) as response:
                if response.status != 200:
                    raise UniProtCatalogError(f"UniProt 请求失败（HTTP {response.status}）。")
                payload = response.read(MAX_PAGE_BYTES + 1)
                headers = {key.lower(): value for key, value in response.headers.items()}
            if len(payload) > MAX_PAGE_BYTES:
                raise UniProtCatalogError("UniProt 单页超过安全下载大小上限。")
            return payload, headers
        except HTTPError as exc:
            retryable = exc.code in {429, 500, 502, 503, 504}
            if not retryable or attempt == 2:
                raise UniProtCatalogError(f"UniProt 请求失败（HTTP {exc.code}）。") from exc
            try:
                delay = min(5.0, max(0.25, float(exc.headers.get("Retry-After", 0))))
            except (TypeError, ValueError):
                delay = min(5.0, 0.5 * (2**attempt))
            time.sleep(delay)
        except (TimeoutError, URLError, OSError) as exc:
            if attempt == 2:
                raise UniProtCatalogError("暂时无法连接 UniProt，请稍后重试。") from exc
            time.sleep(min(5.0, 0.5 * (2**attempt)))
    raise UniProtCatalogError("UniProt 请求失败，请稍后重试。")


def _validate_next_url(current_url: str, link_header: str) -> str | None:
    match = _NEXT_LINK.search(link_header)
    if not match:
        return None
    next_url = urljoin(current_url, match.group(1))
    parsed = urlsplit(next_url)
    if parsed.scheme != "https" or parsed.hostname != "rest.uniprot.org":
        raise UniProtCatalogError("UniProt 返回了不受信任的分页地址，已停止同步。")
    return next_url


def fetch_uniprot_human_catalog() -> UniProtCatalogSnapshot:
    """Download every reviewed human entry, following the server's Link pagination."""
    initial_url = f"{SEARCH_URL}?{urlencode({'query': QUERY, 'format': 'tsv', 'fields': FIELDS, 'size': PAGE_SIZE})}"
    url: str | None = initial_url
    seen_urls: set[str] = set()
    page_payloads: list[bytes] = []
    proteins: dict[str, UniProtProtein] = {}
    checksum = hashlib.sha256()
    total_bytes = 0
    expected_total: int | None = None
    source_version: str | None = None
    release_date: str | None = None

    while url:
        if url in seen_urls or len(seen_urls) >= MAX_PAGES:
            raise UniProtCatalogError("UniProt 分页重复或超过安全页数上限。")
        seen_urls.add(url)
        payload, headers = _read_page(url)
        total_bytes += len(payload)
        if total_bytes > MAX_TOTAL_BYTES:
            raise UniProtCatalogError("UniProt 目录超过安全下载大小上限。")
        checksum.update(payload)
        checksum.update(b"\n")
        parsed = _parse_tsv_page(payload)
        for protein in parsed:
            proteins[protein.accession] = protein
            if len(proteins) > MAX_RECORDS:
                raise UniProtCatalogError("UniProt 人类目录超过安全记录数上限。")

        try:
            page_total = int(headers["x-total-results"])
        except (KeyError, ValueError) as exc:
            raise UniProtCatalogError("UniProt 响应缺少有效的总记录数。") from exc
        page_version = headers.get("x-uniprot-release", "").strip()
        if not page_version:
            raise UniProtCatalogError("UniProt 响应缺少版本号，不能建立可追溯快照。")
        if expected_total is None:
            expected_total = page_total
            source_version = page_version
            release_date = headers.get("x-uniprot-release-date") or None
        elif page_total != expected_total or page_version != source_version:
            raise UniProtCatalogError("UniProt 在分页期间切换了目录版本，请重新预览。")
        url = _validate_next_url(url, headers.get("link", ""))

    if expected_total is None or expected_total <= 0:
        raise UniProtCatalogError("UniProt 响应缺少有效的人类条目总数。")
    if expected_total > MAX_RECORDS:
        raise UniProtCatalogError("UniProt 人类目录超过安全记录数上限。")
    if len(proteins) != expected_total:
        raise UniProtCatalogError("UniProt 分页记录数与服务端总数不一致，请重新预览。")
    return UniProtCatalogSnapshot(
        proteins=tuple(proteins[key] for key in sorted(proteins)),
        source_version=source_version or "",
        source_release_date=release_date,
        checksum_sha256=checksum.hexdigest(),
        total_results=expected_total,
        page_count=len(seen_urls),
    )
