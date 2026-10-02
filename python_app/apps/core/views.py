from django.db import DatabaseError, connection
from django.views.generic import TemplateView
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import (
    AnalysisTask,
    DataSource,
    EvidenceRelation,
    KnowledgeEntity,
    MedicalCase,
    ResearchDataset,
)
from .serializers import (
    AnalysisTaskSerializer,
    DataSourceSerializer,
    EvidenceRelationSerializer,
    KnowledgeEntitySerializer,
    MedicalCaseSerializer,
    ResearchDatasetSerializer,
)


class HomeView(TemplateView):
    template_name = "core/home.html"


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return Response({"status": "degraded", "database": "unavailable"}, status=503)
    return Response({"status": "ok", "database": "ok", "api_version": "v1"})


class ResearchDatasetViewSet(viewsets.ModelViewSet):
    serializer_class = ResearchDatasetSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ResearchDataset.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class MedicalCaseViewSet(viewsets.ModelViewSet):
    serializer_class = MedicalCaseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return MedicalCase.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class AnalysisTaskViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AnalysisTaskSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return AnalysisTask.objects.filter(owner=self.request.user).select_related("dataset", "medical_case")


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
