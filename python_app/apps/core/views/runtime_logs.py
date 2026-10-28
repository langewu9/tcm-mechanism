"""Superuser-only access to recent sanitized diagnostic events."""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsPlatformMaintenanceAdministrator
from apps.core.services.access_audit import mark_sensitive_access
from config.runtime_logs import RuntimeLogUnavailable, query_runtime_events


class RuntimeLogQuerySerializer(serializers.Serializer):
    request_id = serializers.UUIDField(required=False)
    task_id = serializers.IntegerField(required=False, min_value=1, max_value=9223372036854775807)
    level = serializers.ChoiceField(required=False, choices=["warning", "error"])
    since = serializers.DateTimeField(required=False)
    limit = serializers.IntegerField(required=False, default=50, min_value=1, max_value=100)


class RuntimeLogFrameSerializer(serializers.Serializer):
    module = serializers.CharField()
    function = serializers.CharField()
    line = serializers.IntegerField()


class RuntimeLogEntrySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    createdAt = serializers.DateTimeField()
    event = serializers.CharField()
    level = serializers.CharField()
    message = serializers.CharField()
    requestId = serializers.UUIDField(allow_null=True)
    taskId = serializers.IntegerField(allow_null=True)
    operation = serializers.CharField(allow_null=True)
    method = serializers.CharField(allow_null=True)
    statusCode = serializers.IntegerField(allow_null=True)
    exceptionType = serializers.CharField(allow_null=True)
    frames = RuntimeLogFrameSerializer(many=True)


class RuntimeLogResponseSerializer(serializers.Serializer):
    results = RuntimeLogEntrySerializer(many=True)
    limit = serializers.IntegerField()
    hasMore = serializers.BooleanField()
    scanTruncated = serializers.BooleanField()
    skippedRecords = serializers.IntegerField()


class RuntimeLogReadUnavailable(APIException):
    status_code = 503
    default_detail = "运行日志暂时无法读取，请联系服务器维护人员。"


class RuntimeLogView(APIView):
    permission_classes = [IsPlatformMaintenanceAdministrator]
    renderer_classes = [JSONRenderer]
    http_method_names = ["get", "head", "options"]

    @extend_schema(
        parameters=[RuntimeLogQuerySerializer], responses=RuntimeLogResponseSerializer,
        description="仅管理后台超级管理员可用。查询近期脱敏异常，不读取任意文件，不包含原始异常消息或研究数据。最多扫描最近 1 MiB，返回最多 100 条；scanTruncated 表示查询窗口以外仍可能有记录。",
    )
    def get(self, request):
        query = RuntimeLogQuerySerializer(data=request.query_params)
        if set(request.query_params) - set(query.fields) or any(len(values) != 1 for _, values in request.query_params.lists()):
            raise ValidationError("仅支持已登记的筛选参数，且不能重复传入。")
        query.is_valid(raise_exception=True)
        try:
            payload = query_runtime_events(**query.validated_data)
        except RuntimeLogUnavailable:
            raise RuntimeLogReadUnavailable() from None
        mark_sensitive_access(request, operation="runtime_logs.query", action="view", resources=[])
        return Response(payload)
