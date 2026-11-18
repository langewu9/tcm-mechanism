"""Private workbook-to-count snapshot endpoint for the case visualization page."""

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import AnalysisTask
from ..serializers import AnalysisTaskSerializer
from ..services.case_statistics import CaseWorkbookError, summarize_case_workbook


class CaseStatisticsView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        task_id = request.query_params.get("task")
        tasks = AnalysisTask.objects.filter(
            owner=request.user,
            task_type=AnalysisTask.TaskType.CASE_STATISTICS,
            status=AnalysisTask.Status.SUCCEEDED,
        ).order_by("-created_at", "-id")
        if task_id:
            task = tasks.filter(pk=task_id).first()
            if task is None:
                return Response({"detail": "未找到此医案分析数据。"}, status=status.HTTP_404_NOT_FOUND)
            return Response(AnalysisTaskSerializer(task).data)
        return Response({"results": AnalysisTaskSerializer(tasks[:10], many=True).data})

    def post(self, request):
        upload = request.FILES.get("file")
        unit = request.data.get("unit", "first_visit")
        if upload is None:
            return Response({"file": "请选择 Excel 工作簿。"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            summary = summarize_case_workbook(upload, unit)
        except CaseWorkbookError as exc:
            return Response({"file": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # Store only counts and anonymous feature matrices for local analysis.
        # Workbook bytes, patient identity and narrative text are discarded.
        with transaction.atomic():
            previous = AnalysisTask.objects.filter(
                owner=request.user,
                task_type=AnalysisTask.TaskType.CASE_STATISTICS,
                input_parameters__fileSha256=summary["fileSha256"],
                input_parameters__unit=unit,
                input_parameters__adapterVersion=summary["adapterVersion"],
                status=AnalysisTask.Status.SUCCEEDED,
            ).first()
            if previous:
                return Response(AnalysisTaskSerializer(previous).data, status=status.HTTP_200_OK)
            now = timezone.now()
            task = AnalysisTask.objects.create(
                owner=request.user,
                created_by=request.user,
                task_type=AnalysisTask.TaskType.CASE_STATISTICS,
                status=AnalysisTask.Status.SUCCEEDED,
                progress=100,
                input_parameters={
                    "analysisKind": "case_statistics",
                    "name": "医案数据分析",
                    "unit": unit,
                    "adapterVersion": summary["adapterVersion"],
                    "fileSha256": summary["fileSha256"],
                },
                result=summary,
                started_at=now,
                finished_at=now,
            )
        return Response(AnalysisTaskSerializer(task).data, status=status.HTTP_201_CREATED)
