"""Researcher-owned datasets, cases, and analysis task records."""

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from ..models import AnalysisTask, MedicalCase, ResearchDataset
from ..serializers import AnalysisTaskSerializer, MedicalCaseSerializer, ResearchDatasetSerializer


class ResearchDatasetViewSet(viewsets.ModelViewSet):
    serializer_class = ResearchDatasetSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = ResearchDataset.objects.all()
        if not self.request.user.is_superuser:
            queryset = queryset.filter(owner=self.request.user)
        return queryset

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class MedicalCaseViewSet(viewsets.ModelViewSet):
    serializer_class = MedicalCaseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = MedicalCase.objects.all()
        if not self.request.user.is_superuser:
            queryset = queryset.filter(owner=self.request.user)
        return queryset

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class AnalysisTaskViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AnalysisTaskSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = AnalysisTask.objects.select_related("dataset", "medical_case")
        if not self.request.user.is_superuser:
            queryset = queryset.filter(owner=self.request.user)
        return queryset
