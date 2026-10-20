"""Stable JSON error contract for all Django REST API failures."""

import json
import logging
import uuid

from django.conf import settings
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import Http404, JsonResponse
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.views.csrf import csrf_failure as default_csrf_failure
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


def request_id_for(request):
    return getattr(request, "request_id", None) or str(uuid.uuid4())


def error_payload(code, message, details=None, request=None):
    error = {"code": code, "message": message, "details": details}
    error["requestId"] = request_id_for(request) if request is not None else None
    return {"error": error}


def api_json_error(request, *, code, message, status_code, details=None):
    return JsonResponse(
        error_payload(code, message, details, request),
        status=status_code,
    )


def api_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    request = context.get("request")
    status_code = response.status_code
    error_map = {
        400: ("VALIDATION_ERROR", "提交的数据无效，请检查后重试。"),
        401: ("AUTHENTICATION_REQUIRED", "请先登录后再操作。"),
        403: ("PERMISSION_DENIED", "当前账号无权执行此操作。"),
        404: ("NOT_FOUND", "请求的资源不存在。"),
        405: ("METHOD_NOT_ALLOWED", "不支持此请求方法。"),
        409: ("RESOURCE_CONFLICT", "该记录已关联分析任务，不能删除或替换其原始内容。"),
        413: ("PAYLOAD_TOO_LARGE", "请求内容超过允许大小，请缩小数据后重试。"),
        429: ("RATE_LIMITED", "请求过于频繁，请稍后重试。"),
        503: ("SERVICE_UNAVAILABLE", "服务暂时不可用，请稍后重试。"),
    }
    exception_code = exc.get_codes() if hasattr(exc, "get_codes") else getattr(exc, "default_code", None)
    if not isinstance(exception_code, str):
        exception_code = getattr(getattr(exc, "detail", None), "code", None)
    if exception_code in {"invalid_credentials", "not_authenticated"}:
        response.status_code = 401
        status_code = 401
    code, message = error_map.get(status_code, ("API_ERROR", "请求未能完成。"))
    if exception_code == "invalid_credentials":
        code, message = "INVALID_CREDENTIALS", "用户名或密码不正确。"
    elif exception_code == "not_authenticated":
        code, message = "AUTHENTICATION_REQUIRED", "请先登录后再操作。"
    elif exception_code == "email_not_verified":
        code, message = "EMAIL_NOT_VERIFIED", "请先通过注册邮箱中的链接完成邮箱验证。"
    elif exception_code == "catalog_results_changed":
        code, message = "CATALOG_RESULTS_CHANGED", "目录数据已更新，请重新检索后再保存关系图。"
    elif exception_code == "upload_quota_exceeded":
        code, message = "UPLOAD_QUOTA_EXCEEDED", str(exc.detail)
        response.data = {"quota": exc.usage}
    elif status_code == 403 and str(getattr(exc, "detail", "")).startswith("CSRF Failed:"):
        code, message = "CSRF_FAILED", "请求校验失败，请刷新页面后重试。"
    response.data = error_payload(code, message, response.data, request)
    return response


class ApiErrorEnvelopeMiddleware:
    """Normalizes Django-level API 404/500 errors and adds a request ID."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = str(uuid.uuid4())
        if request.path.startswith("/api/"):
            try:
                length = int(request.META.get("CONTENT_LENGTH") or 0)
                if length < 0:
                    raise ValueError
            except ValueError:
                return self.process_response(request, api_json_error(
                    request, code="INVALID_REQUEST", message="请求长度无效。", status_code=400
                ))
            upload = request.method == "POST" and request.path == "/api/v1/research/datasets/"
            limit = (
                settings.DATASET_UPLOAD_MAX_BYTES + 1024 * 1024
                if upload else settings.DATA_UPLOAD_MAX_MEMORY_SIZE
            )
            if length > limit:
                return self.process_response(request, api_json_error(
                    request, code="PAYLOAD_TOO_LARGE",
                    message="请求内容超过允许大小，请缩小数据后重试。", status_code=413
                ))
        try:
            response = self.get_response(request)
        except Exception:
            if not request.path.startswith("/api/"):
                raise
            logger.exception("Unhandled API exception request_id=%s", request.request_id)
            response = api_json_error(
                request,
                code="INTERNAL_ERROR",
                message="服务器暂时无法处理请求，请稍后重试。",
                status_code=500,
            )
        return self.process_response(request, response)

    def process_exception(self, request, exception):
        if request.path.startswith("/api/"):
            if isinstance(exception, Http404):
                return api_json_error(request, code="NOT_FOUND", message="请求的资源不存在。", status_code=404)
            if isinstance(exception, PermissionDenied):
                return api_json_error(request, code="PERMISSION_DENIED", message="当前账号无权执行此操作。", status_code=403)
            if isinstance(exception, SuspiciousOperation):
                return api_json_error(request, code="INVALID_REQUEST", message="请求内容无效。", status_code=400)
            logger.error(
                "Unhandled API exception request_id=%s type=%s",
                request_id_for(request), type(exception).__name__,
            )
            return api_json_error(
                request, code="INTERNAL_ERROR",
                message="服务器暂时无法处理请求，请稍后重试。", status_code=500
            )

    def process_response(self, request, response):
        if request.path.startswith("/api/") and response.status_code >= 400 and not getattr(response, "streaming", False):
            try:
                payload = json.loads(response.content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                payload = None
            if response.status_code == 500 or not isinstance(payload, dict) or "error" not in payload:
                codes = {
                    400: ("INVALID_REQUEST", "请求内容无效。"),
                    403: ("PERMISSION_DENIED", "当前账号无权执行此操作。"),
                    404: ("NOT_FOUND", "请求的 API 地址不存在。"),
                    413: ("PAYLOAD_TOO_LARGE", "请求内容超过允许大小。"),
                    429: ("RATE_LIMITED", "请求过于频繁，请稍后重试。"),
                }
                code, message = codes.get(response.status_code, ("INTERNAL_ERROR", "服务器暂时无法处理请求，请稍后重试。"))
                original = response
                response = api_json_error(
                    request,
                    code=code, message=message, status_code=original.status_code,
                )
                for header in ("Retry-After", "Allow", "WWW-Authenticate"):
                    if header in original:
                        response[header] = original[header]
        if request.path.startswith("/api/"):
            patch_cache_control(response, private=True, no_store=True)
            patch_vary_headers(response, ["Cookie"])
        response["X-Request-ID"] = request.request_id
        return response

def csrf_failure(request, reason=""):
    if request.path.startswith("/api/"):
        response = api_json_error(
            request,
            code="CSRF_FAILED",
            message="请求校验失败，请刷新页面后重试。",
            status_code=403,
        )
        response["X-Request-ID"] = request_id_for(request)
        return response
    return default_csrf_failure(request, reason=reason)
