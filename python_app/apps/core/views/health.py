from django.db import DatabaseError, connection
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import APIException
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class DatabaseUnavailable(APIException):
    status_code = 503
    default_detail = "Database is temporarily unavailable."
    default_code = "service_unavailable"


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()
    database = serializers.CharField()
    api_version = serializers.CharField()


class HealthView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=HealthSerializer)
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except DatabaseError as exc:
            raise DatabaseUnavailable() from exc
        return Response({"status": "ok", "database": "ok", "api_version": "v1"})
