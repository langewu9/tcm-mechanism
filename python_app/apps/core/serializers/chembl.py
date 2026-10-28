from rest_framework import serializers

from ..services.chembl import CHEMBL_ID_RE


class ChemblMoleculeSearchRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=120, trim_whitespace=True)
    consent = serializers.BooleanField()

    def validate_query(self, value):
        if not value:
            raise serializers.ValidationError("请输入化合物名称或标识。")
        if any(ord(character) < 32 for character in value):
            raise serializers.ValidationError("查询词包含不支持的控制字符。")
        return value

    def validate_consent(self, value):
        if not value:
            raise serializers.ValidationError("请先确认将查询词及系统展开的别名发送到 ChEMBL 官方服务。")
        return value


class ChemblActivityRequestSerializer(serializers.Serializer):
    chemblId = serializers.RegexField(CHEMBL_ID_RE, max_length=20)
    consent = serializers.BooleanField()

    def validate_consent(self, value):
        if not value:
            raise serializers.ValidationError("请先确认将 ChEMBL 化合物编号发送到官方服务。")
        return value


class ChemblMoleculeSerializer(serializers.Serializer):
    chemblId = serializers.CharField()
    preferredName = serializers.CharField(allow_blank=True)
    moleculeType = serializers.CharField(allow_blank=True)
    maxPhase = serializers.CharField(allow_blank=True)
    firstApproval = serializers.CharField(allow_blank=True)
    naturalProduct = serializers.IntegerField(allow_null=True)
    canonicalSmiles = serializers.CharField(allow_blank=True)
    recordUrl = serializers.URLField()
    sourceQuery = serializers.CharField()
    matchedQueries = serializers.ListField(child=serializers.CharField())
    componentChinese = serializers.CharField(allow_blank=True)
    componentEnglish = serializers.CharField()
    componentLatin = serializers.CharField(allow_blank=True)


class ChemblNameMatchSerializer(serializers.Serializer):
    query = serializers.CharField()
    chinese = serializers.CharField()
    english = serializers.CharField()
    latin = serializers.CharField()
    matchedTerms = serializers.CharField()
    hitCount = serializers.IntegerField()


class ChemblMoleculeSearchResponseSerializer(serializers.Serializer):
    source = serializers.CharField()
    sourceVersion = serializers.CharField()
    releaseDate = serializers.CharField(allow_blank=True)
    query = serializers.CharField()
    queries = serializers.ListField(child=serializers.CharField())
    resolvedQueries = serializers.ListField(child=serializers.CharField())
    nameMatches = ChemblNameMatchSerializer(many=True)
    aliasSource = serializers.CharField()
    aliasSourceCommit = serializers.CharField()
    failedQueries = serializers.ListField(child=serializers.CharField())
    endpoint = serializers.URLField()
    retrievedAt = serializers.DateTimeField()
    queriedTerms = serializers.IntegerField()
    resultLimit = serializers.IntegerField()
    totalCount = serializers.IntegerField()
    truncated = serializers.BooleanField()
    results = ChemblMoleculeSerializer(many=True)


class ComponentCompareRequestSerializer(serializers.Serializer):
    detected = serializers.CharField(max_length=6000, trim_whitespace=True)
    reference = serializers.CharField(max_length=6000, trim_whitespace=True)

    def validate(self, attrs):
        if not attrs["detected"] or not attrs["reference"]:
            raise serializers.ValidationError("请分别输入检测成分与参考成分。")
        return attrs


class ComponentCompareResponseSerializer(serializers.Serializer):
    evidenceSha256 = serializers.CharField()
    aliasSource = serializers.CharField()
    aliasSourceCommit = serializers.CharField()
    detected = serializers.ListField(child=serializers.DictField())
    reference = serializers.ListField(child=serializers.DictField())
    exactMatches = serializers.ListField(child=serializers.DictField())
    detectedOnly = serializers.ListField(child=serializers.DictField())
    referenceOnly = serializers.ListField(child=serializers.DictField())
    familyMatches = serializers.ListField(child=serializers.DictField())
    rows = serializers.ListField(child=serializers.DictField())
    counts = serializers.DictField()


class ChemblActivitySerializer(serializers.Serializer):
    activityId = serializers.IntegerField(allow_null=True)
    standardType = serializers.CharField(allow_blank=True)
    relation = serializers.CharField(allow_blank=True)
    value = serializers.CharField(allow_blank=True)
    units = serializers.CharField(allow_blank=True)
    pchemblValue = serializers.CharField(allow_blank=True)
    targetId = serializers.CharField(allow_blank=True)
    targetName = serializers.CharField(allow_blank=True)
    assayId = serializers.CharField(allow_blank=True)
    assayDescription = serializers.CharField(allow_blank=True)
    assayType = serializers.CharField(allow_blank=True)
    documentId = serializers.CharField(allow_blank=True)


class ChemblActivityResponseSerializer(serializers.Serializer):
    source = serializers.CharField()
    sourceVersion = serializers.CharField()
    releaseDate = serializers.CharField(allow_blank=True)
    chemblId = serializers.CharField()
    endpoint = serializers.URLField()
    retrievedAt = serializers.DateTimeField()
    resultLimit = serializers.IntegerField()
    totalCount = serializers.IntegerField()
    truncated = serializers.BooleanField()
    results = ChemblActivitySerializer(many=True)
