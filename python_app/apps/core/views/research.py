"""Researcher-owned datasets, cases, and analysis task records."""

from django.core.files.storage import default_storage
from django.http import FileResponse
from rest_framework.exceptions import NotFound
from rest_framework import viewsets
from rest_framework.decorators import action
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

    def perform_destroy(self, instance):
        storage_key = instance.storage_key
        super().perform_destroy(instance)
        if storage_key:
            default_storage.delete(storage_key)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        dataset = self.get_object()
        if not dataset.storage_key or not default_storage.exists(dataset.storage_key):
            raise NotFound("原始文件暂不可用。")
        filename = dataset.original_filename or f"dataset-{dataset.pk}"
        return FileResponse(
            default_storage.open(dataset.storage_key, "rb"),
            as_attachment=True,
            filename=filename,
        )


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
