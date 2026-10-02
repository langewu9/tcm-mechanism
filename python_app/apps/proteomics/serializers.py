from rest_framework import serializers


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


class ProteomicsMatrixDesignSerializer(serializers.Serializer):
    identifierColumn = serializers.CharField(max_length=160, trim_whitespace=True)
    sampleColumns = serializers.ListField(
        child=serializers.CharField(max_length=160, trim_whitespace=True), min_length=4, max_length=100
    )
    controlSamples = serializers.ListField(
        child=serializers.CharField(max_length=160, trim_whitespace=True), min_length=2, max_length=100
    )
    treatmentSamples = serializers.ListField(
        child=serializers.CharField(max_length=160, trim_whitespace=True), min_length=2, max_length=100
    )
    valuesAreLog2 = serializers.BooleanField()
    normalization = serializers.ChoiceField(choices=["none", "median_center"])
    missingPolicy = serializers.ChoiceField(choices=["complete_rows", "available_replicates"])

    def validate(self, attrs):
        identifier = attrs["identifierColumn"]
        samples = attrs["sampleColumns"]
        control = attrs["controlSamples"]
        treatment = attrs["treatmentSamples"]
        if any(not value for value in [identifier, *samples, *control, *treatment]):
            raise serializers.ValidationError("标识列和样本列名称不能为空。")
        if len(set(samples)) != len(samples):
            raise serializers.ValidationError({"sampleColumns": "样本列不能重复。"})
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
