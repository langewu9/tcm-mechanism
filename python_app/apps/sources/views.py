from django.db import transaction
from django.db.models import OuterRef, Subquery
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import DataSource, SyncRun
from apps.sources.serializers import (
    DataSourceSyncSerializer,
    SyncApplyResponseSerializer,
    SyncPreviewRequestSerializer,
    SyncPreviewResponseSerializer,
    SyncRunSerializer,
)
from apps.sources.services import REACTOME_SOURCE_SLUG, enqueue_sync_run


class IsPlatformAdministrator(permissions.BasePermission):
    message = "只有平台超级管理员可以查看或执行数据源同步。"

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class DataSourceListView(generics.ListAPIView):
    permission_classes = [IsPlatformAdministrator]
    serializer_class = DataSourceSyncSerializer

    def get_queryset(self):
        latest_runs = SyncRun.objects.filter(source_id=OuterRef("pk")).order_by("-created_at")
        return DataSource.objects.annotate(
            latest_run_status=Subquery(latest_runs.values("status")[:1]),
            latest_run_at=Subquery(latest_runs.values("created_at")[:1]),
        )


class SyncRunListView(generics.ListAPIView):
    permission_classes = [IsPlatformAdministrator]
    serializer_class = SyncRunSerializer

    def get_queryset(self):
        queryset = SyncRun.objects.select_related("source", "release", "requested_by")
        source_id = self.request.query_params.get("sourceId")
        if source_id:
            if not source_id.isdecimal():
                raise ValidationError({"sourceId": "请提供有效的数据源编号。"})
            queryset = queryset.filter(source_id=int(source_id))
        return queryset


class ReactomePreviewView(APIView):
    permission_classes = [IsPlatformAdministrator]
    serializer_class = SyncPreviewResponseSerializer

    @extend_schema(request=SyncPreviewRequestSerializer, responses={202: SyncPreviewResponseSerializer})
    def post(self, request, source_id: int):
        try:
            source = DataSource.objects.get(pk=source_id)
        except DataSource.DoesNotExist as exc:
            raise NotFound("找不到指定的数据源。") from exc
        if source.slug != REACTOME_SOURCE_SLUG:
            raise ValidationError("当前版本只支持 Reactome 通路目录预览。")
        if not source.enabled:
            raise ValidationError("该数据源已停用，不能执行同步。")
        serializer = SyncPreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = SyncRun.objects.create(
            source=source,
            requested_by=request.user,
            preview_summary={"mode": "preview"},
        )
        enqueue_sync_run(run)
        return Response({"run": SyncRunSerializer(run).data}, status=status.HTTP_202_ACCEPTED)


class ReactomeApplyView(APIView):
    permission_classes = [IsPlatformAdministrator]
    serializer_class = SyncApplyResponseSerializer

    @extend_schema(responses={202: SyncApplyResponseSerializer})
    def post(self, request, run_id: int):
        with transaction.atomic():
            try:
                preview = SyncRun.objects.select_for_update().select_related("source", "release").get(pk=run_id)
            except SyncRun.DoesNotExist as exc:
                raise NotFound("找不到指定的预览记录。") from exc
            if preview.status != SyncRun.Status.SUCCEEDED or (preview.preview_summary or {}).get("mode") != "preview":
                raise ValidationError("只能应用已成功的目录预览。")
            if preview.source.slug != REACTOME_SOURCE_SLUG or not preview.release_id or not preview.cursor:
                raise ValidationError("预览记录缺少可应用的 Reactome 版本信息。")
            if not preview.source.enabled:
                raise ValidationError("该数据源已停用，不能执行同步。")
            if SyncRun.objects.filter(preview_summary__basedOn=preview.pk).exclude(
                status=SyncRun.Status.FAILED
            ).exists():
                raise ValidationError("该预览已有待处理或成功的应用任务，请查看同步历史。")

            run = SyncRun.objects.create(
                source=preview.source,
                release=preview.release,
                requested_by=request.user,
                cursor=preview.cursor,
                preview_summary={"mode": "apply", "basedOn": preview.pk},
            )
        enqueue_sync_run(run)
        return Response({"run": SyncRunSerializer(run).data}, status=status.HTTP_202_ACCEPTED)
