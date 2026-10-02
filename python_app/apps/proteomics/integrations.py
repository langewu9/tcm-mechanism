"""Provenance-aware opt-in integration for external human gene enrichment."""

from datetime import date

from django.utils import timezone

from apps.core.services.external_analysis import (
    ExternalAnalysisError,
    query_string_physical_network,
)
from apps.core.models import DataSource, SourceRelease

from .external_reactome import (
    ExternalEnrichmentError,
    analyze_reactome_human_pathways,
    resolve_human_identifiers,
)
from .models import ProteomicsRowResult


def _source_release(slug, name, url, version, metadata):
    source, _ = DataSource.objects.get_or_create(
        slug=slug,
        defaults={
            "name": name,
            "description": "蛋白组学任务选择启用时调用的外部基因注释/通路分析服务。",
            "access_mode": DataSource.AccessMode.API,
            "documentation_url": url,
            "license_note": "分析结果保留服务版本和查询映射；使用者需遵循数据服务的引用与使用条款。",
            "enabled": True,
        },
    )
    release, _ = SourceRelease.objects.get_or_create(
        source=source,
        version=version,
        defaults={"metadata": metadata},
    )
    return release


def _canonical(value):
    return str(value or "").strip().strip('"').upper()


def _refresh_preview_and_counts(result, rows):
    preview_by_index = {item["index"]: item for item in result.get("rows", [])}
    for row in rows:
        preview = preview_by_index.get(row.row_index)
        if preview:
            preview["symbol"] = row.normalized_symbol or None
            preview["mappingStatus"] = row.mapping_status
            preview["mappingSource"] = row.mapping_source

    selected_rows = [row for row in rows if row.selected]
    database_symbols = {
        row.normalized_symbol for row in selected_rows
        if row.mapping_status == ProteomicsRowResult.MappingStatus.DATABASE and row.normalized_symbol
    }
    external_symbols = {
        row.normalized_symbol for row in selected_rows
        if row.mapping_status == ProteomicsRowResult.MappingStatus.EXTERNAL and row.normalized_symbol
    }
    unverified_symbols = {
        row.normalized_symbol for row in selected_rows
        if row.mapping_status == ProteomicsRowResult.MappingStatus.UNVERIFIED and row.normalized_symbol
    }
    normalized = {}
    for row in selected_rows:
        if row.normalized_symbol:
            normalized.setdefault(_canonical(row.normalized_symbol), row.normalized_symbol)
    unmapped = list(
        dict.fromkeys(row.original_label for row in selected_rows if row.original_label and not row.normalized_symbol)
    )
    result["unmapped"] = unmapped[:500]
    result["unmappedTruncated"] = len(unmapped) > 500
    summary = result.setdefault("summary", {})
    summary["databaseMappedCount"] = len(database_symbols)
    summary["externalMappedCount"] = len(external_symbols)
    summary["unverifiedSymbolCount"] = len(unverified_symbols)
    summary["normalizedCount"] = len(normalized)
    summary["unmappedCount"] = len(unmapped)

    validation = result.setdefault("validation", {})
    reference_targets = validation.get("referenceTargets", [])
    reference_by_canonical = {_canonical(item): item for item in reference_targets}
    validation["overlap"] = [
        symbol for key, symbol in normalized.items() if key in reference_by_canonical
    ]
    validation["proteomicsOnly"] = [
        symbol for key, symbol in normalized.items() if key not in reference_by_canonical
    ]
    validation["referenceOnly"] = sorted(set(reference_by_canonical) - set(normalized))
    summary["candidateOverlapCount"] = len(validation["overlap"])


def run_opt_in_reactome(task, result, row_results):
    """Append external mappings/enrichment while retaining local output on failure."""
    labels = list(
        dict.fromkeys(
            row.original_label
            for row in row_results
            if row.selected
            and row.original_label
            and row.mapping_status != ProteomicsRowResult.MappingStatus.DATABASE
        )
    )
    output = {
        "status": "unavailable",
        "organism": "Homo sapiens",
        "mappings": [],
        "ambiguousIdentifiers": [],
        "unmappedIdentifiers": [],
        "rejectedIdentifiers": [],
        "pathways": [],
        "source": "Reactome Analysis Service",
        "sourceVersion": None,
        "reactomeToken": None,
    }
    releases = []
    warnings = []

    for slug in ("mygene-info", "reactome"):
        source = DataSource.objects.filter(slug=slug).only("enabled").first()
        if source and not source.enabled:
            output["status"] = "disabled"
            output["failureStage"] = slug
            result["externalReactome"] = output
            warnings.append("管理员已停用外部基因映射或通路服务；本地分析结果仍可查看。")
            _refresh_preview_and_counts(result, row_results)
            return [], warnings

    mapping_version = f"captured-{date.today().isoformat()}"
    eligible_labels = [label for label in labels if len(label) <= 120][:500]
    if eligible_labels:
        try:
            mapping_result = resolve_human_identifiers(labels)
        except ExternalEnrichmentError:
            warnings.append("MyGene.info 标识映射暂不可用，保留本地分析结果。")
            result["externalReactome"] = {**output, "failureStage": "identifier_mapping"}
            _refresh_preview_and_counts(result, row_results)
            return [], warnings
        mapping_release = _source_release(
            "mygene-info",
            "MyGene.info",
            "https://docs.mygene.info/en/latest/doc/query_service.html",
            mapping_version,
            {
                "versionStrategy": "query-results-captured-on-date",
                "retrievedAt": timezone.now().isoformat(),
                "endpoint": "https://mygene.info/v3/query",
            },
        )
        releases.append(mapping_release.pk)
    else:
        mapping_result = {
            "mappings": [],
            "ambiguous": [],
            "unmapped": [],
            "rejected": labels,
            "truncatedCount": 0,
            "rejectedCount": len(labels),
        }
    mapping_by_label = {_canonical(item["query"]): item for item in mapping_result["mappings"]}
    ambiguous_labels = {_canonical(label) for label in mapping_result["ambiguous"]}
    for row in row_results:
        if not row.selected or not row.original_label:
            continue
        key = _canonical(row.original_label)
        match = mapping_by_label.get(key)
        if row.mapping_status == ProteomicsRowResult.MappingStatus.DATABASE:
            continue
        if match:
            row.mapping_status = ProteomicsRowResult.MappingStatus.EXTERNAL
            row.normalized_symbol = match["symbol"]
            row.mapping_source = f"mygene.info:{mapping_version}"
        elif key in ambiguous_labels:
            row.mapping_status = ProteomicsRowResult.MappingStatus.AMBIGUOUS
            row.normalized_symbol = ""
            row.mapping_source = f"mygene.info:{mapping_version}:ambiguous"

    mapping_warnings = []
    if mapping_result["truncatedCount"]:
        mapping_warnings.append(
            f"外部标识映射最多提交 500 个不同标识，另有 {mapping_result['truncatedCount']} 个未发送。"
        )
    if mapping_result["rejectedCount"]:
        mapping_warnings.append(
            f"有 {mapping_result['rejectedCount']} 个标识长度超过 120 个字符，没有发送到外部服务。"
        )
    if mapping_result["ambiguous"]:
        mapping_warnings.append("MyGene.info 对部分标识返回多个候选，系统保留为歧义项，不自动选定。")

    symbols = list(
        dict.fromkeys(
            row.normalized_symbol
            for row in row_results
            if row.selected and row.normalized_symbol
        )
    )[:500]
    _refresh_preview_and_counts(result, row_results)
    output["mappings"] = mapping_result["mappings"]
    output["ambiguousIdentifiers"] = mapping_result["ambiguous"]
    output["unmappedIdentifiers"] = mapping_result["unmapped"]
    output["rejectedIdentifiers"] = mapping_result["rejected"]
    output["submittedLabelCount"] = min(len(labels), 500)
    output["truncatedLabelCount"] = mapping_result["truncatedCount"]

    if not symbols:
        warnings.extend(mapping_warnings)
        warnings.append("没有可提交 Reactome 的已识别人类基因符号；本地结果仍可查看。")
        output["status"] = "no_mapped_identifiers"
        result["externalReactome"] = output
        return releases, warnings

    try:
        enrichment = analyze_reactome_human_pathways(symbols)
    except ExternalEnrichmentError:
        warnings.extend(mapping_warnings)
        warnings.append("Reactome 通路分析暂不可用；已保留本地分析及 MyGene.info 映射结果。")
        output["status"] = "unavailable"
        output["failureStage"] = "reactome_enrichment"
        result["externalReactome"] = output
        return releases, warnings

    reactome_release = None
    if enrichment["sourceVersion"]:
        reactome_release = _source_release(
            "reactome",
            "Reactome",
            "https://reactome.org/dev/analysis/",
            str(enrichment["sourceVersion"]),
            {
                "endpoint": "https://reactome.org/AnalysisService/identifiers/projection/",
                "retrievedAt": timezone.now().isoformat(),
            },
        )
        releases.append(reactome_release.pk)

    output.update(
        {
            "status": "succeeded" if enrichment["pathways"] else "no_significant_pathways",
            "pathways": enrichment["pathways"],
            "sourceVersion": enrichment["sourceVersion"],
            "reactomeToken": enrichment["token"],
            "identifiersNotFound": enrichment["identifiersNotFound"],
            "pathwaysFound": enrichment["pathwaysFound"],
            "submittedIdentifierCount": enrichment["submittedIdentifierCount"],
            "truncatedIdentifierCount": enrichment["truncatedIdentifierCount"],
            "rejectedIdentifierCount": enrichment["rejectedIdentifierCount"],
            "sourceRelease": reactome_release.pk if reactome_release else None,
        }
    )
    warnings.extend(mapping_warnings)
    if not enrichment["pathways"]:
        warnings.append("Reactome 未返回同时满足 FDR ≤ 0.05 且至少命中 2 个实体的通路。")
    result.setdefault("summary", {})["enrichmentMode"] = "LOCAL+REACTOME"
    result.setdefault("summary", {})["reactomePathwayCount"] = len(enrichment["pathways"])

    result["externalReactome"] = output
    return releases, warnings


def run_opt_in_string(task, result, row_results, required_score=700):
    """Append STRING physical interactions only after separate user consent."""
    output = {
        "status": "unavailable",
        "organism": "Homo sapiens",
        "source": "STRING",
        "sourceVersion": None,
        "sourceVersionKnown": False,
        "networkType": "physical",
        "requiredScore": required_score,
        "inputCount": 0,
        "submittedIdentifierCount": 0,
        "truncatedIdentifierCount": 0,
        "interactionCount": 0,
        "nodes": [],
        "edges": [],
        "consentRecorded": True,
    }
    warnings = []
    releases = []

    source = DataSource.objects.filter(slug="string").only("enabled").first()
    if source and not source.enabled:
        output["status"] = "disabled"
        result["externalString"] = output
        warnings.append("管理员已停用 STRING 外部物理互作查询；本地分析结果仍可查看。")
        return releases, warnings

    unique = {}
    rejected_count = 0
    for row in row_results:
        if not row.selected or not row.normalized_symbol:
            continue
        symbol = row.normalized_symbol.strip()
        if len(symbol) > 120 or any(ord(char) < 32 for char in symbol):
            rejected_count += 1
            continue
        unique.setdefault(_canonical(symbol), symbol)
    labels = list(unique.values())
    submitted = labels[:200]
    output["inputCount"] = len(labels)
    output["submittedIdentifierCount"] = len(submitted)
    output["truncatedIdentifierCount"] = max(0, len(labels) - len(submitted))
    output["rejectedIdentifierCount"] = rejected_count

    if len(submitted) < 2:
        output["status"] = "insufficient_identifiers"
        result["externalString"] = output
        warnings.append("筛选并映射后的标识少于 2 个，未向 STRING 发送数据。")
        return releases, warnings

    try:
        network, version = query_string_physical_network(submitted, int(required_score))
    except ExternalAnalysisError:
        output["status"] = "unavailable"
        output["failureStage"] = "string_query"
        result["externalString"] = output
        warnings.append("STRING 物理互作服务暂不可用；本地分析结果仍可查看。")
        return releases, warnings
    except ValueError:
        output["status"] = "unavailable"
        output["failureStage"] = "string_query"
        result["externalString"] = output
        warnings.append("STRING 查询参数无效，未能完成外部分析。")
        return releases, warnings

    output.update(network)
    output["status"] = "succeeded" if network.get("interactionCount", 0) else "no_interactions"
    output["inputCount"] = len(labels)
    output["submittedIdentifierCount"] = len(submitted)
    output["truncatedIdentifierCount"] = max(0, len(labels) - len(submitted))
    output["rejectedIdentifierCount"] = rejected_count
    output["consentRecorded"] = True
    if version:
        release = _source_release(
            "string",
            "STRING",
            "https://string-db.org/help/api/",
            version,
            {
                "versionStrategy": "automatic-discovery-or-configured-pin",
                "apiEndpoint": network.get("sourceEndpoint"),
                "retrievedAt": timezone.now().isoformat(),
                "networkType": "physical",
                "requiredScore": required_score,
                "identifierCount": len(submitted),
            },
        )
        releases.append(release.pk)
    if output["truncatedIdentifierCount"]:
        warnings.append(f"STRING 单次最多发送 200 个标识，另有 {output['truncatedIdentifierCount']} 个未发送。")
    if rejected_count:
        warnings.append(f"有 {rejected_count} 个过长或无效标识没有发送到 STRING。")
    result["externalString"] = output
    return releases, warnings
