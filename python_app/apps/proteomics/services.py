"""Validated table parsing and local-evidence proteomics analysis.

The result contract follows the reusable ``src/lib/proteomics.ts`` logic on
``origin/main`` while keeping uncertain mappings explicit and preserving a
row-level QC trail in relational storage.
"""

import csv
import io
import math
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import PurePosixPath
from typing import Any, Iterable

import xlrd
from django.conf import settings
from django.core.files.storage import default_storage
from openpyxl import load_workbook

from apps.core.models import AnalysisTask, EvidenceRelation, KnowledgeEntity
from apps.proteomics.models import ProteomicsRowResult


ALGORITHM_VERSION = "proteomics-py-1.1"
MAX_CELL_CHARACTERS = 50_000
MAX_XLSX_EXPANDED_BYTES = 512 * 1024 * 1024
PATHWAY_RELATION_TYPES = {
    "genepathway",
    "proteinpathway",
    "targetpathway",
    "participatesin",
    "annotatedtopathway",
    "associatedwithpathway",
}
ALIASES = {
    "gene_column": [
        "gene", "gene_symbol", "gene symbol", "symbol", "genes", "基因", "基因名",
        "基因符号", "靶点", "靶点基因",
    ],
    "protein_column": [
        "protein", "protein_name", "protein name", "uniprot", "蛋白", "蛋白质",
        "蛋白名称", "蛋白名",
    ],
    "log2fc_column": [
        "log2fc", "log2_fc", "log2 fold change", "log2foldchange", "logfc", "fc",
        "log2倍数变化", "差异倍数",
    ],
    "p_value_column": ["pvalue", "p_value", "p value", "p-value", "p值", "p 值"],
    "fdr_column": [
        "fdr", "adj.p.val", "adj_p_val", "padj", "adjusted p value", "qvalue", "q-value",
        "校正p值", "校正 p 值",
    ],
    "direction_column": ["direction", "regulation", "change", "trend", "变化方向", "上调下调"],
}
MISSING_VALUES = {"", "na", "nan", "null", "none", "-"}


class ProteomicsInputError(ValueError):
    """An actionable validation error that is safe to show to the researcher."""


@dataclass(frozen=True)
class ParsedTable:
    columns: list[str]
    rows: list[dict[str, str]]
    sheet_name: str


@dataclass(frozen=True)
class ColumnMapping:
    gene_column: str
    protein_column: str
    log2fc_column: str
    p_value_column: str
    fdr_column: str
    direction_column: str

    def as_dict(self) -> dict[str, str]:
        return {
            "geneColumn": self.gene_column,
            "proteinColumn": self.protein_column,
            "log2FcColumn": self.log2fc_column,
            "pValueColumn": self.p_value_column,
            "fdrColumn": self.fdr_column,
            "directionColumn": self.direction_column,
        }


@dataclass
class AnalyzedRow:
    row_index: int
    raw: dict[str, str]
    original_label: str
    protein_name: str
    log2_fold_change: float | None
    p_value: float | None
    fdr: float | None
    direction: str
    mapping_status: str
    normalized_symbol: str
    mapping_source: str
    matched_entity: KnowledgeEntity | None
    selected: bool
    exclusion_reasons: list[str]
    qc_warnings: list[str]


def _normalize_column(value: str) -> str:
    return re.sub(r"[\s_\-.()（）]+", "", value.strip().lower())


def _canonical_label(value: str) -> str:
    return value.strip().strip('"').upper()


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if len(text) > MAX_CELL_CHARACTERS:
        raise ProteomicsInputError("文件中单元格内容过长，请先拆分或清理该字段。")
    return text


def _unique_headers(values: list[Any]) -> list[str]:
    headers: list[str] = []
    counts: Counter[str] = Counter()
    for index, value in enumerate(values, start=1):
        base = _cell_text(value) or f"column_{index}"
        counts[base] += 1
        headers.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
    return headers


def _rows_to_records(headers: list[str], rows: Iterable[list[Any]]) -> list[dict[str, str]]:
    output = []
    for values in rows:
        cells = [_cell_text(value) for value in values]
        if not any(cells):
            continue
        if len(cells) > len(headers) and any(cells[len(headers) :]):
            raise ProteomicsInputError("数据行的字段数多于表头列数，请检查文件格式。")
        if (len(output) + 1) * len(headers) > settings.PROTEOMICS_MAX_CELLS:
            raise ProteomicsInputError(
                f"文件超过当前单次分析的 {settings.PROTEOMICS_MAX_CELLS:,} 个单元格上限，请拆分文件。"
            )
        output.append({header: cells[index] if index < len(cells) else "" for index, header in enumerate(headers)})
        if len(output) > settings.PROTEOMICS_MAX_ROWS:
            raise ProteomicsInputError(
                f"单次最多分析 {settings.PROTEOMICS_MAX_ROWS:,} 行，请先拆分文件。"
            )
    return output


def _parse_delimited(payload: bytes, extension: str) -> ParsedTable:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = payload.decode("gb18030")
        except UnicodeDecodeError as exc:
            raise ProteomicsInputError("无法识别文本编码，请将文件另存为 UTF-8 CSV/TSV。") from exc
    if "\x00" in text:
        raise ProteomicsInputError("文本文件包含非法二进制内容。")
    if extension == ".tsv":
        delimiter = "\t"
    else:
        try:
            delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
        header_row = next(reader, [])
    except csv.Error as exc:
        raise ProteomicsInputError("CSV/TSV 格式无法解析，请检查引号和分隔符。") from exc
    if not header_row:
        return ParsedTable([], [], "")
    headers = _unique_headers(header_row)
    if len(headers) > settings.PROTEOMICS_MAX_COLUMNS:
        raise ProteomicsInputError(f"单次最多支持 {settings.PROTEOMICS_MAX_COLUMNS} 列。")
    try:
        records = _rows_to_records(headers, (list(row) for row in reader))
    except csv.Error as exc:
        raise ProteomicsInputError("CSV/TSV 格式无法解析，请检查引号和分隔符。") from exc
    return ParsedTable(headers, records, "")


def _parse_xlsx(payload: bytes) -> ParsedTable:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            expanded_size = sum(item.file_size for item in archive.infolist())
            if expanded_size > MAX_XLSX_EXPANDED_BYTES:
                raise ProteomicsInputError("Excel 解压后的文件体积过大，无法安全分析。")
    except zipfile.BadZipFile as exc:
        raise ProteomicsInputError("XLSX 文件结构无效或已损坏。") from exc
    try:
        workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    except Exception as exc:
        raise ProteomicsInputError("XLSX 文件无法读取，请在 Excel 中另存后重试。") from exc
    try:
        if not workbook.worksheets:
            return ParsedTable([], [], "")
        sheet = workbook.worksheets[0]
        iterator = sheet.iter_rows(values_only=True)
        header_row = next(iterator, ())
        headers = _unique_headers(list(header_row))
        if len(headers) > settings.PROTEOMICS_MAX_COLUMNS:
            raise ProteomicsInputError(f"单次最多支持 {settings.PROTEOMICS_MAX_COLUMNS} 列。")
        return ParsedTable(headers, _rows_to_records(headers, (list(row) for row in iterator)), sheet.title)
    finally:
        workbook.close()


def _parse_xls(payload: bytes) -> ParsedTable:
    try:
        workbook = xlrd.open_workbook(file_contents=payload, on_demand=True)
        if workbook.nsheets < 1:
            return ParsedTable([], [], "")
        sheet = workbook.sheet_by_index(0)
        if sheet.nrows - 1 > settings.PROTEOMICS_MAX_ROWS:
            raise ProteomicsInputError(
                f"单次最多分析 {settings.PROTEOMICS_MAX_ROWS:,} 行，请先拆分文件。"
            )
        if max(sheet.ncols, 0) > settings.PROTEOMICS_MAX_COLUMNS:
            raise ProteomicsInputError(f"单次最多支持 {settings.PROTEOMICS_MAX_COLUMNS} 列。")
        if max(sheet.nrows - 1, 0) * max(sheet.ncols, 0) > settings.PROTEOMICS_MAX_CELLS:
            raise ProteomicsInputError(
                f"文件超过当前单次分析的 {settings.PROTEOMICS_MAX_CELLS:,} 个单元格上限，请拆分文件。"
            )
        headers = _unique_headers(sheet.row_values(0)) if sheet.nrows else []
        if len(headers) > settings.PROTEOMICS_MAX_COLUMNS:
            raise ProteomicsInputError(f"单次最多支持 {settings.PROTEOMICS_MAX_COLUMNS} 列。")
        rows = [sheet.row_values(index) for index in range(1, sheet.nrows)]
        return ParsedTable(headers, _rows_to_records(headers, rows), sheet.name)
    except ProteomicsInputError:
        raise
    except Exception as exc:
        raise ProteomicsInputError("XLS 文件无法读取，请在 Excel 中另存为 XLSX 后重试。") from exc
    finally:
        if "workbook" in locals():
            workbook.release_resources()


def parse_dataset_table(storage_key: str, filename: str) -> ParsedTable:
    extension = PurePosixPath(filename.lower()).suffix
    if extension not in {".csv", ".tsv", ".xlsx", ".xls"}:
        raise ProteomicsInputError("仅支持 CSV、TSV、XLS 和 XLSX 文件。")
    try:
        with default_storage.open(storage_key, "rb") as uploaded:
            payload = uploaded.read(settings.DATASET_UPLOAD_MAX_BYTES + 1)
    except OSError as exc:
        raise ProteomicsInputError("服务器原始文件暂不可用。") from exc
    if len(payload) > settings.DATASET_UPLOAD_MAX_BYTES:
        raise ProteomicsInputError("原始文件超过当前配置的分析大小限制。")
    if extension in {".csv", ".tsv"}:
        table = _parse_delimited(payload, extension)
    elif extension == ".xlsx":
        table = _parse_xlsx(payload)
    else:
        table = _parse_xls(payload)
    if not table.columns or not table.rows:
        raise ProteomicsInputError("上传文件没有可分析的数据行。")
    return table


def resolve_mapping(columns: list[str], requested: dict[str, str]) -> ColumnMapping:
    normalized: dict[str, str] = {}
    for column in columns:
        normalized.setdefault(_normalize_column(column), column)

    def find(field: str) -> str:
        candidate = str(requested.get(field, "") or "").strip()
        if candidate:
            resolved = normalized.get(_normalize_column(candidate))
            if not resolved:
                raise ProteomicsInputError(
                    f"找不到字段“{candidate}”，当前文件字段为：{'、'.join(columns)}"
                )
            return resolved
        for alias in ALIASES[field]:
            resolved = normalized.get(_normalize_column(alias))
            if resolved:
                return resolved
        return ""

    mapping = ColumnMapping(
        gene_column=find("gene_column"),
        protein_column=find("protein_column"),
        log2fc_column=find("log2fc_column"),
        p_value_column=find("p_value_column"),
        fdr_column=find("fdr_column"),
        direction_column=find("direction_column"),
    )
    if not mapping.gene_column and not mapping.protein_column:
        raise ProteomicsInputError(
            f"未识别到基因或蛋白字段，请填写列名。当前字段为：{'、'.join(columns)}"
        )
    return mapping


def _number(value: str) -> tuple[float | None, str | None]:
    text = value.strip().replace(",", "")
    if text.lower() in MISSING_VALUES:
        return None, None
    is_percent = text.endswith("%")
    try:
        parsed = float(text[:-1] if is_percent else text)
    except ValueError:
        return None, "invalid_numeric"
    if not math.isfinite(parsed):
        return None, "invalid_numeric"
    if is_percent:
        parsed /= 100
    return parsed, None


def _looks_like_gene_symbol(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{1,31}", value))


def _row_value(raw: dict[str, str], column: str) -> str:
    return str(raw.get(column, "") or "").strip() if column else ""


def _parse_rows(
    rows: list[dict[str, str]], mapping: ColumnMapping, thresholds: dict[str, float]
) -> tuple[list[AnalyzedRow], dict[str, Any]]:
    output: list[AnalyzedRow] = []
    duplicate_labels: Counter[str] = Counter()
    missing_identifier_count = 0
    invalid_numeric_row_count = 0
    reason_counts: Counter[str] = Counter()

    for row_index, raw in enumerate(rows):
        gene = _row_value(raw, mapping.gene_column)
        protein = _row_value(raw, mapping.protein_column)
        if len(gene) > 500 or len(protein) > 500:
            raise ProteomicsInputError("基因或蛋白标识单元格超过 500 个字符，请检查列映射。")
        label = gene or protein
        log2fc, log2fc_error = _number(_row_value(raw, mapping.log2fc_column)) if mapping.log2fc_column else (None, None)
        p_value, p_error = _number(_row_value(raw, mapping.p_value_column)) if mapping.p_value_column else (None, None)
        fdr, fdr_error = _number(_row_value(raw, mapping.fdr_column)) if mapping.fdr_column else (None, None)
        reasons: list[str] = []
        qc_warnings: list[str] = []
        if not label:
            missing_identifier_count += 1
            reasons.append("missing_identifier")
        invalid_numeric = any(error for error in (log2fc_error, p_error, fdr_error))
        if p_value is not None and not 0 <= p_value <= 1:
            p_error, p_value = "invalid_range", None
            invalid_numeric = True
        if fdr is not None and not 0 <= fdr <= 1:
            fdr_error, fdr = "invalid_range", None
            invalid_numeric = True
        if invalid_numeric:
            invalid_numeric_row_count += 1
        for field_name, field_error in (
            ("log2fc", log2fc_error),
            ("p_value", p_error),
            ("fdr", fdr_error),
        ):
            if field_error:
                qc_warnings.append(f"invalid_{field_name}")

        if label:
            duplicate_labels[_canonical_label(label)] += 1
        if label and mapping.log2fc_column:
            if log2fc is None:
                reasons.append("invalid_log2fc" if log2fc_error else "missing_log2fc")
            elif abs(log2fc) < thresholds["log2FcMin"]:
                reasons.append("log2fc_below_threshold")
        if label and (mapping.fdr_column or mapping.p_value_column):
            significance_value = fdr if fdr is not None else p_value
            significance_limit = thresholds["fdrMax"] if fdr is not None else thresholds["pValueMax"]
            if significance_value is None:
                reasons.append("invalid_significance" if fdr_error or p_error else "missing_significance")
            elif significance_value > significance_limit:
                reasons.append("fdr_above_threshold" if fdr is not None else "p_value_above_threshold")

        raw_direction = _row_value(raw, mapping.direction_column)
        inferred_direction = "" if log2fc is None else "上调" if log2fc >= 0 else "下调"
        direction = raw_direction or inferred_direction
        status = ProteomicsRowResult.MappingStatus.MISSING if not label else ProteomicsRowResult.MappingStatus.UNMAPPED
        output.append(
            AnalyzedRow(
                row_index=row_index,
                raw=raw,
                original_label=label,
                protein_name=protein,
                log2_fold_change=log2fc,
                p_value=p_value,
                fdr=fdr,
                direction=direction,
                mapping_status=status,
                normalized_symbol="",
                mapping_source="",
                matched_entity=None,
                selected=not reasons,
                exclusion_reasons=reasons,
                qc_warnings=qc_warnings,
            )
        )
        reason_counts.update(reasons)

    duplicate_count = sum(count - 1 for count in duplicate_labels.values() if count > 1)
    qc = {
        "inputRowCount": len(rows),
        "rowsWithIdentifier": len(rows) - missing_identifier_count,
        "missingIdentifierCount": missing_identifier_count,
        "duplicateIdentifierCount": duplicate_count,
        "invalidNumericValueRowCount": invalid_numeric_row_count,
        "excludedRowCount": sum(not row.selected for row in output),
        "excludedReasonCounts": dict(sorted(reason_counts.items())),
        "selectedRowCount": sum(row.selected for row in output),
    }
    return output, qc


def _entity_aliases(entity: KnowledgeEntity) -> set[str]:
    synonyms = entity.synonyms if isinstance(entity.synonyms, list) else []
    values: list[Any] = [entity.stable_id, entity.label, *synonyms]
    if isinstance(entity.metadata, dict):
        values.extend(
            entity.metadata.get(key)
            for key in ("symbol", "gene_symbol", "geneSymbol", "external_id", "accession", "uniprot_id")
        )
    return {_canonical_label(str(value)) for value in values if value}


def _entity_symbol(entity: KnowledgeEntity) -> str:
    metadata = entity.metadata if isinstance(entity.metadata, dict) else {}
    symbol = metadata.get("symbol") or metadata.get("gene_symbol") or metadata.get("geneSymbol")
    if symbol:
        return str(symbol).strip()
    if entity.entity_type == KnowledgeEntity.EntityType.GENE:
        return entity.stable_id.strip()
    return entity.label.strip()


def _build_result(
    rows: list[AnalyzedRow],
    reference_targets: list[str],
    columns: list[str],
    mapping: ColumnMapping,
    qc: dict[str, Any],
    task: AnalysisTask,
) -> tuple[dict[str, Any], list[ProteomicsRowResult], list[int]]:
    selected_rows = [row for row in rows if row.selected]
    entities = list(
        KnowledgeEntity.objects.filter(
            entity_type__in=[KnowledgeEntity.EntityType.GENE, KnowledgeEntity.EntityType.PROTEIN]
        ).select_related("source_release", "source_release__source").order_by("id")
    )
    aliases: dict[str, list[KnowledgeEntity]] = defaultdict(list)
    for entity in entities:
        for alias in _entity_aliases(entity):
            if entity not in aliases[alias]:
                aliases[alias].append(entity)

    for row in rows:
        if not row.original_label:
            continue
        matches = aliases.get(_canonical_label(row.original_label), [])
        if len(matches) == 1:
            entity = matches[0]
            row.matched_entity = entity
            row.mapping_status = ProteomicsRowResult.MappingStatus.DATABASE
            row.normalized_symbol = _entity_symbol(entity)
            metadata = entity.metadata if isinstance(entity.metadata, dict) else {}
            if entity.source_release_id:
                row.mapping_source = f"{entity.source_release.source.slug}:{entity.source_release.version}"
            else:
                row.mapping_source = str(metadata.get("source") or entity.entity_type)
        elif len(matches) > 1:
            row.mapping_status = ProteomicsRowResult.MappingStatus.AMBIGUOUS
            row.mapping_source = "multiple_local_entities"
        elif _looks_like_gene_symbol(row.original_label):
            # Mirrors the main-branch fallback, but marks it as a format-based
            # candidate instead of claiming a verified database mapping.
            row.mapping_status = ProteomicsRowResult.MappingStatus.UNVERIFIED
            row.normalized_symbol = row.original_label.upper()
            row.mapping_source = "symbol_format_only"

    selected_labels = list(dict.fromkeys(row.original_label for row in selected_rows if row.original_label))
    canonical_labels = {_canonical_label(label) for label in selected_labels}
    symbols_by_canonical: dict[str, str] = {}
    for row in selected_rows:
        if row.normalized_symbol:
            symbols_by_canonical.setdefault(_canonical_label(row.normalized_symbol), row.normalized_symbol)
    mapped_symbols = list(symbols_by_canonical.values())
    mapped_label_keys = {
        _canonical_label(row.original_label)
        for row in selected_rows
        if row.original_label and row.normalized_symbol
    }
    unmapped = [
        label
        for label in selected_labels
        if _canonical_label(label) not in mapped_label_keys
    ]
    reference_set = {_canonical_label(item) for item in reference_targets if item.strip()}
    normalized_by_canonical = {_canonical_label(item): item for item in mapped_symbols}
    overlap = [symbol for key, symbol in normalized_by_canonical.items() if key in reference_set]
    proteomics_only = [symbol for key, symbol in normalized_by_canonical.items() if key not in reference_set]
    reference_only = sorted(reference_set - set(normalized_by_canonical))

    selected_entity_ids = list(
        dict.fromkeys(row.matched_entity.pk for row in selected_rows if row.matched_entity)
    )
    relations = list(
        EvidenceRelation.objects.filter(
            subject_id__in=selected_entity_ids,
            object__entity_type=KnowledgeEntity.EntityType.PATHWAY,
        ).select_related("subject", "object", "source_release", "source_release__source")
    ) if selected_entity_ids else []
    relations = [
        relation
        for relation in relations
        if _normalize_column(relation.relation_type) in PATHWAY_RELATION_TYPES
    ]

    network_nodes: dict[str, dict[str, Any]] = {}
    for symbol in mapped_symbols:
        network_nodes[f"target:{symbol}"] = {"id": f"target:{symbol}", "label": symbol, "type": "target"}
    network_links: list[dict[str, Any]] = []
    release_ids: set[int] = {
        row.matched_entity.source_release_id
        for row in selected_rows
        if row.matched_entity and row.matched_entity.source_release_id
    }
    pathways: dict[str, dict[str, Any]] = {}
    symbols_by_entity_id: dict[int, set[str]] = defaultdict(set)
    for row in selected_rows:
        if row.matched_entity and row.normalized_symbol:
            symbols_by_entity_id[row.matched_entity.pk].add(row.normalized_symbol)
    for relation in relations:
        row_symbols = symbols_by_entity_id.get(relation.subject_id, set())
        pathway_id = relation.object.stable_id or str(relation.object_id)
        pathway_node_id = f"pathway:{pathway_id}"
        network_nodes[pathway_node_id] = {
            "id": pathway_node_id,
            "label": relation.object.label,
            "type": "pathway",
        }
        source = relation.source_release.source
        pathways[pathway_node_id] = {
            "name": relation.object.label,
            "stableId": pathway_id,
            "source": source.slug,
            "version": relation.source_release.version,
        }
        release_ids.add(relation.source_release_id)
        for symbol in row_symbols:
            network_links.append(
                {
                    "source": f"target:{symbol}",
                    "target": pathway_node_id,
                    "relation": relation.relation_type,
                    "evidenceType": relation.evidence_type,
                    "score": float(relation.score) if relation.score is not None else None,
                    "sourceSlug": source.slug,
                    "sourceVersion": relation.source_release.version,
                    "sourceRecordId": relation.source_record_id,
                }
            )

    degree: Counter[str] = Counter()
    for link in network_links:
        degree[link["source"]] += 1
        degree[link["target"]] += 1
    top_nodes = []
    for symbol in mapped_symbols:
        symbol_rows = [row for row in selected_rows if _canonical_label(row.normalized_symbol) == _canonical_label(symbol)]
        representative = max(
            symbol_rows,
            key=lambda row: abs(row.log2_fold_change or 0),
            default=None,
        )
        pathway_names = list(
            dict.fromkeys(
                pathways[link["target"]]["name"]
                for link in network_links
                if link["source"] == f"target:{symbol}"
            )
        )
        top_nodes.append(
            {
                "symbol": symbol,
                "degree": degree[f"target:{symbol}"],
                "log2FoldChange": representative.log2_fold_change if representative else None,
                "fdr": representative.fdr if representative else None,
                "direction": representative.direction or None if representative else None,
                "pathways": pathway_names,
                "mappingStatus": representative.mapping_status if representative else "unmapped",
            }
        )
    top_nodes.sort(
        key=lambda item: (item["degree"], abs(item["log2FoldChange"] or 0)), reverse=True
    )

    rows_for_storage = [
        ProteomicsRowResult(
            task=task,
            row_index=row.row_index,
            original_label=row.original_label[:500],
            protein_name=row.protein_name[:500],
            normalized_symbol=row.normalized_symbol[:160],
            mapping_status=row.mapping_status,
            mapping_source=row.mapping_source[:160],
            matched_entity=row.matched_entity,
            log2_fold_change=row.log2_fold_change,
            p_value=row.p_value,
            fdr=row.fdr,
            direction=row.direction[:80],
            selected=row.selected,
            exclusion_reasons=row.exclusion_reasons,
            qc_warnings=row.qc_warnings,
        )
        for row in rows
    ]
    preview = [
        {
            "index": row.row_index,
            "originalLabel": row.original_label,
            "proteinName": row.protein_name or None,
            "symbol": row.normalized_symbol or None,
            "mappingStatus": row.mapping_status,
            "mappingSource": row.mapping_source,
            "log2FoldChange": row.log2_fold_change,
            "pValue": row.p_value,
            "fdr": row.fdr,
            "direction": row.direction or None,
        }
        for row in selected_rows[:500]
    ]
    database_mapped = {
        row.normalized_symbol for row in selected_rows if row.mapping_status == ProteomicsRowResult.MappingStatus.DATABASE
    }
    heuristic_mapped = {
        row.normalized_symbol for row in selected_rows if row.mapping_status == ProteomicsRowResult.MappingStatus.UNVERIFIED
    }
    qc.update(
        {
            "selectedRowCount": len(selected_rows),
            "databaseMappedCount": len(database_mapped),
            "unverifiedSymbolCount": len(heuristic_mapped),
            "unmappedLabelCount": len(unmapped),
        }
    )
    warnings = []
    if not mapping.log2fc_column:
        warnings.append("未配置 log2FC 列，本次没有按倍数变化筛选。")
    if not (mapping.fdr_column or mapping.p_value_column):
        warnings.append("未配置 FDR/P 值列，本次没有按统计显著性筛选。")
    if qc["duplicateIdentifierCount"]:
        warnings.append("文件中存在重复标识；重复行已保留并分别计入结果。")
    if heuristic_mapped:
        warnings.append("部分标识仅符合基因符号格式，未在本地知识库核实，请人工确认。")
    if not entities:
        warnings.append("本地知识库尚无基因/蛋白实体；结果不会使用外部服务自动补全。")

    result = {
        "algorithmVersion": ALGORITHM_VERSION,
        "dataset": {
            "id": task.dataset_id,
            "sha256": task.dataset.content_sha256,
            "originalFilename": task.dataset.original_filename,
            "rowCount": len(rows),
            "sheetName": task.input_parameters.get("sheetName", ""),
        },
        "columns": columns,
        "mapping": mapping.as_dict(),
        "thresholds": {
            "log2FcMin": task.input_parameters["thresholds"]["log2FcMin"],
            "fdrMax": task.input_parameters["thresholds"]["fdrMax"],
            "pValueMax": task.input_parameters["thresholds"]["pValueMax"],
        },
        "qc": qc,
        "warnings": warnings,
        "summary": {
            "selectedRowCount": len(selected_rows),
            "uniqueLabelCount": len(canonical_labels),
            "normalizedCount": len(mapped_symbols),
            "databaseMappedCount": len(database_mapped),
            "unverifiedSymbolCount": len(heuristic_mapped),
            "unmappedCount": len(unmapped),
            "localAnnotatedCount": len(database_mapped),
            "referenceCount": len(reference_set),
            "candidateOverlapCount": len(overlap),
            "pathwayCount": len(pathways),
            "enrichmentMode": "LOCAL",
            "enrichmentNote": "仅使用本地基因/蛋白实体和来源证据；未向外部服务发送上传数据。",
        },
        "rows": preview,
        "previewTruncated": len(selected_rows) > len(preview),
        "unmapped": unmapped[:500],
        "unmappedTruncated": len(unmapped) > 500,
        "topNodes": top_nodes[:30],
        "pathways": list(pathways.values()),
        "validation": {
            "referenceTargets": sorted(reference_set),
            "overlap": overlap,
            "proteomicsOnly": proteomics_only,
            "referenceOnly": reference_only,
        },
        "network": {"nodes": list(network_nodes.values()), "links": network_links},
    }
    return result, rows_for_storage, sorted(release_ids)


def run_proteomics_analysis(task: AnalysisTask) -> tuple[dict[str, Any], list[ProteomicsRowResult], list[int]]:
    dataset = task.dataset
    if dataset is None or not dataset.storage_key:
        raise ProteomicsInputError("分析任务对应的原始数据集已不可用。")
    if not default_storage.exists(dataset.storage_key):
        raise ProteomicsInputError("服务器原始文件暂不可用。")
    table = parse_dataset_table(dataset.storage_key, dataset.original_filename)
    if not table.columns or not table.rows:
        raise ProteomicsInputError("上传文件没有可分析的数据行。")
    parameters = task.input_parameters
    mapping = resolve_mapping(table.columns, parameters.get("mapping", {}))
    thresholds = parameters.get(
        "thresholds", {"log2FcMin": 1.0, "fdrMax": 0.05, "pValueMax": 0.05}
    )
    rows, qc = _parse_rows(table.rows, mapping, thresholds)
    if not any(row.selected and row.original_label for row in rows):
        raise ProteomicsInputError("没有有效标识通过当前阈值，请检查列映射或放宽阈值。")
    if qc["inputRowCount"] > settings.PROTEOMICS_MAX_ROWS:
        raise ProteomicsInputError(
            f"单次最多分析 {settings.PROTEOMICS_MAX_ROWS:,} 行，请先拆分文件。"
        )
    parameters["sheetName"] = table.sheet_name
    task.input_parameters = parameters
    result, row_results, release_ids = _build_result(
        rows,
        parameters.get("referenceTargets", []),
        table.columns,
        mapping,
        qc,
        task,
    )
    return result, row_results, release_ids
