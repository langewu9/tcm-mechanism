"""Researcher-owned datasets, cases, and analysis task records."""

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..exceptions import ResourceConflict, TaskQueueUnavailable
from ..models import AnalysisTask, KnowledgeEntity, MedicalCase, MedicalCaseAuditEvent, MedicalCaseCandidate, ResearchDataset, VisualizationArtifact
from ..serializers import AnalysisTaskSerializer, CaseAnalysisRequestSerializer, CaseCandidateReviewRequestSerializer, MedicalCaseAuditEventSerializer, MedicalCaseCandidateSerializer, MedicalCaseSerializer, ResearchAssistantRequestSerializer, ResearchDashboardSerializer, ResearchDatasetSerializer, VisualizationRequestSerializer
from apps.proteomics.serializers import ProteomicsRunRequestSerializer
from apps.proteomics.models import ProteomicsRowResult
from apps.proteomics.serializers_rows import ProteomicsRowResultSerializer
from apps.proteomics.services import ALGORITHM_VERSION


class ResearchDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=ResearchDashboardSerializer)
    def get(self, request):
        owner_filter = {} if request.user.is_superuser else {"owner": request.user}
        visible_entities = KnowledgeEntity.objects.filter(is_active=True).filter(
            Q(source_release__isnull=True) | Q(source_release__source__enabled=True)
        )
        counts = visible_entities.aggregate(
            herbs=Count("id", filter=Q(entity_type=KnowledgeEntity.EntityType.HERB)),
            compounds=Count("id", filter=Q(entity_type=KnowledgeEntity.EntityType.COMPOUND)),
            targets=Count(
                "id",
                filter=Q(
                    entity_type__in=[
                        KnowledgeEntity.EntityType.PROTEIN,
                        KnowledgeEntity.EntityType.GENE,
                    ]
                ),
            ),
            pathways=Count("id", filter=Q(entity_type=KnowledgeEntity.EntityType.PATHWAY)),
        )
        counts.update(
            datasets=ResearchDataset.objects.filter(**owner_filter).count(),
            cases=MedicalCase.objects.filter(**owner_filter).count(),
            tasks=AnalysisTask.objects.filter(**owner_filter).count(),
        )
        latest_tasks = AnalysisTask.objects.filter(**owner_filter).order_by("-created_at")[:5]
        return Response(
            ResearchDashboardSerializer(
                {"stats": counts, "latest_tasks": latest_tasks}
            ).data
        )


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
        query = self.request.query_params.get("q", "").strip() if self.action == "list" else ""
        if query:
            queryset = queryset.filter(
                Q(name__icontains=query) | Q(original_filename__icontains=query)
            )
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
                "analysisMode": data["analysisMode"],
                "matrixDesign": data.get("matrixDesign"),
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
        query = self.request.query_params.get("q", "").strip() if self.action == "list" else ""
        if query:
            queryset = queryset.filter(
                Q(title__icontains=query)
                | Q(deidentified_text__icontains=query)
                | Q(structured_data__diagnosis__icontains=query)
            )
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

    @action(detail=True, methods=["get", "post"], url_path="analysis")
    def analysis(self, request, pk=None):
        case = self.get_object()
        if request.method == "GET":
            task = AnalysisTask.objects.filter(
                medical_case=case,
                task_type=AnalysisTask.TaskType.CASE_LINK,
            ).first()
            from ..services.case_analysis import case_input_sha256, case_model_configuration

            candidates = (
                MedicalCaseCandidate.objects.filter(task=task)
                .select_related("entity", "reviewed_by")
                .order_by("candidate_type", "rank", "pk")
                if task
                else MedicalCaseCandidate.objects.none()
            )
            return Response({
                "task": AnalysisTaskSerializer(task).data if task else None,
                "candidates": MedicalCaseCandidateSerializer(candidates, many=True).data,
                "stale": bool(task and task.input_parameters.get("caseContentSha256") != case_input_sha256(case)),
                "modelConfiguration": case_model_configuration(),
            })

        serializer = CaseAnalysisRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from ..services.case_analysis import case_input_sha256, case_model_configuration
        from ..services.case_audit import create_case_audit_event

        if not case_model_configuration()["configured"]:
            raise ValidationError({"model": "平台尚未配置受信任的本地模型地址、名称和实际版本。"})

        with transaction.atomic():
            case = MedicalCase.objects.select_for_update().get(pk=case.pk)
            active_task = AnalysisTask.objects.filter(
                medical_case=case,
                task_type=AnalysisTask.TaskType.CASE_LINK,
                status__in=[AnalysisTask.Status.QUEUED, AnalysisTask.Status.RUNNING],
            ).first()
            if active_task:
                return Response(AnalysisTaskSerializer(active_task).data, status=status.HTTP_202_ACCEPTED)
            from apps.case_rag.services import build_case_snapshot
            from ..services.case_analysis import case_input_payload
            corpus_snapshot = build_case_snapshot(" ".join(case_input_payload(case).values()))
            task = AnalysisTask.objects.create(
                owner=case.owner,
                created_by=request.user,
                task_type=AnalysisTask.TaskType.CASE_LINK,
                status=AnalysisTask.Status.QUEUED,
                medical_case=case,
                input_parameters={
                    "analysisKind": "case_analysis",
                    "caseContentSha256": case_input_sha256(case),
                    "caseCorpusSnapshot": corpus_snapshot,
                    "localModelConsent": True,
                    "modelName": settings.CASE_MODEL_NAME,
                    "modelVersion": settings.CASE_MODEL_VERSION,
                },
            )
            create_case_audit_event(
                case=case,
                actor=request.user,
                action=MedicalCaseAuditEvent.Action.ANALYSIS_REQUESTED,
                metadata={
                    "analysisTaskId": task.pk,
                    "localModelConsent": True,
                    "modelName": settings.CASE_MODEL_NAME,
                    "modelVersion": settings.CASE_MODEL_VERSION,
                },
            )
        try:
            from ..tasks import run_case_analysis_task

            run_case_analysis_task.apply_async(args=[task.pk])
        except Exception as exc:
            task.status = AnalysisTask.Status.FAILED
            task.progress = 100
            task.error_summary = "医案分析任务队列暂不可用，请稍后重试。"
            task.finished_at = timezone.now()
            task.save(update_fields=["status", "progress", "error_summary", "finished_at"])
            raise TaskQueueUnavailable() from exc
        return Response(AnalysisTaskSerializer(task).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(parameters=[OpenApiParameter("candidate_id", OpenApiTypes.INT, OpenApiParameter.PATH)])
    @action(
        detail=True,
        methods=["post"],
        url_path=r"candidates/(?P<candidate_id>[^/.]+)/review",
    )
    def review_candidate(self, request, pk=None, candidate_id=None):
        case = self.get_object()
        serializer = CaseCandidateReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            candidate = MedicalCaseCandidate.objects.select_related("task", "entity").get(
                pk=candidate_id,
                medical_case=case,
                task__owner=case.owner,
                task__medical_case=case,
            )
        except MedicalCaseCandidate.DoesNotExist as exc:
            raise NotFound("没有找到当前医案中的分析候选。") from exc
        if candidate.task.status != AnalysisTask.Status.SUCCEEDED:
            raise ValidationError({"candidate": "分析任务尚未完成，不能审核候选。"})
        decision = serializer.validated_data["decision"]
        from ..services.case_analysis import case_input_sha256, refresh_case_analysis_result
        from ..services.case_audit import create_case_audit_event

        with transaction.atomic():
            # Serialize edits and confirmations against the case row so a concurrent edit
            # cannot slip between the stale-content check and accepting the candidate.
            case = MedicalCase.objects.select_for_update().get(pk=case.pk)
            candidate = MedicalCaseCandidate.objects.select_for_update().get(
                pk=candidate.pk,
                medical_case=case,
            )
            candidate.task = AnalysisTask.objects.get(pk=candidate.task_id)
            if candidate.task.medical_case_id != case.pk or candidate.task.owner_id != case.owner_id:
                raise NotFound("没有找到当前医案中的分析候选。")
            if candidate.task.status != AnalysisTask.Status.SUCCEEDED:
                raise ValidationError({"candidate": "分析任务尚未完成，不能审核候选。"})
            if decision == "accept" and candidate.task.input_parameters.get("caseContentSha256") != case_input_sha256(case):
                raise ValidationError({"candidate": "分析后医案内容已修改；请重新分析后再确认候选。"})
            if decision == "accept" and not candidate.entity_id:
                raise ValidationError({"candidate": "该名称无法唯一关联本地规范实体，不能加入下游证据链。"})
            before = {
                f"candidate_{candidate.pk}_review_status": candidate.review_status,
                f"candidate_{candidate.pk}_reviewed_by_id": candidate.reviewed_by_id,
            }
            candidate.review_status = (
                MedicalCaseCandidate.ReviewStatus.ACCEPTED
                if decision == "accept"
                else MedicalCaseCandidate.ReviewStatus.REJECTED
            )
            candidate.review_note = serializer.validated_data.get("note", "")
            candidate.reviewed_by = request.user
            candidate.reviewed_at = timezone.now()
            candidate.save(update_fields=["review_status", "review_note", "reviewed_by", "reviewed_at"])
            create_case_audit_event(
                case=case,
                actor=request.user,
                action=MedicalCaseAuditEvent.Action.CANDIDATE_REVIEWED,
                before=before,
                after={
                    f"candidate_{candidate.pk}_review_status": candidate.review_status,
                    f"candidate_{candidate.pk}_reviewed_by_id": candidate.reviewed_by_id,
                },
                metadata={
                    "analysisTaskId": candidate.task_id,
                    "candidateId": candidate.pk,
                    "candidateType": candidate.candidate_type,
                    "entityStableId": candidate.entity.stable_id if candidate.entity_id else None,
                    "decision": decision,
                },
            )
            refresh_case_analysis_result(candidate.task)
        candidate.refresh_from_db()
        return Response(MedicalCaseCandidateSerializer(candidate).data)


class AnalysisTaskViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AnalysisTask.objects.none()
    serializer_class = AnalysisTaskSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['parent_task', 'task_type', 'status']

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
        if task.task_type == AnalysisTask.TaskType.TEXT_ANALYSIS:
            if task.status != AnalysisTask.Status.SUCCEEDED:
                raise NotFound("该分析任务尚无可导出的规则分析结果。")
            export_format = request.query_params.get("file_format", "csv").lower()
            if export_format not in {"csv", "pdf"}:
                raise ValidationError({"file_format": "规则分析结果仅支持 csv 或 pdf。"})
            from ..services.text_analysis_exports import export_text_analysis_csv, export_text_analysis_pdf

            content = export_text_analysis_csv(task) if export_format == "csv" else export_text_analysis_pdf(task)
            content_type = "text/csv; charset=utf-8" if export_format == "csv" else "application/pdf"
            response = HttpResponse(content, content_type=content_type)
            response["Content-Disposition"] = f'attachment; filename="text-analysis-task-{task.pk}.{export_format}"'
            response["X-Content-Type-Options"] = "nosniff"
            return response
        if task.task_type != AnalysisTask.TaskType.PROTEOMICS or task.status != AnalysisTask.Status.SUCCEEDED:
            raise NotFound("该分析任务没有可导出的蛋白组学结果。")
        export_format = request.query_params.get("file_format", "csv").lower()
        if export_format not in {"csv", "xlsx", "pdf"}:
            raise ValidationError({"file_format": "仅支持 csv、xlsx 或 pdf。"})

        from apps.proteomics.exports import (
            export_proteomics_csv,
            export_proteomics_xlsx,
            export_proteomics_pdf,
            rows_for_task,
        )

        rows = rows_for_task(task)
        if export_format == "csv":
            content = export_proteomics_csv(rows)
            content_type = "text/csv; charset=utf-8"
        elif export_format == "xlsx":
            content = export_proteomics_xlsx(task, rows)
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            content = export_proteomics_pdf(task, rows)
            content_type = "application/pdf"
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="proteomics-task-{task.pk}.{export_format}"'
        response["X-Content-Type-Options"] = "nosniff"
        return response


class ResearchAssistantView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ResearchAssistantRequestSerializer, responses=AnalysisTaskSerializer)
    def post(self, request):
        serializer = ResearchAssistantRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        from ..services.research_assistant import (
            ASSISTANT_ALGORITHM_VERSION,
            ResearchAssistantError,
            build_evidence_snapshot,
        )
        if data["useModel"]:
            from ..services.case_analysis import case_model_configuration
            if not case_model_configuration()["configured"]:
                raise ValidationError({"model": "本机/内网模型尚未配置，取消模型选项后仍可检索参考医案。"})

        try:
            evidence, source_release_ids = build_evidence_snapshot(data["entityIds"], data["question"], data["caseIds"], data["caseCategory"])
        except ResearchAssistantError as exc:
            raise ValidationError({"entityIds": str(exc)}) from exc

        task = AnalysisTask.objects.create(
            owner=request.user,
            created_by=request.user,
            task_type=AnalysisTask.TaskType.RESEARCH_ASSISTANT,
            status=AnalysisTask.Status.QUEUED,
            input_parameters={
                "analysisKind": "research_assistant",
                "algorithmVersion": ASSISTANT_ALGORITHM_VERSION,
                "question": data["question"],
                "entityIds": data["entityIds"],
                "caseIds": data["caseIds"],
                "caseCategory": data["caseCategory"],
                "evidenceSnapshot": evidence,
                "useModel": data["useModel"],
                "modelConsentRecorded": data["useModel"] and data["confirmModelSharing"],
                "modelName": settings.CASE_MODEL_NAME if data["useModel"] else None,
                "modelVersion": settings.CASE_MODEL_VERSION if data["useModel"] else None,
            },
        )
        task.source_releases.set(source_release_ids)
        try:
            from ..tasks import run_research_assistant_task

            run_research_assistant_task.apply_async(args=[task.pk])
        except Exception as exc:
            task.status = AnalysisTask.Status.FAILED
            task.progress = 100
            task.error_summary = "科研助手任务队列暂不可用，请稍后重试。"
            task.finished_at = timezone.now()
            task.save(update_fields=["status", "progress", "error_summary", "finished_at"])
            raise TaskQueueUnavailable() from exc
        return Response(AnalysisTaskSerializer(task).data, status=status.HTTP_202_ACCEPTED)


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
        inline = (
            request.query_params.get("inline") == "1"
            and artifact.file_format in {"svg", "png", "html"}
        )
        response = FileResponse(
            default_storage.open(artifact.storage_key, "rb"),
            as_attachment=not inline,
            filename=artifact.filename,
            content_type=artifact.mime_type,
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        # HTML widgets execute only inside an opaque sandbox. Never grant same-origin,
        # network access, parent navigation, forms, or popups to an uploaded label.
        response["Content-Security-Policy"] = (
            "sandbox allow-scripts allow-downloads; default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; base-uri 'none'; form-action 'none'"
            if artifact.file_format == "html" else "sandbox"
        )
        if inline and artifact.file_format == "html":
            # Permit only our own authenticated page to embed the opaque widget.
            # Otherwise Django's default DENY also blocks the intended iframe.
            response["X-Frame-Options"] = "SAMEORIGIN"
            response["Content-Security-Policy"] += "; frame-ancestors 'self'"
        return response
