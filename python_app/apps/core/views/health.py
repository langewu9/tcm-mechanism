from django.db import DatabaseError, connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import APIException
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


class DatabaseUnavailable(APIException):
    status_code = 503
    default_detail = "Database is temporarily unavailable."
    default_code = "service_unavailable"


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError as exc:
        raise DatabaseUnavailable() from exc
    return Response({"status": "ok", "database": "ok", "api_version": "v1"})
