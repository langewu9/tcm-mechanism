"""Researcher-owned datasets, cases, and analysis task records."""

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from ..models import AnalysisTask, MedicalCase, ResearchDataset
from ..serializers import AnalysisTaskSerializer, MedicalCaseSerializer, ResearchDatasetSerializer


class ResearchDatasetViewSet(viewsets.ModelViewSet):
    queryset = ResearchDataset.objects.none()
    serializer_class = ResearchDatasetSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ResearchDataset.objects.none()
        queryset = ResearchDataset.objects.all()
        if not self.request.user.is_superuser:
            queryset = queryset.filter(owner=self.request.user)
        return queryset

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class MedicalCaseViewSet(viewsets.ModelViewSet):
    queryset = MedicalCase.objects.none()
    serializer_class = MedicalCaseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MedicalCase.objects.none()
        queryset = MedicalCase.objects.all()
        if not self.request.user.is_superuser:
            queryset = queryset.filter(owner=self.request.user)
        return queryset

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class AnalysisTaskViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AnalysisTask.objects.none()
    serializer_class = AnalysisTaskSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AnalysisTask.objects.none()
        queryset = AnalysisTask.objects.select_related("dataset", "medical_case")
        if not self.request.user.is_superuser:
            queryset = queryset.filter(owner=self.request.user)
        return queryset
