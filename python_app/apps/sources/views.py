from uuid import uuid4
import json

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.db.models.deletion import ProtectedError
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.core.models import DataSource, SyncRun
from config.api_errors import error_payload
from apps.sources.serializers import (
    DataSourceSyncSerializer,
    DataSourceSettingsSerializer,
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
        latest_runs = SyncRun.objects.filter(source_id=OuterRef("pk")).order_by("-created_at", "-id")
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


class DataSourceDeleteView(APIView):
    permission_classes = [IsPlatformAdministrator]

    @extend_schema(request=DataSourceSettingsSerializer, responses=DataSourceSyncSerializer)
    def patch(self, request, source_id: int):
        serializer = DataSourceSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            try:
                source = DataSource.objects.select_for_update().get(pk=source_id)
            except DataSource.DoesNotExist as exc:
                raise NotFound("找不到指定的数据源。") from exc
            before = {field: getattr(source, field) for field in serializer.validated_data}
            for field, value in serializer.validated_data.items():
                setattr(source, field, value)
            source.save(update_fields=[*serializer.validated_data, "updated_at"])
            LogEntry.objects.create(
                user_id=request.user.pk, content_type=ContentType.objects.get_for_model(DataSource),
                object_id=str(source.pk), object_repr=str(source), action_flag=CHANGE,
                change_message=json.dumps([{
                    "changed": {"fields": list(serializer.validated_data)},
                    "before": before, "after": dict(serializer.validated_data),
                }], ensure_ascii=False),
            )
        return Response(DataSourceSyncSerializer(source).data)

    @extend_schema(responses={204: None, 409: OpenApiTypes.OBJECT})
    def delete(self, request, source_id: int):
        try:
            with transaction.atomic():
                try:
                    source = DataSource.objects.select_for_update().get(pk=source_id)
                except DataSource.DoesNotExist as exc:
                    raise NotFound("找不到指定的数据源。") from exc
                if source.releases.exists() or source.sync_runs.exists():
                    return self._conflict_response(request, source_id)
                source.delete()
        except ProtectedError:
            return self._conflict_response(request, source_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _conflict_response(request, source_id):
        return Response(
            error_payload(
                "RESOURCE_CONFLICT",
                "该数据源已有来源版本或同步历史，为保留数据溯源不能删除。",
                {"sourceId": source_id},
                request=request,
            ),
            status=status.HTTP_409_CONFLICT,
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


class SourceSyncPreviewView(APIView):
    permission_classes = [IsPlatformAdministrator]
    serializer_class = SyncPreviewResponseSerializer

    @extend_schema(request=SyncPreviewRequestSerializer, responses={202: SyncPreviewResponseSerializer})
    def post(self, request, source_id: int):
        serializer = SyncPreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            try:
                source = DataSource.objects.select_for_update().get(pk=source_id)
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
            if source.sync_runs.filter(status__in=[SyncRun.Status.PENDING, SyncRun.Status.RUNNING]).exists():
                return active_sync_conflict(request, source.pk)
            run = SyncRun.objects.create(
                source=source, requested_by=request.user,
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
            # Lock source first, matching the scheduler and manual preview lock order.
            source_id = SyncRun.objects.filter(pk=run_id).values_list("source_id", flat=True).first()
            if source_id is None:
                raise NotFound("找不到指定的预览记录。")
            source = DataSource.objects.select_for_update().get(pk=source_id)
            try:
                preview = SyncRun.objects.select_related("source", "release").get(pk=run_id)
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
            if not source.enabled:
                raise ValidationError("该数据源已停用，不能执行同步。")
            if connector == UNIPROT_CONNECTOR:
                summary = preview.preview_summary or {}
                if not summary.get("identityPlanSha256"):
                    raise ValidationError("这份 UniProt 旧预览缺少身份核对依据，请重新预览。")
                if summary.get("identifierConflicts", 0):
                    raise ValidationError("UniProt 已有编号存在归属冲突，请先核对物种与符号，再重新预览。")
            if SyncRun.objects.filter(preview_summary__basedOn=preview.pk).exclude(
                status=SyncRun.Status.FAILED
            ).exists():
                raise ValidationError("该预览已有待处理或成功的应用任务，请查看同步历史。")

            if source.sync_runs.filter(status__in=[SyncRun.Status.PENDING, SyncRun.Status.RUNNING]).exists():
                return active_sync_conflict(request, source.pk)

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


def active_sync_conflict(request, source_id):
    return Response(error_payload(
        "SOURCE_SYNC_ACTIVE", "该数据源已有排队或运行中的同步任务，请等待完成后重试。",
        {"sourceId": source_id}, request=request,
    ), status=status.HTTP_409_CONFLICT)


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
