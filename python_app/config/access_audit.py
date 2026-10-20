"""Do not release sensitive responses when their access evidence cannot persist."""

import logging

from django.db import DatabaseError
from django.http import HttpResponse
from django.utils.cache import patch_cache_control, patch_vary_headers

from apps.core.models import SensitiveAccessEvent
from config.api_errors import api_json_error, request_id_for


logger = logging.getLogger(__name__)


def close_withheld_file(response):
    # HttpResponse.close() also emits request_finished. Calling it here would
    # close database connections before the replacement response is returned.
    file_object = getattr(response, "file_to_stream", None)
    if file_object is not None:
        file_object.close()


class SensitiveAccessAuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        evidence = getattr(request, "sensitive_access", None)
        if not evidence or request.method not in {"GET", "HEAD"} or not 200 <= response.status_code < 300:
            return response
        if not request.user.is_authenticated:
            close_withheld_file(response)
            return api_json_error(request, code="AUTHENTICATION_REQUIRED", message="请先登录后再操作。", status_code=401)
        request_id = request_id_for(request)
        try:
            SensitiveAccessEvent.objects.create(
                actor=request.user, channel="admin" if request.path.startswith("/django-admin/") else "api",
                method=request.method, status_code=response.status_code, request_id=request_id, **evidence,
            )
        except DatabaseError as exc:
            logger.error("Sensitive access audit unavailable request_id=%s type=%s", request_id, type(exc).__name__)
            close_withheld_file(response)
            if request.path.startswith("/api/"):
                response = api_json_error(request, code="ACCESS_AUDIT_UNAVAILABLE", message="访问记录暂时无法保存，请稍后重试。", status_code=503)
            else:
                response = HttpResponse("访问记录暂时无法保存，请稍后重试。", status=503, content_type="text/plain; charset=utf-8")
        patch_cache_control(response, private=True, no_store=True)
        patch_vary_headers(response, ["Cookie"])
        response["X-Request-ID"] = request_id
        return response
