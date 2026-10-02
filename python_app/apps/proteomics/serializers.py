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


class ProteomicsRunRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)
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
        attrs.setdefault("mapping", {})
        attrs.setdefault("externalReactome", False)
        attrs.setdefault("externalString", False)
        attrs.setdefault("externalGProfiler", False)
        attrs.setdefault("stringRequiredScore", 700)
        attrs.setdefault("thresholds", {"log2FcMin": 1.0, "fdrMax": 0.05, "pValueMax": 0.05})
        attrs.setdefault("referenceTargets", [])
        return attrs
