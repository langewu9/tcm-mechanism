"""Read-only public knowledge catalogue and source provenance endpoints."""

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import DataSource, EvidenceRelation, KnowledgeEntity
from ..serializers import DataSourceSerializer, EvidenceRelationSerializer, KnowledgeEntitySerializer


class DataSourceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DataSourceSerializer
    permission_classes = [IsAuthenticated]
    queryset = DataSource.objects.filter(enabled=True)


class KnowledgeEntityViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = KnowledgeEntitySerializer
    permission_classes = [IsAuthenticated]
    queryset = KnowledgeEntity.objects.filter(is_active=True).select_related(
        "source_release", "source_release__source"
    )
    search_fields = ["stable_id", "label"]
    filterset_fields = ["entity_type", "organism"]


class EvidenceRelationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EvidenceRelationSerializer
    permission_classes = [IsAuthenticated]
    queryset = EvidenceRelation.objects.filter(
        is_active=True, subject__is_active=True, object__is_active=True
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
        entity = get_object_or_404(KnowledgeEntity.objects.filter(is_active=True), pk=entity_id)
        relations = EvidenceRelation.objects.filter(
            Q(subject=entity) | Q(object=entity),
            is_active=True,
            subject__is_active=True,
            object__is_active=True,
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
        counts = KnowledgeEntity.objects.filter(is_active=True).aggregate(
            herbs=Count("id", filter=Q(entity_type=KnowledgeEntity.EntityType.HERB)),
            compounds=Count("id", filter=Q(entity_type=KnowledgeEntity.EntityType.COMPOUND)),
            targets=Count(
                "id",
                filter=Q(entity_type__in=[KnowledgeEntity.EntityType.PROTEIN, KnowledgeEntity.EntityType.GENE]),
            ),
            pathways=Count("id", filter=Q(entity_type=KnowledgeEntity.EntityType.PATHWAY)),
        )
        return Response({"counts": counts})
