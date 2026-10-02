"""Researcher-owned datasets, cases, and analysis task records."""

from django.core.files.storage import default_storage
from django.http import FileResponse, HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..exceptions import ResourceConflict, TaskQueueUnavailable
from ..models import AnalysisTask, MedicalCase, ResearchDataset
from ..serializers import AnalysisTaskSerializer, MedicalCaseSerializer, ResearchDatasetSerializer
from apps.proteomics.serializers import ProteomicsRunRequestSerializer
from apps.proteomics.models import ProteomicsRowResult
from apps.proteomics.serializers_rows import ProteomicsRowResultSerializer


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
        if instance.analysis_tasks.exists():
            raise ResourceConflict("数据集已有分析任务，为保留结果溯源不能删除。")
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

    @action(detail=True, methods=["post"])
    def analyze(self, request, pk=None):
        dataset = self.get_object()
        if not dataset.storage_key or not default_storage.exists(dataset.storage_key):
            raise NotFound("原始数据文件暂不可用。")
        serializer = ProteomicsRunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        task = AnalysisTask.objects.create(
            owner=dataset.owner,
            created_by=request.user,
            task_type=AnalysisTask.TaskType.PROTEOMICS,
            dataset=dataset,
            input_parameters={
                "name": data.get("name") or dataset.name,
                "datasetSha256": dataset.content_sha256,
                "algorithmVersion": "proteomics-py-1.1",
                "externalReactome": data["externalReactome"],
                "mapping": data["mapping"],
                "thresholds": data["thresholds"],
                "referenceTargets": data["referenceTargets"],
            },
        )
        try:
            from apps.proteomics.tasks import run_proteomics_task

            run_proteomics_task.apply_async(args=[task.pk])
        except Exception as exc:
            task.status = AnalysisTask.Status.FAILED
            task.progress = 100
            task.error_summary = "任务队列暂不可用，请稍后重试。"
            from django.utils import timezone

            task.finished_at = timezone.now()
            task.save(update_fields=["status", "progress", "error_summary", "finished_at"])
            raise TaskQueueUnavailable() from exc
        return Response(AnalysisTaskSerializer(task).data, status=status.HTTP_202_ACCEPTED)


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

    def perform_destroy(self, instance):
        if instance.analysis_tasks.exists():
            raise ResourceConflict("医案已有分析任务，为保留结果溯源不能删除。")


class AnalysisTaskViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AnalysisTask.objects.none()
    serializer_class = AnalysisTaskSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AnalysisTask.objects.none()
        queryset = AnalysisTask.objects.select_related("dataset", "medical_case", "owner", "created_by")
        if not self.request.user.is_superuser:
            queryset = queryset.filter(owner=self.request.user)
        return queryset

    @action(detail=True, methods=["get"])
    def rows(self, request, pk=None):
        task = self.get_object()
        if task.task_type != AnalysisTask.TaskType.PROTEOMICS:
            raise NotFound("该分析任务没有蛋白组学行结果。")
        queryset = ProteomicsRowResult.objects.filter(task=task).select_related("matched_entity")
        selected = request.query_params.get("selected")
        if selected in {"true", "1"}:
            queryset = queryset.filter(selected=True)
        elif selected in {"false", "0"}:
            queryset = queryset.filter(selected=False)
        page = self.paginate_queryset(queryset)
        serializer = ProteomicsRowResultSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        task = self.get_object()
        if task.task_type != AnalysisTask.TaskType.PROTEOMICS or task.status != AnalysisTask.Status.SUCCEEDED:
            raise NotFound("该分析任务没有可导出的蛋白组学结果。")
        export_format = request.query_params.get("file_format", "csv").lower()
        if export_format not in {"csv", "xlsx"}:
            raise ValidationError({"file_format": "仅支持 csv 或 xlsx。"})

        from apps.proteomics.exports import (
            export_proteomics_csv,
            export_proteomics_xlsx,
            rows_for_task,
        )

        rows = rows_for_task(task)
        if export_format == "csv":
            content = export_proteomics_csv(rows)
            content_type = "text/csv; charset=utf-8"
        else:
            content = export_proteomics_xlsx(task, rows)
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="proteomics-task-{task.pk}.{export_format}"'
        response["X-Content-Type-Options"] = "nosniff"
        return response
