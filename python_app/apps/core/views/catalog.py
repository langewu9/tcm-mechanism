"""Read-only public knowledge catalogue and source provenance endpoints."""

from django.db.models import Count, Q
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from ..models import DataSource, EvidenceRelation, KnowledgeEntity
from ..serializers import DataSourceSerializer, EvidenceRelationSerializer, KnowledgeEntitySerializer


class DataSourceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DataSourceSerializer
    permission_classes = [IsAuthenticated]
    queryset = DataSource.objects.filter(enabled=True)


class KnowledgeEntityViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = KnowledgeEntitySerializer
    permission_classes = [IsAuthenticated]
    queryset = KnowledgeEntity.objects.all()
    search_fields = ["stable_id", "label"]
    filterset_fields = ["entity_type", "organism"]


class EvidenceRelationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EvidenceRelationSerializer
    permission_classes = [IsAuthenticated]
    queryset = EvidenceRelation.objects.select_related(
        "subject", "object", "source_release", "source_release__source"
    )
    filterset_fields = ["relation_type", "evidence_type", "organism", "source_release"]


@api_view(["GET"])
@permission_classes([AllowAny])
def home_stats(request):
    counts = KnowledgeEntity.objects.aggregate(
        herbs=Count("id", filter=Q(entity_type=KnowledgeEntity.EntityType.HERB)),
        compounds=Count("id", filter=Q(entity_type=KnowledgeEntity.EntityType.COMPOUND)),
        targets=Count(
            "id",
            filter=Q(entity_type__in=[KnowledgeEntity.EntityType.PROTEIN, KnowledgeEntity.EntityType.GENE]),
        ),
        pathways=Count("id", filter=Q(entity_type=KnowledgeEntity.EntityType.PATHWAY)),
    )
    return Response({"counts": counts})
