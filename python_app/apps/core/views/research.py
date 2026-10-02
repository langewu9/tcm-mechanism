"""Researcher-owned datasets, cases, and analysis task records."""

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..exceptions import ResourceConflict, TaskQueueUnavailable
from ..models import AnalysisTask, MedicalCase, MedicalCaseAuditEvent, ResearchDataset, VisualizationArtifact
from ..serializers import AnalysisTaskSerializer, MedicalCaseAuditEventSerializer, MedicalCaseSerializer, ResearchDatasetSerializer, VisualizationRequestSerializer
from apps.proteomics.serializers import ProteomicsRunRequestSerializer
from apps.proteomics.models import ProteomicsRowResult
from apps.proteomics.serializers_rows import ProteomicsRowResultSerializer
from apps.proteomics.services import ALGORITHM_VERSION


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
                "algorithmVersion": ALGORITHM_VERSION,
                "externalReactome": data["externalReactome"],
                "externalString": data["externalString"],
                "externalGProfiler": data["externalGProfiler"],
                "stringRequiredScore": data["stringRequiredScore"],
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
        from ..services.case_audit import case_field_values, create_case_audit_event

        with transaction.atomic():
            case = serializer.save(owner=self.request.user)
            create_case_audit_event(
                case=case,
                actor=self.request.user,
                action=MedicalCaseAuditEvent.Action.CREATED,
                after=case_field_values(case),
            )

    def perform_update(self, serializer):
        from ..services.case_audit import case_field_values, create_case_audit_event

        case = serializer.instance
        fields = set(serializer.validated_data)
        audited_fields = fields | {"review_status", "reviewed_by_id", "reviewed_at"}
        before = case_field_values(case, audited_fields)
        with transaction.atomic():
            case = serializer.save()
            content_fields = fields - {"review_status", "reviewed_by_id", "reviewed_at"}
            content_changed = any(before[field] != getattr(case, field) for field in content_fields)
            if content_changed and case.review_status == MedicalCase.ReviewStatus.REVIEWED:
                case.review_status = MedicalCase.ReviewStatus.DRAFT
                case.reviewed_by = None
                case.reviewed_at = None
                case.save(update_fields=["review_status", "reviewed_by", "reviewed_at", "updated_at"])
            after = case_field_values(case, audited_fields)
            changed = {field for field in audited_fields if before[field] != after[field]}
            if changed:
                create_case_audit_event(
                    case=case,
                    actor=self.request.user,
                    action=MedicalCaseAuditEvent.Action.UPDATED,
                    before={field: before[field] for field in changed},
                    after={field: after[field] for field in changed},
                )

    def perform_destroy(self, instance):
        if instance.analysis_tasks.exists():
            raise ResourceConflict("医案已有分析任务，为保留结果溯源不能删除。")
        from ..services.case_audit import case_field_values, create_case_audit_event

        with transaction.atomic():
            create_case_audit_event(
                case=instance,
                actor=self.request.user,
                action=MedicalCaseAuditEvent.Action.DELETED,
                before=case_field_values(instance),
            )
            super().perform_destroy(instance)

    @action(detail=True, methods=["get"], url_path="audit")
    def audit(self, request, pk=None):
        case = self.get_object()
        events = MedicalCaseAuditEvent.objects.filter(case_id_snapshot=case.pk).select_related("actor")
        page = self.paginate_queryset(events)
        if page is not None:
            return self.get_paginated_response(MedicalCaseAuditEventSerializer(page, many=True).data)
        return Response(MedicalCaseAuditEventSerializer(events, many=True).data)

    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request, pk=None):
        if not request.user.is_superuser:
            raise PermissionDenied("只有平台管理员可以审核医案。")
        if request.data.get("decision") != "approve":
            raise ValidationError({"decision": "审核操作必须明确提交 approve。"})
        case = self.get_object()
        from ..services.case_audit import create_case_audit_event

        before = {"review_status": case.review_status, "reviewed_by_id": case.reviewed_by_id}
        with transaction.atomic():
            case.review_status = MedicalCase.ReviewStatus.REVIEWED
            case.reviewed_at = timezone.now()
            case.reviewed_by = request.user
            case.save(update_fields=["review_status", "reviewed_at", "reviewed_by", "updated_at"])
            create_case_audit_event(
                case=case,
                actor=request.user,
                action=MedicalCaseAuditEvent.Action.REVIEWED,
                before=before,
                after={"review_status": case.review_status, "reviewed_by_id": case.reviewed_by_id},
                metadata={"decision": "approve"},
            )
        return Response(MedicalCaseSerializer(case).data)


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

    @action(detail=True, methods=["post"], url_path="visualizations")
    def visualizations(self, request, pk=None):
        parent_task = self.get_object()
        if not settings.R_VIZ_BASE_URL or not settings.R_VIZ_API_TOKEN:
            raise TaskQueueUnavailable("R 图表服务尚未配置，请先启动可访问的 Plumber 服务。")
        serializer = VisualizationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from ..services.visualization import VisualizationInputError, queue_visualization

        try:
            task, created = queue_visualization(
                parent_task=parent_task,
                user=request.user,
                chart_key=serializer.validated_data["chartKey"],
            )
        except VisualizationInputError as exc:
            raise ValidationError({"chartKey": str(exc)}) from exc
        if created:
            try:
                from ..tasks import run_visualization_task

                run_visualization_task.apply_async(args=[task.pk])
            except Exception as exc:
                task.status = AnalysisTask.Status.FAILED
                task.progress = 100
                task.error_summary = "R 图表任务队列暂不可用，请稍后重试。"
                task.finished_at = timezone.now()
                task.save(update_fields=["status", "progress", "error_summary", "finished_at"])
                raise TaskQueueUnavailable() from exc
        return Response(
            AnalysisTaskSerializer(task).data,
            status=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK,
        )

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


class VisualizationArtifactDownloadView(APIView):
    """Serve private R artifacts only through an authenticated, owner-scoped URL."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.BINARY})
    def get(self, request, pk):
        queryset = VisualizationArtifact.objects.select_related("task", "render_task", "owner")
        if not request.user.is_superuser:
            queryset = queryset.filter(owner=request.user)
        try:
            artifact = queryset.get(pk=pk)
        except VisualizationArtifact.DoesNotExist as exc:
            raise NotFound("图表文件不存在或无权访问。") from exc
        if not default_storage.exists(artifact.storage_key):
            raise NotFound("图表文件暂不可用。")
        response = FileResponse(
            default_storage.open(artifact.storage_key, "rb"),
            as_attachment=not (
                request.query_params.get("inline") == "1"
                and artifact.file_format in {"svg", "png"}
            ),
            filename=artifact.filename,
            content_type=artifact.mime_type,
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        response["Content-Security-Policy"] = "sandbox"
        return response
