"""Streaming adapters for the versioned, local TCM target workbooks."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator

from openpyxl import load_workbook


@dataclass(frozen=True)
class SourceDefinition:
    slug: str
    name: str
    filename: str
    headers: tuple[str, ...]


@dataclass(frozen=True)
class EntityRef:
    entity_type: str
    namespace: str
    identifier: str
    label: str
    taxon_key: str = "unknown"
    match_method: str = "source_scoped"
    aliases: tuple[tuple[str, str, str], ...] = ()

    @property
    def all_identifiers(self) -> tuple[tuple[str, str, str], ...]:
        return ((self.namespace, self.identifier, self.match_method), *self.aliases)


@dataclass(frozen=True)
class RelationSpec:
    subject: EntityRef
    object: EntityRef
    relation_type: str
    evidence_type: str
    score: Decimal | None = None
    evidence_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedRecord:
    source_record_id: str
    payload_sha256: str
    payload: dict[str, Any]
    relations: tuple[RelationSpec, ...]
    status: str


SOURCES: dict[str, SourceDefinition] = {
    "batman": SourceDefinition(
        "batman",
        "BATMAN-TCM",
        "Batman全部数据.xlsx",
        ("Herb Name", "中文名", "Compound Name", "CID", "Gene ID", "Gene Name", "Score"),
    ),
    "herb": SourceDefinition(
        "herb",
        "HERB",
        "Herb数据库全部.xlsx",
        ("来源中药id", "Herb_cn_name", "Ingredient name", "Gene name"),
    ),
    "hit": SourceDefinition(
        "hit",
        "HIT",
        "HIT数据库全部.xlsx",
        (
            "Herb ID", "Chinese Pin Yin", "Chinese Character", "English_name", "Latin_name",
            "Compound Id", "Compound Name", "CAS", "Pubchem ID", "Chembl ID", "Formula",
            "Smiles", "Target ID", "Protein Name", "Symbol", "Uniprot",
        ),
    ),
    "tcmip": SourceDefinition(
        "tcmip",
        "TCMIP",
        "TCMIP全部数据.xlsx",
        ("中药", "成分名称", "靶标", "相似得分", "Activity", "参考文献"),
    ),
    "tcmsp": SourceDefinition(
        "tcmsp",
        "TCMSP",
        "tcmsp全部数据.xlsx",
        ("中药", "成分", "靶点基因"),
    ),
    "disease-herb": SourceDefinition(
        "disease-herb",
        "疾病-中药关联表",
        "疾病_中药.xlsx",
        ("疾病", "中药", "靶点基因"),
    ),
    "disease-targets": SourceDefinition(
        "disease-targets",
        "疾病靶点汇总表",
        "combined_results.xlsx",
        ("靶点基因", "疾病", "来源文件"),
    ),
}

GLOBAL_NAMESPACES = {"PUBCHEM_CID", "CHEMBL_COMPOUND", "CHEMBL_TARGET", "UNIPROT", "NCBI_GENE"}
_CHEMBL_RE = re.compile(r"^CHEMBL\d+$", re.IGNORECASE)
_DIGITS_RE = re.compile(r"^\d+$")


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _json_value(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)  # preserve invalid input; never silently convert it to zero
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _score(value: Any) -> Decimal | None:
    text = _clean(value)
    if not text:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    try:
        number = number.quantize(Decimal("0.000001"))
    except InvalidOperation:
        return None
    if abs(number) >= Decimal("10000"):
        return None
    return number


def _entity(
    source: str,
    kind: str,
    identifier: Any,
    label: Any,
    *,
    global_namespace: str = "",
    taxon_key: str = "unknown",
    aliases: tuple[tuple[str, str, str], ...] = (),
) -> EntityRef | None:
    external_id = _clean(identifier)
    display = _clean(label) or external_id
    if not external_id:
        external_id = display
    if not external_id or len(external_id) > 300 or not display:
        return None
    display = display[:300]
    namespace = global_namespace or f"{source}.{kind}_name"
    aliases = tuple(
        (alias_namespace, alias_id, method)
        for alias_namespace, alias_id, method in aliases
        if alias_namespace and len(alias_namespace) <= 80 and alias_id and len(alias_id) <= 300
    )
    return EntityRef(
        entity_type=kind,
        namespace=namespace,
        identifier=external_id,
        label=display,
        taxon_key=taxon_key,
        match_method="global_identifier" if global_namespace else "source_scoped",
        aliases=aliases,
    )


def _herb(source: str, identifier: Any, label: Any) -> EntityRef | None:
    source_id = _clean(identifier)
    if source_id:
        return _entity(source, "herb", source_id, label, global_namespace=f"{source}.herb_id")
    return _entity(source, "herb", label, label)


def _compound(
    source: str,
    label: Any,
    *,
    pubchem: Any = None,
    chembl: Any = None,
    source_id: Any = None,
) -> EntityRef | None:
    pubchem_id = _clean(pubchem)
    pubchem_id = re.sub(r"^(?:CID\s*:?\s*)", "", pubchem_id, flags=re.IGNORECASE)
    chembl_id = _clean(chembl).upper()
    source_compound_id = _clean(source_id)
    if pubchem_id and _DIGITS_RE.fullmatch(pubchem_id):
        aliases = []
        if _CHEMBL_RE.fullmatch(chembl_id):
            aliases.append(("CHEMBL_COMPOUND", chembl_id, "global_identifier"))
        if source_compound_id:
            aliases.append((f"{source}.compound_id", source_compound_id, "source_scoped"))
        return _entity(
            source, "compound", pubchem_id, label, global_namespace="PUBCHEM_CID", aliases=tuple(aliases)
        )
    if _CHEMBL_RE.fullmatch(chembl_id):
        aliases = (
            ((f"{source}.compound_id", source_compound_id, "source_scoped"),)
            if source_compound_id
            else ()
        )
        return _entity(
            source, "compound", chembl_id, label, global_namespace="CHEMBL_COMPOUND", aliases=aliases
        )
    if source_compound_id:
        return _entity(source, "compound", source_compound_id, label, global_namespace=f"{source}.compound_id")
    return _entity(source, "compound", label, label)


def _hit_target(identifier: Any, label: Any, uniprot: Any) -> EntityRef | None:
    uniprot_id = _clean(uniprot).upper()
    target_id = _clean(identifier).upper()
    target_label = _clean(label)
    if uniprot_id and re.fullmatch(r"[A-Z0-9]{6,10}(?:-\d+)?", uniprot_id):
        aliases = (
            (("CHEMBL_TARGET", target_id, "global_identifier"),)
            if _CHEMBL_RE.fullmatch(target_id)
            else ()
        )
        return _entity("hit", "protein", uniprot_id, target_label, global_namespace="UNIPROT", aliases=aliases)
    if _CHEMBL_RE.fullmatch(target_id):
        return _entity("hit", "protein", target_id, target_label, global_namespace="CHEMBL_TARGET")
    if target_id:
        return _entity(
            "hit", "protein", target_id, target_label, global_namespace="hit.target_id"
        )
    return _entity("hit", "gene", target_label, target_label)


def _gene_or_protein(
    source: str,
    identifier: Any,
    label: Any,
    *,
    uniprot: Any = None,
    chembl_target: Any = None,
) -> EntityRef | None:
    uniprot_id = _clean(uniprot).upper()
    if uniprot_id and re.fullmatch(r"[A-Z0-9]{6,10}(?:-\d+)?", uniprot_id):
        return _entity(source, "protein", uniprot_id, label, global_namespace="UNIPROT")
    target_id = _clean(chembl_target).upper()
    if target_id and _CHEMBL_RE.fullmatch(target_id):
        return _entity(source, "protein", target_id, label, global_namespace="CHEMBL_TARGET")
    gene_id = _clean(identifier)
    if gene_id and _DIGITS_RE.fullmatch(gene_id):
        return _entity(source, "gene", gene_id, label, global_namespace="NCBI_GENE")
    # The TCMSP/disease workbooks also contain full protein names. Do not
    # mislabel e.g. "Muscarinic acetylcholine receptor M1" as a gene symbol.
    text = gene_id or _clean(label)
    kind = "gene" if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,39}", text) else "protein"
    return _entity(source, kind, text, label)


def _canonical_payload(row: dict[str, Any]) -> tuple[dict[str, Any], str]:
    payload = {key: _json_value(value) for key, value in row.items()}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload, digest


def normalize_row(source: str, raw_row: dict[str, Any]) -> NormalizedRecord:
    """Convert one source row to preserved raw evidence and zero or more edges."""
    payload, digest = _canonical_payload(raw_row)
    values = {key: _clean(value) for key, value in raw_row.items()}
    edges: list[RelationSpec] = []

    if source == "batman":
        herb = _herb(source, None, values.get("中文名") or values.get("Herb Name"))
        compound = _compound(source, values.get("Compound Name"), pubchem=values.get("CID"))
        target = _gene_or_protein(source, values.get("Gene ID"), values.get("Gene Name"))
        score = _score(values.get("Score"))
        if herb and compound:
            edges.append(RelationSpec(herb, compound, "contains", "database_assertion"))
        if compound and target:
            raw_score = values.get("Score", "")
            evidence = "source_known_target" if raw_score.casefold().startswith("known target") else "predicted_target"
            edges.append(RelationSpec(compound, target, "targets", evidence, score, metadata={"score_raw": raw_score, "score_kind": "source_target_score_not_activity"}))
    elif source == "herb":
        herb = _herb(source, values.get("来源中药id"), values.get("Herb_cn_name"))
        compound = _compound(source, values.get("Ingredient name"))
        target = _gene_or_protein(source, None, values.get("Gene name"))
        if herb and compound:
            edges.append(RelationSpec(herb, compound, "contains", "database_assertion"))
        if compound and target:
            edges.append(RelationSpec(compound, target, "targets", "database_assertion"))
    elif source == "hit":
        herb = _herb(source, values.get("Herb ID"), values.get("Chinese Character") or values.get("Chinese Pin Yin"))
        compound = _compound(
            source,
            values.get("Compound Name"),
            pubchem=values.get("Pubchem ID"),
            chembl=values.get("Chembl ID"),
            source_id=values.get("Compound Id"),
        )
        target = _hit_target(
            values.get("Target ID"),
            values.get("Protein Name") or values.get("Symbol"),
            values.get("Uniprot"),
        )
        if herb and compound:
            edges.append(RelationSpec(herb, compound, "contains", "database_assertion"))
        if compound and target:
            edges.append(RelationSpec(compound, target, "targets", "database_assertion", metadata={"cas": values.get("CAS", ""), "formula": values.get("Formula", ""), "smiles": values.get("Smiles", ""), "symbol": values.get("Symbol", "")}))
    elif source in {"tcmip", "tcmsp"}:
        herb_name = values.get("中药", "")
        compound_name = values.get("成分名称") or values.get("成分", "")
        target_name = values.get("靶标") or values.get("靶点基因", "")
        herb = _herb(source, herb_name, herb_name)
        compound = _compound(source, compound_name)
        target = _gene_or_protein(source, None, target_name)
        if herb and compound:
            edges.append(RelationSpec(herb, compound, "contains", "database_assertion"))
        if compound and target:
            raw_score = values.get("相似得分", "") if source == "tcmip" else ""
            edges.append(RelationSpec(compound, target, "targets", "database_assertion", _score(raw_score), values.get("Activity", ""), {"reference": values.get("参考文献", ""), "score_raw": raw_score, "score_kind": "similarity_not_activity" if source == "tcmip" else "not_supplied"}))
    elif source == "disease-herb":
        disease_name = values.get("疾病", "")
        disease = _entity(source, "disease", disease_name, disease_name)
        herb_name = values.get("中药", "")
        herb = _herb(source, herb_name, herb_name)
        target_name = values.get("靶点基因", "")
        target = _gene_or_protein(source, None, target_name)
        if disease and herb and target:
            context = {"context": "disease_herb_target_triple", "herbLabel": herb.label, "diseaseLabel": disease.label}
            edges.append(RelationSpec(disease, herb, "disease_herb", "database_assertion", metadata=context))
            edges.append(RelationSpec(disease, target, "disease_herb_target", "database_assertion", metadata=context))
            edges.append(RelationSpec(herb, target, "herb_disease_target", "database_assertion", metadata=context))
    elif source == "disease-targets":
        disease_name = values.get("疾病", "")
        target_name = values.get("靶点基因", "")
        disease = _entity(source, "disease", disease_name, disease_name)
        target = _gene_or_protein(source, None, target_name)
        if disease and target:
            edges.append(RelationSpec(disease, target, "disease_target", "database_assertion", metadata={"source_file": values.get("来源文件", "")}))

    record_id = f"sha256:{digest}"
    return NormalizedRecord(
        source_record_id=record_id,
        payload_sha256=digest,
        payload=payload,
        relations=tuple(edges),
        status="accepted" if edges else "quarantined",
    )


def workbook_rows(path: Path, definition: SourceDefinition) -> Iterator[dict[str, Any]]:
    for _, row in workbook_indexed_rows(path, definition):
        yield row


def workbook_indexed_rows(path: Path, definition: SourceDefinition):
    """Yield workbook rows in read-only mode and fail closed on schema drift."""
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook.active
        rows = worksheet.iter_rows(values_only=True)
        try:
            headers = tuple(_clean(value) for value in next(rows))
        except StopIteration:
            raise ValueError(f"{path.name}: workbook is empty") from None
        if headers != definition.headers:
            raise ValueError(
                f"{path.name}: header mismatch; expected {definition.headers!r}, got {headers!r}"
            )
        for row_number, row in enumerate(rows, start=2):
            if not any(value is not None and _clean(value) for value in row):
                continue
            yield row_number, {header: row[index] if index < len(row) else None for index, header in enumerate(headers)}
    finally:
        workbook.close()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()
