"""Curated, versioned PubChem compound-property snapshots via PUG REST."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


API_ROOT = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
DOCUMENTATION_URL = "https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest"
PROPERTIES = "IUPACName,MolecularFormula,MolecularWeight,CanonicalSMILES,InChIKey"
MAX_MAPPINGS = 2_000
BATCH_SIZE = 50
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_CID = re.compile(r"^[1-9][0-9]{0,9}$")


class PubChemCatalogError(Exception):
    """Safe, user-facing validation or availability error for PubChem."""


@dataclass(frozen=True)
class PubChemMapping:
    stable_id: str
    cid: str


@dataclass(frozen=True)
class PubChemCompound:
    stable_id: str
    cid: str
    iupac_name: str
    molecular_formula: str
    molecular_weight: str
    canonical_smiles: str
    inchikey: str


@dataclass(frozen=True)
class PubChemCatalogSnapshot:
    compounds: tuple[PubChemCompound, ...]
    source_version: str
    checksum_sha256: str
    page_count: int
    endpoint: str = API_ROOT

    @property
    def release_version(self) -> str:
        # PubChem does not publish one global snapshot version for these fields.
        # The full content/mapping hash keeps identical snapshots idempotent.
        return f"sha256-{self.checksum_sha256[:32]}"


def validate_pubchem_mappings(value: object) -> tuple[PubChemMapping, ...]:
    if not isinstance(value, list) or not value:
        raise PubChemCatalogError("请先在数据源配置中添加 PubChem CID 与本地成分稳定 ID 的人工映射。")
    if len(value) > MAX_MAPPINGS:
        raise PubChemCatalogError(f"单次 PubChem 同步最多支持 {MAX_MAPPINGS} 个成分映射。")

    mappings: list[PubChemMapping] = []
    seen_stable_ids: set[str] = set()
    seen_cids: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise PubChemCatalogError("PubChem 映射必须是 stableId 与 cid 组成的对象列表。")
        stable_id = item.get("stableId")
        cid_value = item.get("cid")
        if not isinstance(stable_id, str) or not stable_id.strip() or len(stable_id) > 160:
            raise PubChemCatalogError("每条 PubChem 映射都必须包含有效的本地成分 stableId。")
        cid = str(cid_value).strip() if isinstance(cid_value, (str, int)) else ""
        stable_id = stable_id.strip()
        if not _CID.fullmatch(cid):
            raise PubChemCatalogError("PubChem CID 必须是正整数。")
        if stable_id in seen_stable_ids:
            raise PubChemCatalogError("PubChem 映射中存在重复的本地成分 stableId。")
        if cid in seen_cids:
            raise PubChemCatalogError("PubChem 映射中存在重复 CID，请每个 CID 只关联一个本地成分。")
        seen_stable_ids.add(stable_id)
        seen_cids.add(cid)
        mappings.append(PubChemMapping(stable_id=stable_id, cid=cid))
    return tuple(sorted(mappings, key=lambda row: row.cid))


def _clean_property(value: object, max_length: int = 2000) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return str(value).strip()[:max_length]
    raise PubChemCatalogError("PubChem 返回了无法识别的化合物属性，已停止同步。")


def _parse_properties(payload: bytes, mappings: tuple[PubChemMapping, ...]) -> tuple[PubChemCompound, ...]:
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PubChemCatalogError("PubChem 返回的数据不是有效 JSON。") from exc
    rows = decoded.get("PropertyTable", {}).get("Properties") if isinstance(decoded, dict) else None
    if not isinstance(rows, list):
        raise PubChemCatalogError("PubChem 响应缺少化合物属性列表。")

    mapping_by_cid = {mapping.cid: mapping for mapping in mappings}
    parsed: dict[str, PubChemCompound] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise PubChemCatalogError("PubChem 响应含有无效化合物记录。")
        cid_value = row.get("CID")
        cid = str(cid_value) if isinstance(cid_value, (str, int)) else ""
        mapping = mapping_by_cid.get(cid)
        if mapping is None or cid in parsed:
            raise PubChemCatalogError("PubChem 返回的 CID 与已审核映射不一致。")
        parsed[cid] = PubChemCompound(
            stable_id=mapping.stable_id,
            cid=cid,
            iupac_name=_clean_property(row.get("IUPACName")),
            molecular_formula=_clean_property(row.get("MolecularFormula"), 120),
            molecular_weight=_clean_property(row.get("MolecularWeight"), 40),
            canonical_smiles=_clean_property(row.get("CanonicalSMILES"), 4000),
            inchikey=_clean_property(row.get("InChIKey"), 64),
        )
    if set(parsed) != set(mapping_by_cid):
        raise PubChemCatalogError("PubChem 响应记录数与配置 CID 数量不一致，已停止同步。")
    return tuple(sorted(parsed.values(), key=lambda row: row.cid))


def _request_batch(url: str) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "TCM-Mechanism/1.0 (curated compound annotation sync)",
        },
    )
    for attempt in range(4):
        try:
            with urlopen(request, timeout=45) as response:
                if response.geturl().split("/", 3)[2].lower() != "pubchem.ncbi.nlm.nih.gov":
                    raise PubChemCatalogError("PubChem 响应重定向到了非官方主机，已停止同步。")
                if response.status == 202:
                    raise PubChemCatalogError("PubChem 将该请求转为异步任务；请缩小映射批次或稍后重试。")
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise PubChemCatalogError("PubChem 响应超过单批安全大小限制。")
                return payload
        except HTTPError as exc:
            if exc.code in {429, 500, 502, 503, 504} and attempt < 3:
                time.sleep(min(2 ** attempt, 8))
                continue
            raise PubChemCatalogError(f"PubChem 返回 HTTP {exc.code}，请稍后重试。") from exc
        except (TimeoutError, URLError) as exc:
            if attempt < 3:
                time.sleep(min(2 ** attempt, 8))
                continue
            raise PubChemCatalogError("连接 PubChem 超时或失败，请检查网络后重试。") from exc
    raise PubChemCatalogError("PubChem 请求失败，请稍后重试。")


def fetch_pubchem_compound_catalog(value: object) -> PubChemCatalogSnapshot:
    mappings = validate_pubchem_mappings(value)
    compounds: list[PubChemCompound] = []
    for start in range(0, len(mappings), BATCH_SIZE):
        batch = mappings[start : start + BATCH_SIZE]
        cids = ",".join(quote(mapping.cid, safe="") for mapping in batch)
        url = f"{API_ROOT}/compound/cid/{cids}/property/{PROPERTIES}/JSON"
        compounds.extend(_parse_properties(_request_batch(url), batch))
        if start + BATCH_SIZE < len(mappings):
            time.sleep(0.34)

    stable_records = [
        {
            "stableId": row.stable_id,
            "cid": row.cid,
            "iupacName": row.iupac_name,
            "molecularFormula": row.molecular_formula,
            "molecularWeight": row.molecular_weight,
            "canonicalSmiles": row.canonical_smiles,
            "inchiKey": row.inchikey,
        }
        for row in compounds
    ]
    canonical = json.dumps(stable_records, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    checksum = hashlib.sha256(canonical).hexdigest()
    retrieved = datetime.now(timezone.utc).date().isoformat()
    return PubChemCatalogSnapshot(
        compounds=tuple(sorted(compounds, key=lambda row: row.stable_id)),
        source_version=f"snapshot-{retrieved}",
        checksum_sha256=checksum,
        page_count=(len(mappings) + BATCH_SIZE - 1) // BATCH_SIZE,
    )
