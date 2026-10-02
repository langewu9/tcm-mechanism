"""Stable JSON error contract for all Django REST API failures."""

import json
import logging
import uuid

from django.http import JsonResponse
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
        429: ("RATE_LIMITED", "请求过于频繁，请稍后重试。"),
        503: ("SERVICE_UNAVAILABLE", "服务暂时不可用，请稍后重试。"),
    }
    if getattr(exc, "default_code", None) in {"invalid_credentials", "not_authenticated"}:
        response.status_code = 401
        status_code = 401
    code, message = error_map.get(status_code, ("API_ERROR", "请求未能完成。"))
    if getattr(exc, "default_code", None) == "invalid_credentials":
        code, message = "INVALID_CREDENTIALS", "用户名或密码不正确。"
    elif getattr(exc, "default_code", None) == "not_authenticated":
        code, message = "AUTHENTICATION_REQUIRED", "请先登录后再操作。"
    response.data = error_payload(code, message, response.data, request)
    return response


class ApiErrorEnvelopeMiddleware:
    """Normalizes Django-level API 404/500 errors and adds a request ID."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = str(uuid.uuid4())
        response = self.get_response(request)
        return self.process_response(request, response)

    def process_response(self, request, response):
        if request.path.startswith("/api/") and response.status_code == 404:
            try:
                payload = json.loads(response.content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                payload = None
            if not isinstance(payload, dict) or "error" not in payload:
                response = api_json_error(
                    request,
                    code="NOT_FOUND",
                    message="请求的 API 地址不存在。",
                    status_code=404,
                )
        response["X-Request-ID"] = request.request_id
        return response

    def process_exception(self, request, exception):
        if not request.path.startswith("/api/"):
            return None
        logger.exception("Unhandled API exception request_id=%s", request.request_id)
        response = api_json_error(
            request,
            code="INTERNAL_ERROR",
            message="服务器暂时无法处理请求，请稍后重试。",
            status_code=500,
        )
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
