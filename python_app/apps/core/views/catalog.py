"""Versioned knowledge lookups and private, source-preserving query snapshots."""

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from ..models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity
from ..serializers import DataSourceSerializer, EvidenceRelationSerializer, KnowledgeEntitySerializer
from ..serializers.research import AnalysisTaskSerializer
from ..services.disease_names import ALIAS_DATA, disease_entity_queryset, expand_disease_queries, matched_disease_queries
from ..services.herb_evidence import batch_herb_component_evidence


class DataSourceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DataSourceSerializer
    permission_classes = [IsAuthenticated]
    queryset = DataSource.objects.filter(enabled=True)


class KnowledgeEntityViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = KnowledgeEntitySerializer
    permission_classes = [IsAuthenticated]
    queryset = KnowledgeEntity.objects.filter(is_active=True).filter(
        Q(source_release__isnull=True) | Q(source_release__source__enabled=True)
    ).select_related(
        "source_release", "source_release__source"
    )
    search_fields = ["stable_id", "label"]
    filterset_fields = ["entity_type", "organism"]


class EvidenceRelationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EvidenceRelationSerializer
    permission_classes = [IsAuthenticated]
    queryset = EvidenceRelation.objects.filter(
        is_active=True,
        subject__is_active=True,
        object__is_active=True,
        source_release__source__enabled=True,
    ).filter(
        (Q(subject__source_release__isnull=True) | Q(subject__source_release__source__enabled=True))
        & (Q(object__source_release__isnull=True) | Q(object__source_release__source__enabled=True))
    ).select_related(
        "subject", "object", "source_release", "source_release__source"
    )
    filterset_fields = ["relation_type", "evidence_type", "organism", "source_release"]


class EntityNeighborhoodSerializer(serializers.Serializer):
    entity = KnowledgeEntitySerializer()
    relations = EvidenceRelationSerializer(many=True)
    truncated = serializers.BooleanField()


class EntityNeighborhoodView(APIView):
    permission_classes = [IsAuthenticated]
    max_relations = 200

    @extend_schema(responses=EntityNeighborhoodSerializer)
    def get(self, request, entity_id):
        entity = get_object_or_404(
            KnowledgeEntity.objects.filter(is_active=True).filter(
                Q(source_release__isnull=True) | Q(source_release__source__enabled=True)
            ),
            pk=entity_id,
        )
        relations = EvidenceRelation.objects.filter(
            Q(subject=entity) | Q(object=entity),
            is_active=True,
            subject__is_active=True,
            object__is_active=True,
            source_release__source__enabled=True,
        ).filter(
            (Q(subject__source_release__isnull=True) | Q(subject__source_release__source__enabled=True))
            & (Q(object__source_release__isnull=True) | Q(object__source_release__source__enabled=True))
        ).select_related(
            "subject", "object", "source_release", "source_release__source"
        ).order_by("relation_type", "subject__label", "object__label", "source_release__version")
        records = list(relations[: self.max_relations + 1])
        truncated = len(records) > self.max_relations
        return Response({
            "entity": KnowledgeEntitySerializer(entity).data,
            "relations": EvidenceRelationSerializer(records[: self.max_relations], many=True).data,
            "truncated": truncated,
        })


class DiseaseAliasQuerySerializer(serializers.Serializer):
    query = serializers.CharField(max_length=120, trim_whitespace=True)


class DiseaseAliasEntitySerializer(KnowledgeEntitySerializer):
    matchedQueries = serializers.SerializerMethodField()

    class Meta(KnowledgeEntitySerializer.Meta):
        fields = [*KnowledgeEntitySerializer.Meta.fields, "matchedQueries"]

    def get_matchedQueries(self, obj) -> list[str]:
        return matched_disease_queries(obj, self.context["expanded_queries"])


class DiseaseAliasSearchResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    query = serializers.CharField()
    expandedQueries = serializers.ListField(child=serializers.CharField())
    aliasSource = serializers.CharField()
    aliasSourceCommit = serializers.CharField()
    results = DiseaseAliasEntitySerializer(many=True)


class DiseaseAliasSearchView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("query", OpenApiTypes.STR, required=True)],
        responses=DiseaseAliasSearchResponseSerializer,
    )
    def get(self, request):
        parameters = DiseaseAliasQuerySerializer(data=request.query_params)
        parameters.is_valid(raise_exception=True)
        query = parameters.validated_data["query"]
        try:
            expanded_queries = expand_disease_queries(query)
        except ValueError as exc:
            raise ValidationError({"query": str(exc)}) from exc
        queryset = disease_entity_queryset(expanded_queries)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        results = DiseaseAliasEntitySerializer(
            page,
            many=True,
            context={"request": request, "expanded_queries": expanded_queries},
        ).data
        return Response({
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "query": query,
            "expandedQueries": expanded_queries,
            "aliasSource": ALIAS_DATA["source"],
            "aliasSourceCommit": ALIAS_DATA["sourceCommit"],
            "results": results,
        })


class BatchHerbEvidenceRequestSerializer(serializers.Serializer):
    queryType = serializers.ChoiceField(choices=["herb", "compound"])
    queries = serializers.ListField(
        child=serializers.CharField(max_length=300, trim_whitespace=True),
        min_length=1,
        max_length=12,
    )

    def validate_queries(self, values):
        if self.initial_data.get('queryType') == 'herb' and any(len(value) > 120 for value in values):
            raise serializers.ValidationError('每个中药名称最多 120 个字符。')
        distinct = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if not distinct:
            raise serializers.ValidationError("请至少输入一个有效名称。")
        if self.initial_data.get('queryType') == 'compound':
            from ..services.compound_lookup import CompoundLookupInputError, validate_compound_query
            try:
                for query in distinct:
                    validate_compound_query(query)
            except CompoundLookupInputError as exc:
                raise serializers.ValidationError(str(exc)) from exc
        return distinct


class BatchHerbEvidenceEntitySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    stableId = serializers.CharField()
    label = serializers.CharField()
    sourceReleaseId = serializers.IntegerField(allow_null=True)
    sourceSlug = serializers.CharField(allow_null=True)
    sourceVersion = serializers.CharField(allow_null=True)


class BatchHerbEvidenceRelationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
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


class BatchHerbEvidenceItemSerializer(serializers.Serializer):
    query = serializers.CharField()
    resolution = serializers.JSONField(required=False)
    matches = BatchHerbEvidenceEntitySerializer(many=True)
    ambiguous = serializers.BooleanField()
    herbs = BatchHerbEvidenceEntitySerializer(many=True)
    compounds = BatchHerbEvidenceEntitySerializer(many=True)
    targets = BatchHerbEvidenceEntitySerializer(many=True)
    relations = BatchHerbEvidenceRelationSerializer(many=True)
    truncated = serializers.BooleanField()


class BatchHerbEvidenceResponseSerializer(serializers.Serializer):
    queryType = serializers.ChoiceField(choices=["herb", "compound"])
    resultSha256 = serializers.CharField()
    results = BatchHerbEvidenceItemSerializer(many=True)


class BatchHerbEvidenceView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=BatchHerbEvidenceRequestSerializer, responses=BatchHerbEvidenceResponseSerializer)
    def post(self, request):
        parameters = BatchHerbEvidenceRequestSerializer(data=request.data)
        parameters.is_valid(raise_exception=True)
        values = parameters.validated_data
        return Response(batch_herb_component_evidence(
            query_type=values["queryType"],
            queries=values["queries"],
        ))


class CatalogAnalysisRequestSerializer(BatchHerbEvidenceRequestSerializer):
    expectedResultSha256 = serializers.RegexField(r"^[a-f0-9]{64}$")
    complete = serializers.BooleanField(required=False, default=False)


class CatalogResultConflict(APIException):
    status_code = 409
    default_code = "catalog_results_changed"
    default_detail = "目录数据已更新，请重新检索后再保存关系图。"


class CatalogEvidenceAnalysisView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=CatalogAnalysisRequestSerializer, responses={201: AnalysisTaskSerializer, 202: AnalysisTaskSerializer})
    def post(self, request):
        parameters = CatalogAnalysisRequestSerializer(data=request.data)
        parameters.is_valid(raise_exception=True)
        values = parameters.validated_data
        from ..services.catalog_analysis import CatalogSnapshotChanged, save_catalog_analysis
        if values["complete"]:
            # Validate the preview again inside the worker's consistent read.
            from ..services.complete_evidence import VERSION, dispatch_complete_task
            task = AnalysisTask.objects.create(owner=request.user, created_by=request.user,
                task_type=AnalysisTask.TaskType.NETWORK, input_parameters={
                    "analysisKind": "catalog_evidence", "algorithmVersion": VERSION,
                    "complete": True, "queryType": values["queryType"], "queries": values["queries"],
                    "expectedResultSha256": values["expectedResultSha256"],
                    **({'lookupVersion': 'compound-lookup-1'} if values['queryType'] == 'compound' else {}),
                })
            dispatch_complete_task(task, request=request)
            return Response(AnalysisTaskSerializer(task).data, status=202)
        try:
            task = save_catalog_analysis(user=request.user, query_type=values["queryType"],
                                         queries=values["queries"], expected_sha256=values["expectedResultSha256"])
        except CatalogSnapshotChanged as exc:
            raise CatalogResultConflict() from exc
        except ValueError as exc:
            raise ValidationError({"queries": str(exc)}) from exc
        return Response(AnalysisTaskSerializer(task).data, status=201)


class HomeStatsCountsSerializer(serializers.Serializer):
    herbs = serializers.IntegerField()
    compounds = serializers.IntegerField()
    targets = serializers.IntegerField()
    pathways = serializers.IntegerField()


class HomeStatsSerializer(serializers.Serializer):
    counts = HomeStatsCountsSerializer()


class HomeStatsView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=HomeStatsSerializer)
    def get(self, request):
        counts = KnowledgeEntity.objects.filter(is_active=True).filter(
            Q(source_release__isnull=True) | Q(source_release__source__enabled=True)
        ).aggregate(
            herbs=Count("id", filter=Q(entity_type=KnowledgeEntity.EntityType.HERB)),
            compounds=Count("id", filter=Q(entity_type=KnowledgeEntity.EntityType.COMPOUND)),
            targets=Count(
                "id",
                filter=Q(entity_type__in=[KnowledgeEntity.EntityType.PROTEIN, KnowledgeEntity.EntityType.GENE]),
            ),
            pathways=Count("id", filter=Q(entity_type=KnowledgeEntity.EntityType.PATHWAY)),
        )
        return Response({"counts": counts})
