from uuid import uuid4

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
    SQLiteSourceCreateSerializer,
    SQLiteSourceTestResponseSerializer,
)
from apps.sources.connectors.sqlite_tcm import SQLiteSourceError, inspect_sqlite_source
from apps.sources.services import (
    PUBCHEM_CONNECTOR,
    REACTOME_CONNECTOR,
    REACTOME_SOURCE_SLUG,
    STRING_CONNECTOR,
    UNIPROT_CONNECTOR,
    enqueue_sync_run,
)
from apps.sources.sqlite_sync import SQLITE_CONNECTOR


class IsPlatformAdministrator(permissions.BasePermission):
    message = "只有平台超级管理员可以查看或执行数据源同步。"

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class DataSourceListView(generics.ListCreateAPIView):
    permission_classes = [IsPlatformAdministrator]
    serializer_class = DataSourceSyncSerializer

    def get_serializer_class(self):
        return SQLiteSourceCreateSerializer if self.request.method == "POST" else self.serializer_class

    def get_queryset(self):
        latest_runs = SyncRun.objects.filter(source_id=OuterRef("pk")).order_by("-created_at")
        return DataSource.objects.annotate(
            latest_run_status=Subquery(latest_runs.values("status")[:1]),
            latest_run_at=Subquery(latest_runs.values("created_at")[:1]),
        )

    @extend_schema(request=SQLiteSourceCreateSerializer, responses={201: DataSourceSyncSerializer})
    def post(self, request, *args, **kwargs):
        serializer = SQLiteSourceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        source = DataSource.objects.create(
            slug=f"sqlite-{uuid4().hex[:12]}",
            name=data["name"],
            description=data.get("description", ""),
            access_mode=DataSource.AccessMode.DOWNLOAD,
            configuration={
                "connector": SQLITE_CONNECTOR,
                **{key: value for key, value in data.items() if key != "name" and key != "description" and value},
            },
            license_note="管理员登记的本地 SQLite 来源。请确保源数据具有使用授权；目录与文件名相对于服务器 SQLITE_SOURCE_ROOT。",
        )
        response_data = DataSourceSyncSerializer(source).data
        return Response(response_data, status=status.HTTP_201_CREATED)


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


class SourceSyncPreviewView(APIView):
    permission_classes = [IsPlatformAdministrator]
    serializer_class = SyncPreviewResponseSerializer

    @extend_schema(request=SyncPreviewRequestSerializer, responses={202: SyncPreviewResponseSerializer})
    def post(self, request, source_id: int):
        try:
            source = DataSource.objects.get(pk=source_id)
        except DataSource.DoesNotExist as exc:
            raise NotFound("找不到指定的数据源。") from exc
        connector = (source.configuration or {}).get("connector") or (
            REACTOME_CONNECTOR if source.slug == REACTOME_SOURCE_SLUG else
            STRING_CONNECTOR if source.slug == "string" else ""
        )
        if connector not in {REACTOME_CONNECTOR, SQLITE_CONNECTOR, UNIPROT_CONNECTOR, PUBCHEM_CONNECTOR, STRING_CONNECTOR}:
            raise ValidationError("当前版本不支持该数据源的同步连接器。")
        if not source.enabled:
            raise ValidationError("该数据源已停用，不能执行同步。")
        serializer = SyncPreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = SyncRun.objects.create(
            source=source,
            requested_by=request.user,
            preview_summary={"mode": "preview", "connector": connector},
        )
        enqueue_sync_run(run)
        return Response({"run": SyncRunSerializer(run).data}, status=status.HTTP_202_ACCEPTED)


class SourceSyncApplyView(APIView):
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
            connector = (preview.preview_summary or {}).get("connector") or (
                REACTOME_CONNECTOR if preview.source.slug == REACTOME_SOURCE_SLUG else
                STRING_CONNECTOR if preview.source.slug == "string" else ""
            )
            if connector not in {REACTOME_CONNECTOR, SQLITE_CONNECTOR, UNIPROT_CONNECTOR, PUBCHEM_CONNECTOR, STRING_CONNECTOR} or not preview.release_id or not preview.cursor:
                raise ValidationError("预览记录缺少可应用的来源版本信息。")
            if not preview.source.enabled:
                raise ValidationError("该数据源已停用，不能执行同步。")
            if SyncRun.objects.filter(preview_summary__basedOn=preview.pk).exclude(
                status=SyncRun.Status.FAILED
            ).exists():
                raise ValidationError("该预览已有待处理或成功的应用任务，请查看同步历史。")

            run = SyncRun.objects.create(
                source=preview.source,
                release=preview.release,
                records_seen=preview.records_seen,
                requested_by=request.user,
                cursor=preview.cursor,
                preview_summary={
                    **(preview.preview_summary or {}),
                    "mode": "apply",
                    "basedOn": preview.pk,
                },
            )
        enqueue_sync_run(run)
        return Response({"run": SyncRunSerializer(run).data}, status=status.HTTP_202_ACCEPTED)


class SQLiteSourceTestView(APIView):
    permission_classes = [IsPlatformAdministrator]
    serializer_class = SQLiteSourceTestResponseSerializer

    @extend_schema(responses={200: SQLiteSourceTestResponseSerializer})
    def post(self, request, source_id: int):
        try:
            source = DataSource.objects.get(pk=source_id)
        except DataSource.DoesNotExist as exc:
            raise NotFound("找不到指定的数据源。") from exc
        if (source.configuration or {}).get("connector") != SQLITE_CONNECTOR:
            raise ValidationError("该数据源不是 SQLite 中药—成分—靶点连接器。")
        if not source.enabled:
            raise ValidationError("该数据源已停用，不能测试连接。")
        try:
            snapshot = inspect_sqlite_source(source.configuration)
        except SQLiteSourceError as exc:
            raise ValidationError(str(exc)) from exc
        return Response({
            "ok": True,
            "rowCount": snapshot.row_count,
            "fileBytes": snapshot.file_size,
            "checksumSha256": snapshot.checksum_sha256,
            "columns": snapshot.columns,
            "tableRowCounts": snapshot.table_row_counts,
            "mapping": {
                "table": source.configuration["table"],
                "herbColumn": source.configuration["herbColumn"],
                "compoundColumn": source.configuration["compoundColumn"],
                "targetColumn": source.configuration["targetColumn"],
            },
        })
