"""Bound API JSON even when there is no trustworthy Content-Length header."""
from io import BytesIO

from django.conf import settings
from rest_framework.exceptions import APIException, ParseError
from rest_framework.parsers import JSONParser


class PayloadTooLarge(APIException):
    status_code = 413
    default_detail = "请求内容超过允许大小，请缩小数据后重试。"
    default_code = "payload_too_large"


class BoundedJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        payload = stream.read(settings.DATA_UPLOAD_MAX_MEMORY_SIZE + 1)
        if len(payload) > settings.DATA_UPLOAD_MAX_MEMORY_SIZE:
            raise PayloadTooLarge()
        try:
            parsed = super().parse(BytesIO(payload), media_type, parser_context)
        except RecursionError as exc:
            raise ParseError("JSON 结构嵌套过深。") from exc
        pending = [(parsed, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 64:
                raise ParseError("JSON 结构嵌套不能超过 64 层。")
            if isinstance(item, dict):
                pending.extend((value, depth + 1) for value in item.values())
            elif isinstance(item, list):
                pending.extend((value, depth + 1) for value in item)
        return parsed
