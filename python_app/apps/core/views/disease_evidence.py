from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.services.disease_evidence import search_disease_evidence
from apps.core.services.catalog_visualization import fingerprint_result
from apps.core.models import AnalysisTask
from apps.core.serializers.research import AnalysisTaskSerializer


class DiseaseEvidenceQuerySerializer(serializers.Serializer):
    query = serializers.CharField(max_length=120, trim_whitespace=True)

    def validate_query(self, value):
        from apps.core.services.disease_names import expand_disease_queries
        try:
            expand_disease_queries(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return value


class DiseaseEvidenceEntitySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    stableId = serializers.CharField()
    label = serializers.CharField()
    sourceSlug = serializers.CharField(allow_null=True)
    sourceVersion = serializers.CharField(allow_null=True)


class DiseaseEvidenceRelationSerializer(serializers.Serializer):
    sourceRowId = serializers.JSONField(required=False, allow_null=True)
    sourceChecksumSha256 = serializers.CharField(required=False, allow_blank=True)
    sourceFile = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    sourceDiseaseLabel = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    sourceHerbLabel = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    sourceTargetLabel = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    relationId = serializers.IntegerField()
    subjectId = serializers.IntegerField()
    objectId = serializers.IntegerField()
    sourceReleaseId = serializers.IntegerField()
    subject = serializers.CharField()
    object = serializers.CharField()
    subjectType = serializers.CharField()
    objectType = serializers.CharField()
    relationType = serializers.CharField()
    evidenceType = serializers.CharField()
    sourceSlug = serializers.CharField()
    sourceVersion = serializers.CharField()
    sourceRecordId = serializers.CharField()
    score = serializers.FloatField(allow_null=True)


class DiseaseEvidenceLinkSerializer(serializers.Serializer):
    relationId = serializers.IntegerField()
    diseaseId = serializers.IntegerField()
    herbId = serializers.IntegerField(allow_null=True)
    targetId = serializers.IntegerField(allow_null=True)
    sourceReleaseId = serializers.IntegerField()
    sourceFile = serializers.CharField(allow_null=True, allow_blank=True)
    sourceDiseaseLabel = serializers.CharField(allow_null=True, allow_blank=True)
    sourceHerbLabel = serializers.CharField(allow_null=True, allow_blank=True)
    sourceTargetLabel = serializers.CharField(allow_null=True, allow_blank=True)
    disease = serializers.CharField()
    herb = serializers.CharField(allow_blank=True)
    target = serializers.CharField(allow_blank=True)
    relationType = serializers.CharField()
    sourceSlug = serializers.CharField()
    sourceVersion = serializers.CharField()
    sourceRecordId = serializers.CharField()


class DiseaseEvidenceCountsSerializer(serializers.Serializer):
    diseases = serializers.IntegerField()
    herbs = serializers.IntegerField()
    targets = serializers.IntegerField()
    links = serializers.IntegerField()
    relations = serializers.IntegerField()


class DiseaseEvidenceLimitsSerializer(serializers.Serializer):
    maxMatches = serializers.IntegerField()
    maxRelations = serializers.IntegerField()


class DiseaseEvidenceResponseSerializer(serializers.Serializer):
    dataQuality = serializers.JSONField(required=False)
    evidenceSha256 = serializers.CharField()
    resultSha256 = serializers.CharField()
    query = serializers.CharField()
    expandedQueries = serializers.ListField(child=serializers.CharField())
    aliasSource = serializers.CharField()
    aliasSourceCommit = serializers.CharField()
    matches = DiseaseEvidenceEntitySerializer(many=True)
    ambiguous = serializers.BooleanField()
    herbs = DiseaseEvidenceEntitySerializer(many=True)
    targets = DiseaseEvidenceEntitySerializer(many=True)
    relations = DiseaseEvidenceRelationSerializer(many=True)
    links = DiseaseEvidenceLinkSerializer(many=True)
    counts = DiseaseEvidenceCountsSerializer()
    truncated = serializers.BooleanField()
    limits = DiseaseEvidenceLimitsSerializer()


class DiseaseEvidenceSearchView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("query", OpenApiTypes.STR, required=True)],
        responses=DiseaseEvidenceResponseSerializer,
    )
    def get(self, request):
        parameters = DiseaseEvidenceQuerySerializer(data=request.query_params)
        parameters.is_valid(raise_exception=True)
        try:
            result = search_disease_evidence(parameters.validated_data["query"])
        except ValueError as exc:
            raise ValidationError({"query": str(exc)}) from exc
        return Response(DiseaseEvidenceResponseSerializer(fingerprint_result(result)).data)


class DiseaseEvidenceAnalysisRequestSerializer(DiseaseEvidenceQuerySerializer):
    expectedResultSha256 = serializers.RegexField(r"^[a-f0-9]{64}$")


class DiseaseEvidenceAnalysisView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=DiseaseEvidenceAnalysisRequestSerializer, responses={202: AnalysisTaskSerializer})
    def post(self, request):
        parameters = DiseaseEvidenceAnalysisRequestSerializer(data=request.data)
        parameters.is_valid(raise_exception=True)
        values = parameters.validated_data
        from apps.core.services.complete_evidence import dispatch_complete_task
        task = AnalysisTask.objects.create(owner=request.user, created_by=request.user,
            task_type=AnalysisTask.TaskType.NETWORK, input_parameters={
                "analysisKind": "disease_evidence", "algorithmVersion": "disease-evidence-2", "complete": True,
                "name": f"疾病证据 · {values['query']}", "query": values["query"],
                "expectedResultSha256": values["expectedResultSha256"],
            })
        dispatch_complete_task(task, request=request)
        return Response(AnalysisTaskSerializer(task).data, status=202)
