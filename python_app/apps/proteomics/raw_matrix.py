"""Explicitly designed, unpaired differential analysis for raw protein matrices."""

from __future__ import annotations

import math
from statistics import mean, median, variance

from scipy.stats import ttest_ind, ttest_rel

from .exceptions import ProteomicsInputError


MISSING_VALUES = {"", "na", "nan", "null", "none", "-"}
MAX_SAMPLE_COLUMNS = 100


def _matrix_value(value: str, *, values_are_log2: bool) -> tuple[float | None, str | None]:
    text = str("" if value is None else value).strip().replace(",", "")
    if text.casefold() in MISSING_VALUES:
        return None, None
    try:
        parsed = float(text)
    except ValueError:
        return None, "invalid_sample_value"
    if not math.isfinite(parsed):
        return None, "invalid_sample_value"
    if values_are_log2:
        return parsed, None
    if parsed <= 0:
        return None, "non_positive_intensity"
    return math.log2(parsed), None


def _bh_adjust(p_values: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values in the original input order."""
    ordered = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [1.0] * len(p_values)
    running_minimum = 1.0
    total = len(p_values)
    for index in range(total - 1, -1, -1):
        original_index, p_value = ordered[index]
        rank = index + 1
        running_minimum = min(running_minimum, p_value * total / rank, 1.0)
        adjusted[original_index] = running_minimum
    return adjusted


def analyze_raw_matrix(rows: list[dict[str, str]], design: dict) -> tuple[list[dict[str, str]], dict, dict, list[str]]:
    """Return derived differential rows, matrix QC, method metadata and warnings."""
    identifier_column = design["identifierColumn"]
    sample_columns = design["sampleColumns"]
    control_columns = design["controlSamples"]
    treatment_columns = design["treatmentSamples"]
    missing_policy = design["missingPolicy"]
    normalization = design["normalization"]
    values_are_log2 = design["valuesAreLog2"]
    design_type = design.get("designType", "unpaired")
    sample_pairs = design.get("samplePairs", [])

    if design_type not in {"unpaired", "paired"}:
        raise ProteomicsInputError("原始矩阵实验设计类型无效。")
    if normalization not in {"none", "median_center"}:
        raise ProteomicsInputError("原始矩阵归一化方法无效。")
    if missing_policy not in {"complete_rows", "available_replicates"}:
        raise ProteomicsInputError("原始矩阵缺失值策略无效。")
    if len(sample_columns) > MAX_SAMPLE_COLUMNS:
        raise ProteomicsInputError(f"原始矩阵最多可选择 {MAX_SAMPLE_COLUMNS} 个样本列。")
    if len(set(sample_columns)) != len(sample_columns) or identifier_column in sample_columns:
        raise ProteomicsInputError("标识列不能作为样本列，样本列也不能重复。")
    if design_type == "paired":
        pair_ids = [pair.get("pairId", "") for pair in sample_pairs]
        pair_columns = [
            column for pair in sample_pairs for column in (pair.get("controlSample", ""), pair.get("treatmentSample", ""))
        ]
        if len(sample_pairs) < 2:
            raise ProteomicsInputError("配对设计至少需要 2 对样本。")
        if any(not value for value in [*pair_ids, *pair_columns]):
            raise ProteomicsInputError("配对编号和两组样本列名称不能为空。")
        if len(set(pair_ids)) != len(pair_ids) or len(set(pair_columns)) != len(pair_columns):
            raise ProteomicsInputError("配对编号不能重复，样本列也只能出现在一个配对中。")
        if set(pair_columns) != set(sample_columns):
            raise ProteomicsInputError("配对关系中的样本列必须全部且仅包含在所选样本列中。")
        if control_columns != [pair["controlSample"] for pair in sample_pairs] or treatment_columns != [pair["treatmentSample"] for pair in sample_pairs]:
            raise ProteomicsInputError("分组样本列必须与配对关系一致。")
    elif sample_pairs:
        raise ProteomicsInputError("非配对设计不能包含配对关系。")
    elif (
        len(control_columns) < 2
        or len(treatment_columns) < 2
        or set(control_columns) & set(treatment_columns)
        or set(control_columns) | set(treatment_columns) != set(sample_columns)
    ):
        raise ProteomicsInputError("非配对设计需要至少 2 个样本/组，且全部样本列需唯一归属一个组。")
    available_columns = set(rows[0]) if rows else set()
    missing_columns = [column for column in [identifier_column, *sample_columns] if column not in available_columns]
    if missing_columns:
        raise ProteomicsInputError(f"原始矩阵找不到这些列：{'、'.join(missing_columns)}")

    parsed_matrix: list[list[float | None]] = []
    error_matrix: list[list[str | None]] = []
    for row in rows:
        parsed_row = []
        error_row = []
        for column in sample_columns:
            value, error = _matrix_value(row.get(column, ""), values_are_log2=values_are_log2)
            parsed_row.append(value)
            error_row.append(error)
        parsed_matrix.append(parsed_row)
        error_matrix.append(error_row)

    sample_offsets = [0.0] * len(sample_columns)
    if normalization == "median_center":
        for column_index, column in enumerate(sample_columns):
            available = [row[column_index] for row in parsed_matrix if row[column_index] is not None]
            if not available:
                raise ProteomicsInputError(f"样本列「{column}」没有有效数值，无法执行样本中位数中心化。")
            sample_offsets[column_index] = median(available)
        parsed_matrix = [
            [value - sample_offsets[index] if value is not None else None for index, value in enumerate(row)]
            for row in parsed_matrix
        ]

    column_index = {column: index for index, column in enumerate(sample_columns)}
    control_indices = [column_index[column] for column in control_columns]
    treatment_indices = [column_index[column] for column in treatment_columns]
    pair_indices = [
        (pair["pairId"], column_index[pair["controlSample"]], column_index[pair["treatmentSample"]])
        for pair in sample_pairs
    ]
    row_reasons: dict[int, list[str]] = {}
    row_warnings: dict[int, list[str]] = {}
    missing_cell_count = 0
    invalid_cell_count = 0
    invalid_row_count = 0
    tested_indices: list[int] = []
    raw_p_values: list[float] = []
    raw_p_by_row: dict[int, float] = {}
    log2_fold_changes: dict[int, float] = {}

    for row_index, row in enumerate(rows):
        values = parsed_matrix[row_index]
        errors = [error for error in error_matrix[row_index] if error]
        invalid_cell_count += len(errors)
        missing_cell_count += sum(
            value is None and error is None
            for value, error in zip(values, error_matrix[row_index])
        )
        if errors:
            invalid_row_count += 1
            row_warnings[row_index] = ["invalid_sample_values"]
        elif any(value is None for value in values):
            row_warnings[row_index] = ["missing_sample_values"]

        if not str(row.get(identifier_column, "") or "").strip():
            row_reasons[row_index] = ["missing_identifier"]
            continue
        incomplete = any(value is None for value in values)
        if incomplete and missing_policy == "complete_rows":
            row_reasons[row_index] = ["invalid_sample_values" if errors else "incomplete_samples"]
            continue

        if design_type == "paired":
            valid_pairs = [
                (values[control_index], values[treatment_index])
                for _pair_id, control_index, treatment_index in pair_indices
                if values[control_index] is not None and values[treatment_index] is not None
            ]
            if len(valid_pairs) < 2:
                row_reasons[row_index] = ["insufficient_valid_pairs"]
                continue
            control = [pair[0] for pair in valid_pairs]
            treatment = [pair[1] for pair in valid_pairs]
            differences = [treated - control_value for control_value, treated in valid_pairs]
            effect = mean(differences)
            standard_error_squared = variance(differences) / len(differences)
        else:
            control = [values[index] for index in control_indices if values[index] is not None]
            treatment = [values[index] for index in treatment_indices if values[index] is not None]
            if len(control) < 2 or len(treatment) < 2:
                row_reasons[row_index] = ["insufficient_valid_replicates"]
                continue
            effect = mean(treatment) - mean(control)
            standard_error_squared = variance(control) / len(control) + variance(treatment) / len(treatment)
        if standard_error_squared == 0:
            if effect != 0:
                row_reasons[row_index] = ["test_not_estimable"]
                continue
            p_value = 1.0
        else:
            test_result = (
                ttest_rel(treatment, control)
                if design_type == "paired"
                else ttest_ind(treatment, control, equal_var=False)
            )
            p_value = float(test_result.pvalue)
        if not math.isfinite(p_value):
            row_reasons[row_index] = ["test_not_estimable"]
            continue
        p_value = min(max(p_value, 0.0), 1.0)
        tested_indices.append(row_index)
        raw_p_values.append(p_value)
        raw_p_by_row[row_index] = p_value
        log2_fold_changes[row_index] = effect

    adjusted_p_values = _bh_adjust(raw_p_values)
    adjusted_by_row = dict(zip(tested_indices, adjusted_p_values))
    synthetic_rows = []
    for row_index, row in enumerate(rows):
        effect = log2_fold_changes.get(row_index)
        p_value = raw_p_by_row.get(row_index)
        fdr = adjusted_by_row.get(row_index)
        synthetic_rows.append({
            "__identifier": str(row.get(identifier_column, "") or "").strip(),
            "__log2fc": "" if effect is None else repr(effect),
            "__pvalue": "" if p_value is None else repr(p_value),
            "__fdr": "" if fdr is None else repr(fdr),
        })

    warnings = [
        (
            "原始矩阵使用配对双样本 t 检验；效应量为每对样本实验组减对照组的 log2 差值均值。"
            if design_type == "paired"
            else "原始矩阵使用非配对 Welch 双样本 t 检验；效应量为实验组减对照组的平均 log2 强度。"
        ),
        "P 值使用 Benjamini–Hochberg 方法校正为 FDR；没有对缺失值进行插补。",
    ]
    if not values_are_log2:
        warnings.append("已对正值强度执行 log2 转换。")
    if normalization == "median_center":
        warnings.append("已在选定样本中进行样本中位数中心化；归一化方法由研究者显式选择。")
    else:
        warnings.append("未执行样本归一化；请确认输入强度已适当归一化。")
    if missing_policy == "available_replicates":
        warnings.append(
            "按可用的完整配对样本计算，每个蛋白至少需要 2 对有效样本；未执行数值填补。"
            if design_type == "paired"
            else "按每个蛋白可用重复值计算，但每组至少需要 2 个有效重复；未执行数值填补。"
        )
    else:
        warnings.append("仅完整样本行参与检验，含缺失或非法样本值的整行已排除。")

    matrix_qc = {
        "sampleCount": len(sample_columns),
        "controlReplicateCount": len(control_columns),
        "treatmentReplicateCount": len(treatment_columns),
        "pairCount": len(pair_indices),
        "rowsTested": len(tested_indices),
        "rowsWithInvalidSampleValues": invalid_row_count,
        "invalidSampleValueCount": invalid_cell_count,
        "missingSampleValueCount": missing_cell_count,
        "rowsExcludedByMatrixDesign": len(row_reasons),
    }
    method = {
        "designType": design_type,
        "test": "paired two-sample t-test" if design_type == "paired" else "Welch two-sample t-test (unpaired)",
        "effect": (
            "mean(paired treatment log2 intensity - paired control log2 intensity)"
            if design_type == "paired"
            else "mean(treatment log2 intensity) - mean(control log2 intensity)"
        ),
        "pValueAdjustment": "Benjamini-Hochberg FDR",
        "normalization": normalization,
        "missingPolicy": missing_policy,
        "valuesWereLog2": values_are_log2,
        "inputScaleTransform": "none" if values_are_log2 else "log2",
        "controlSamples": control_columns,
        "treatmentSamples": treatment_columns,
        "sampleColumns": sample_columns,
        "samplePairs": sample_pairs,
    }
    return synthetic_rows, row_reasons, {"qc": matrix_qc, "method": method, "rowWarnings": row_warnings}, warnings
