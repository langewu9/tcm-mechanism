"""The existing main free-text analysis workbench, served by Django."""

from itertools import chain
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import AnalysisTask, MedicalCase
from apps.core.serializers import AnalysisTaskSerializer
from apps.core.services.text_analysis import create_text_analysis
from apps.core.services.access_audit import mark_sensitive_access


class TextAnalysisRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, default="中医药理分析任务")
    query = serializers.CharField(max_length=20000)
    caseId = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)


class AnalysisCaseOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()


class TextAnalysisWorkspaceSerializer(serializers.Serializer):
    tasks = AnalysisTaskSerializer(many=True)
    cases = AnalysisCaseOptionSerializer(many=True)
    casesTruncated = serializers.BooleanField()


class TextAnalysisView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=TextAnalysisWorkspaceSerializer)
    def get(self, request):
        scope = {} if request.user.is_superuser else {"owner": request.user}
        cases = list(MedicalCase.objects.filter(archived_at__isnull=True, **scope).order_by("-created_at", "-id")[:201])
        tasks = AnalysisTask.objects.filter(
            task_type=AnalysisTask.TaskType.TEXT_ANALYSIS, **scope,
        ).select_related("owner", "created_by").order_by("-created_at", "-id")[:8]
        response = Response(TextAnalysisWorkspaceSerializer({
            "tasks": tasks, "cases": cases[:200], "casesTruncated": len(cases) > 200,
        }).data)
        mark_sensitive_access(request, operation="text_workspace.view", action="view", resources=chain(tasks, cases[:200]))
        return response

    @extend_schema(request=TextAnalysisRequestSerializer, responses={201: AnalysisTaskSerializer})
    @transaction.atomic
    def post(self, request):
        serializer = TextAnalysisRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        medical_case = None
        if data["caseId"]:
            cases = MedicalCase.objects.select_for_update().select_related("owner").filter(archived_at__isnull=True)
            if not request.user.is_superuser:
                cases = cases.filter(owner=request.user)
            medical_case = cases.filter(pk=data["caseId"]).first()
            if not medical_case:
                raise NotFound("医案不存在或当前账号无权访问。")
        task = create_text_analysis(
            user=request.user, name=data["name"], query=data["query"], medical_case=medical_case,
        )
        return Response(AnalysisTaskSerializer(task).data, status=status.HTTP_201_CREATED)
