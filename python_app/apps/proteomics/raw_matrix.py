"""Explicitly designed differential analysis for raw protein matrices."""

from __future__ import annotations

import math
from statistics import mean, median, variance

import numpy as np
from scipy.stats import t as student_t
from scipy.stats import ttest_ind, ttest_rel

from .exceptions import ProteomicsInputError


MISSING_VALUES = {"", "na", "nan", "null", "none", "-"}
MAX_SAMPLE_COLUMNS = 100
MAX_FACTORS = 10


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


def build_multifactor_design(sample_columns: list[str], design: dict) -> tuple[np.ndarray, np.ndarray, dict]:
    """Build an additive categorical model with an explicitly requested contrast."""
    assignments = design.get("sampleFactors", [])
    contrast_factor = str(design.get("contrastFactor", "")).strip()
    reference_level = str(design.get("referenceLevel", "")).strip()
    treatment_level = str(design.get("treatmentLevel", "")).strip()
    if len(sample_columns) < 4 or len(assignments) != len(sample_columns):
        raise ProteomicsInputError("多因素设计必须为每个样本列指定分组，并至少包含 4 个样本。")

    assignment_by_sample = {}
    for assignment in assignments:
        sample = str(assignment.get("sampleColumn", "")).strip()
        factors = assignment.get("factors", {})
        if not sample or sample in assignment_by_sample or not isinstance(factors, dict):
            raise ProteomicsInputError("多因素设计的样本信息格式无效或样本列重复。")
        normalized_factors = {}
        for raw_name, raw_level in factors.items():
            name = str(raw_name).strip()
            if not name or name in normalized_factors:
                raise ProteomicsInputError("多因素名称不能为空，去除首尾空格后也不能重复。")
            normalized_factors[name] = str(raw_level).strip()
        assignment_by_sample[sample] = normalized_factors
    if set(assignment_by_sample) != set(sample_columns):
        raise ProteomicsInputError("多因素设计中的样本列必须全部且仅包含在所选样本列中。")

    factor_names = sorted(assignment_by_sample[sample_columns[0]])
    if len(factor_names) < 2 or len(factor_names) > MAX_FACTORS:
        raise ProteomicsInputError(f"多因素设计须指定 2 至 {MAX_FACTORS} 个分类因素。")
    if any(not name for name in factor_names):
        raise ProteomicsInputError("多因素名称不能为空。")
    if any(set(assignment_by_sample[column]) != set(factor_names) for column in sample_columns):
        raise ProteomicsInputError("每个样本必须为相同的所有因素指定一个水平。")
    if any(not value for column in sample_columns for value in assignment_by_sample[column].values()):
        raise ProteomicsInputError("每个样本的因素水平都不能为空。")

    factor_levels = {
        name: sorted({assignment_by_sample[column][name] for column in sample_columns})
        for name in factor_names
    }
    if any(len(levels) < 2 for levels in factor_levels.values()):
        raise ProteomicsInputError("多因素设计中的每个因素都必须至少有两个水平。")
    if contrast_factor not in factor_levels:
        raise ProteomicsInputError("请指定一个有效的主要对比因素。")
    if reference_level == treatment_level or reference_level not in factor_levels[contrast_factor] or treatment_level not in factor_levels[contrast_factor]:
        raise ProteomicsInputError("主要对比的参考水平和实验水平必须是不同的已有水平。")

    reference_samples = [
        column for column in sample_columns
        if assignment_by_sample[column][contrast_factor] == reference_level
    ]
    treatment_samples = [
        column for column in sample_columns
        if assignment_by_sample[column][contrast_factor] == treatment_level
    ]
    if len(reference_samples) < 2 or len(treatment_samples) < 2:
        raise ProteomicsInputError("主要对比的每个水平至少需要 2 个样本。")

    reference_levels = {
        name: (reference_level if name == contrast_factor else factor_levels[name][0])
        for name in factor_names
    }
    matrix_columns = ["Intercept"]
    matrix_values = [[1.0] for _ in sample_columns]
    contrast = [0.0]
    for factor in factor_names:
        baseline = reference_levels[factor]
        for level in factor_levels[factor]:
            if level == baseline:
                continue
            matrix_columns.append(f"{factor}={level}")
            contrast.append(1.0 if factor == contrast_factor and level == treatment_level else 0.0)
            for row_index, sample in enumerate(sample_columns):
                matrix_values[row_index].append(
                    1.0 if assignment_by_sample[sample][factor] == level else 0.0
                )

    model_matrix = np.asarray(matrix_values, dtype=float)
    contrast_vector = np.asarray(contrast, dtype=float)
    rank = int(np.linalg.matrix_rank(model_matrix))
    parameter_count = int(model_matrix.shape[1])
    if rank < parameter_count:
        raise ProteomicsInputError("多因素设计存在完全共线或缺少交叉样本，无法估计所选因素效应。")
    residual_df = int(model_matrix.shape[0] - rank)
    if residual_df < 1:
        raise ProteomicsInputError("多因素设计没有残差自由度；请增加样本或减少因素水平。")

    metadata = {
        "model": "additive categorical linear model (main effects only; no interactions)",
        "factorNames": factor_names,
        "factorLevels": factor_levels,
        "referenceLevels": reference_levels,
        "contrast": {
            "factor": contrast_factor,
            "referenceLevel": reference_level,
            "treatmentLevel": treatment_level,
        },
        "modelColumns": matrix_columns,
        "parameterCount": parameter_count,
        "residualDegreesOfFreedom": residual_df,
        "referenceSamples": reference_samples,
        "treatmentSamples": treatment_samples,
    }
    return model_matrix, contrast_vector, metadata


def _fit_multifactor_contrast(
    model_matrix: np.ndarray,
    contrast_vector: np.ndarray,
    values: list[float | None],
) -> tuple[float | None, float | None, str | None]:
    valid_indices = [index for index, value in enumerate(values) if value is not None]
    if len(valid_indices) <= model_matrix.shape[1]:
        return None, None, "insufficient_model_degrees_of_freedom"
    observed_matrix = model_matrix[valid_indices]
    observed_values = np.asarray([values[index] for index in valid_indices], dtype=float)
    parameter_count = model_matrix.shape[1]
    rank = int(np.linalg.matrix_rank(observed_matrix))
    if rank < parameter_count:
        return None, None, "rank_deficient_sample_design"
    residual_df = len(valid_indices) - rank
    if residual_df < 1:
        return None, None, "insufficient_model_degrees_of_freedom"
    try:
        design_pseudoinverse = np.linalg.pinv(observed_matrix)
    except np.linalg.LinAlgError:
        return None, None, "rank_deficient_sample_design"
    coefficients = design_pseudoinverse @ observed_values
    effect = float(contrast_vector @ coefficients)
    residuals = observed_values - observed_matrix @ coefficients
    residual_variance = float(residuals @ residuals) / residual_df
    covariance_shape = design_pseudoinverse @ design_pseudoinverse.T
    contrast_variance = residual_variance * float(contrast_vector @ covariance_shape @ contrast_vector)
    if not math.isfinite(effect) or not math.isfinite(contrast_variance) or contrast_variance < 0:
        return None, None, "test_not_estimable"
    if contrast_variance == 0:
        return (effect, 1.0, None) if effect == 0 else (None, None, "test_not_estimable")
    statistic = effect / math.sqrt(contrast_variance)
    p_value = float(2 * student_t.sf(abs(statistic), df=residual_df))
    if not math.isfinite(p_value):
        return None, None, "test_not_estimable"
    return effect, min(max(p_value, 0.0), 1.0), None


def analyze_raw_matrix(rows: list[dict[str, str]], design: dict) -> tuple[list[dict[str, str]], dict, dict, list[str]]:
    """Return derived differential rows, matrix QC, method metadata and warnings."""
    identifier_column = design["identifierColumn"]
    sample_columns = design["sampleColumns"]
    control_columns = design.get("controlSamples", [])
    treatment_columns = design.get("treatmentSamples", [])
    missing_policy = design["missingPolicy"]
    normalization = design["normalization"]
    values_are_log2 = design["valuesAreLog2"]
    design_type = design.get("designType", "unpaired")
    sample_pairs = design.get("samplePairs", [])
    multifactor_matrix = None
    multifactor_contrast = None
    multifactor_metadata = None

    if design_type not in {"unpaired", "paired", "multifactor"}:
        raise ProteomicsInputError("原始矩阵实验设计类型无效。")
    if normalization not in {"none", "median_center"}:
        raise ProteomicsInputError("原始矩阵归一化方法无效。")
    if missing_policy not in {"complete_rows", "available_replicates"}:
        raise ProteomicsInputError("原始矩阵缺失值策略无效。")
    if len(sample_columns) > MAX_SAMPLE_COLUMNS:
        raise ProteomicsInputError(f"原始矩阵最多可选择 {MAX_SAMPLE_COLUMNS} 个样本列。")
    if len(set(sample_columns)) != len(sample_columns) or identifier_column in sample_columns:
        raise ProteomicsInputError("标识列不能作为样本列，样本列也不能重复。")
    if design_type == "multifactor":
        if control_columns or treatment_columns or sample_pairs:
            raise ProteomicsInputError("多因素设计不能同时提交配对关系或传统对照/实验分组。")
        multifactor_matrix, multifactor_contrast, multifactor_metadata = build_multifactor_design(
            sample_columns, design,
        )
        control_columns = multifactor_metadata["referenceSamples"]
        treatment_columns = multifactor_metadata["treatmentSamples"]
    elif design_type == "paired":
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

        if design_type == "multifactor":
            effect, p_value, reason = _fit_multifactor_contrast(
                multifactor_matrix, multifactor_contrast, values,
            )
            if reason:
                row_reasons[row_index] = [reason]
                continue
        elif design_type == "paired":
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
        if design_type != "multifactor":
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
        if effect is None or p_value is None:
            row_reasons[row_index] = ["test_not_estimable"]
            continue
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

    if design_type == "multifactor":
        contrast = multifactor_metadata["contrast"]
        warnings = [
            (
                "原始矩阵使用仅含主效应的加性分类线性模型；主要效应为"
                f"因素「{contrast['factor']}」的「{contrast['treatmentLevel']}」相对「{contrast['referenceLevel']}」的调整后 log2 差值。"
                "模型未拟合因素交互项。"
            ),
            "P 值使用模型对比 t 检验；P 值使用 Benjamini–Hochberg 方法校正为 FDR；没有对缺失值进行插补。",
            "多因素模型假设样本相互独立、误差方差相同且残差近似正态；本版不估计随机效应，请按实验设计复核这些假设。",
        ]
    else:
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
            else (
                "每个蛋白仅使用可用样本；其设计矩阵必须保持满秩且有残差自由度，否则该行不进行检验。"
                if design_type == "multifactor"
                else "按每个蛋白可用重复值计算，但每组至少需要 2 个有效重复；未执行数值填补。"
            )
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
    if multifactor_metadata:
        matrix_qc.update({
            "factorCount": len(multifactor_metadata["factorNames"]),
            "modelParameterCount": multifactor_metadata["parameterCount"],
            "modelResidualDegreesOfFreedom": multifactor_metadata["residualDegreesOfFreedom"],
        })
    method = {
        "designType": design_type,
        "test": (
            "additive multifactor linear-model contrast t-test"
            if design_type == "multifactor"
            else "paired two-sample t-test" if design_type == "paired" else "Welch two-sample t-test (unpaired)"
        ),
        "effect": (
            "adjusted mean log2 intensity difference for the specified factor contrast"
            if design_type == "multifactor"
            else (
                "mean(paired treatment log2 intensity - paired control log2 intensity)"
                if design_type == "paired"
                else "mean(treatment log2 intensity) - mean(control log2 intensity)"
            )
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
    if multifactor_metadata:
        method.update({
            **multifactor_metadata,
            "sampleFactors": design["sampleFactors"],
        })
    return synthetic_rows, row_reasons, {"qc": matrix_qc, "method": method, "rowWarnings": row_warnings}, warnings
