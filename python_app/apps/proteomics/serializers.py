from rest_framework import serializers

from .exceptions import ProteomicsInputError
from .raw_matrix import build_multifactor_design


class ProteomicsThresholdsSerializer(serializers.Serializer):
    log2FcMin = serializers.FloatField(min_value=0, max_value=100, default=1.0)
    fdrMax = serializers.FloatField(min_value=0, max_value=1, default=0.05)
    pValueMax = serializers.FloatField(min_value=0, max_value=1, default=0.05)


class ProteomicsMappingSerializer(serializers.Serializer):
    geneColumn = serializers.CharField(max_length=160, allow_blank=True, default="")
    proteinColumn = serializers.CharField(max_length=160, allow_blank=True, default="")
    log2FcColumn = serializers.CharField(max_length=160, allow_blank=True, default="")
    pValueColumn = serializers.CharField(max_length=160, allow_blank=True, default="")
    fdrColumn = serializers.CharField(max_length=160, allow_blank=True, default="")
    directionColumn = serializers.CharField(max_length=160, allow_blank=True, default="")


class ProteomicsSamplePairSerializer(serializers.Serializer):
    pairId = serializers.CharField(max_length=160, trim_whitespace=True)
    controlSample = serializers.CharField(max_length=160, trim_whitespace=True)
    treatmentSample = serializers.CharField(max_length=160, trim_whitespace=True)


class ProteomicsSampleFactorSerializer(serializers.Serializer):
    sampleColumn = serializers.CharField(max_length=160, trim_whitespace=True)
    factors = serializers.DictField(
        child=serializers.CharField(max_length=160, trim_whitespace=True),
    )


class ProteomicsMatrixDesignSerializer(serializers.Serializer):
    identifierColumn = serializers.CharField(max_length=160, trim_whitespace=True)
    sampleColumns = serializers.ListField(
        child=serializers.CharField(max_length=160, trim_whitespace=True), min_length=4, max_length=100
    )
    designType = serializers.ChoiceField(choices=["unpaired", "paired", "multifactor"], default="unpaired")
    controlSamples = serializers.ListField(
        child=serializers.CharField(max_length=160, trim_whitespace=True), required=False,
        min_length=2, max_length=100,
    )
    treatmentSamples = serializers.ListField(
        child=serializers.CharField(max_length=160, trim_whitespace=True), required=False,
        min_length=2, max_length=100,
    )
    samplePairs = ProteomicsSamplePairSerializer(many=True, required=False, min_length=2, max_length=50)
    sampleFactors = ProteomicsSampleFactorSerializer(many=True, required=False, max_length=100)
    contrastFactor = serializers.CharField(max_length=160, required=False, allow_blank=True, trim_whitespace=True)
    referenceLevel = serializers.CharField(max_length=160, required=False, allow_blank=True, trim_whitespace=True)
    treatmentLevel = serializers.CharField(max_length=160, required=False, allow_blank=True, trim_whitespace=True)
    valuesAreLog2 = serializers.BooleanField()
    normalization = serializers.ChoiceField(choices=["none", "median_center"])
    missingPolicy = serializers.ChoiceField(choices=["complete_rows", "available_replicates"])

    def validate(self, attrs):
        identifier = attrs["identifierColumn"]
        samples = attrs["sampleColumns"]
        control = attrs.get("controlSamples", [])
        treatment = attrs.get("treatmentSamples", [])
        pairs = attrs.get("samplePairs", [])
        if any(not value for value in [identifier, *samples, *control, *treatment]):
            raise serializers.ValidationError("标识列和样本列名称不能为空。")
        if len(set(samples)) != len(samples):
            raise serializers.ValidationError({"sampleColumns": "样本列不能重复。"})
        if attrs["designType"] == "multifactor":
            if pairs or control or treatment:
                raise serializers.ValidationError("多因素设计不能提交配对关系或传统对照/实验分组。")
            assignments = attrs.get("sampleFactors", [])
            if len(assignments) != len(samples):
                raise serializers.ValidationError({"sampleFactors": "每个样本列都必须有且只有一份因素设置。"})
            by_sample = {}
            for assignment in assignments:
                sample = assignment["sampleColumn"]
                if sample in by_sample:
                    raise serializers.ValidationError({"sampleFactors": "每个样本列只能出现一次。"})
                by_sample[sample] = assignment["factors"]
            if set(by_sample) != set(samples):
                raise serializers.ValidationError({"sampleFactors": "因素设置中的样本列必须与所选样本列一致。"})
            factor_names = set(assignments[0]["factors"]) if assignments else set()
            if len(factor_names) < 2 or len(factor_names) > 10:
                raise serializers.ValidationError({"sampleFactors": "多因素设计须指定 2 至 10 个分类因素。"})
            if any(set(factors) != factor_names for factors in by_sample.values()):
                raise serializers.ValidationError({"sampleFactors": "每个样本必须为相同的所有因素指定一个水平。"})
            if any(not name.strip() for name in factor_names) or any(
                not level.strip() for factors in by_sample.values() for level in factors.values()
            ):
                raise serializers.ValidationError({"sampleFactors": "因素名称和水平不能为空。"})
            levels_by_factor = {
                factor: {factors[factor] for factors in by_sample.values()}
                for factor in factor_names
            }
            if any(len(levels) < 2 for levels in levels_by_factor.values()):
                raise serializers.ValidationError({"sampleFactors": "多因素设计中的每个因素都必须至少有两个水平。"})
            contrast_factor = attrs.get("contrastFactor", "")
            reference_level = attrs.get("referenceLevel", "")
            treatment_level = attrs.get("treatmentLevel", "")
            if contrast_factor not in levels_by_factor:
                raise serializers.ValidationError({"contrastFactor": "请选择一个有效的主要对比因素。"})
            if reference_level == treatment_level or reference_level not in levels_by_factor[contrast_factor] or treatment_level not in levels_by_factor[contrast_factor]:
                raise serializers.ValidationError({"referenceLevel": "参考水平和实验水平必须是不同的已有水平。"})
            contrast_counts = {
                level: sum(factors[contrast_factor] == level for factors in by_sample.values())
                for level in (reference_level, treatment_level)
            }
            if any(count < 2 for count in contrast_counts.values()):
                raise serializers.ValidationError({"sampleFactors": "主要对比的每个水平至少需要 2 个样本。"})
            try:
                build_multifactor_design(samples, attrs)
            except ProteomicsInputError as exc:
                raise serializers.ValidationError({"sampleFactors": str(exc)}) from exc
        elif attrs["designType"] == "paired":
            pair_ids = [pair["pairId"] for pair in pairs]
            paired_controls = [pair["controlSample"] for pair in pairs]
            paired_treatments = [pair["treatmentSample"] for pair in pairs]
            if any(not value for pair in pairs for value in pair.values()):
                raise serializers.ValidationError("配对编号和两组样本列不能为空。")
            if len(set(pair_ids)) != len(pair_ids):
                raise serializers.ValidationError({"samplePairs": "配对编号不能重复。"})
            if len(set(paired_controls + paired_treatments)) != len(paired_controls + paired_treatments):
                raise serializers.ValidationError({"samplePairs": "一个样本列只能属于一个配对。"})
            if len(pairs) < 2:
                raise serializers.ValidationError({"samplePairs": "配对设计至少需要 2 对样本。"})
            if (control and control != paired_controls) or (treatment and treatment != paired_treatments):
                raise serializers.ValidationError("配对设计的分组列必须与配对关系一致。")
            attrs["controlSamples"] = paired_controls
            attrs["treatmentSamples"] = paired_treatments
            control = paired_controls
            treatment = paired_treatments
        elif pairs:
            raise serializers.ValidationError({"samplePairs": "非配对设计不能提交配对样本。"})
        if attrs["designType"] != "multifactor":
            if len(set(control)) != len(control) or len(set(treatment)) != len(treatment):
                raise serializers.ValidationError("对照组和实验组内的样本列不能重复。")
            if set(control) & set(treatment):
                raise serializers.ValidationError("同一个样本不能同时属于对照组和实验组。")
            if set(control) | set(treatment) != set(samples):
                raise serializers.ValidationError("所选样本列必须全部且仅属于对照组或实验组。")
        if identifier in samples:
            raise serializers.ValidationError("标识列不能同时作为样本数值列。")
        return attrs


class ProteomicsRunRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    analysisMode = serializers.ChoiceField(
        choices=["differential_table", "raw_matrix"], required=False, default="differential_table"
    )
    matrixDesign = ProteomicsMatrixDesignSerializer(required=False)
    externalReactome = serializers.BooleanField(required=False, default=False)
    externalString = serializers.BooleanField(required=False, default=False)
    externalGProfiler = serializers.BooleanField(required=False, default=False)
    stringRequiredScore = serializers.IntegerField(min_value=0, max_value=1000, required=False, default=700)
    mapping = ProteomicsMappingSerializer(required=False, default=dict)
    thresholds = ProteomicsThresholdsSerializer(required=False, default=dict)
    referenceTargets = serializers.ListField(
        child=serializers.CharField(max_length=160, allow_blank=False),
        required=False,
        default=list,
        max_length=2000,
    )

    def validate_referenceTargets(self, values):
        seen = set()
        output = []
        for value in values:
            for token in value.replace("，", ",").replace("、", ",").replace(";", ",").split(","):
                label = token.strip()
                key = label.upper()
                if label and key not in seen:
                    output.append(label)
                    seen.add(key)
                if len(output) > 2000:
                    raise serializers.ValidationError("候选靶点最多 2000 个。")
        return output

    def validate(self, attrs):
        attrs.setdefault("analysisMode", "differential_table")
        if attrs["analysisMode"] == "raw_matrix" and "matrixDesign" not in attrs:
            raise serializers.ValidationError({"matrixDesign": "原始矩阵分析必须提交样本分组设计。"})
        if attrs["analysisMode"] == "differential_table" and "matrixDesign" in attrs:
            raise serializers.ValidationError({"matrixDesign": "差异结果表模式不接收原始矩阵设计。"})
        attrs.setdefault("mapping", {})
        attrs.setdefault("externalReactome", False)
        attrs.setdefault("externalString", False)
        attrs.setdefault("externalGProfiler", False)
        attrs.setdefault("stringRequiredScore", 700)
        attrs.setdefault("thresholds", {"log2FcMin": 1.0, "fdrMax": 0.05, "pValueMax": 0.05})
        attrs.setdefault("referenceTargets", [])
        return attrs
