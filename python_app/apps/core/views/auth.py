"""Session-based authentication endpoints for the React client."""

from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class CsrfTokenSerializer(serializers.Serializer):
    csrfToken = serializers.CharField()


class SessionUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    isSuperuser = serializers.BooleanField()


class SessionSerializer(serializers.Serializer):
    authenticated = serializers.BooleanField()
    user = SessionUserSerializer(required=False)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfTokenView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=CsrfTokenSerializer)
    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class SessionView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=SessionSerializer)
    def get(self, request):
        if not request.user.is_authenticated:
            return Response({"authenticated": False})
        return Response(
            {
                "authenticated": True,
                "user": {
                    "id": request.user.pk,
                    "username": request.user.get_username(),
                    "isSuperuser": request.user.is_superuser,
                },
            }
        )

    @extend_schema(request=LoginSerializer, responses=SessionSerializer)
    def post(self, request):
        credentials = LoginSerializer(data=request.data)
        credentials.is_valid(raise_exception=True)
        user = authenticate(request, **credentials.validated_data)
        if user is None:
            raise AuthenticationFailed("Invalid username or password.", code="invalid_credentials")
        login(request, user)
        return Response(
            {
                "authenticated": True,
                "user": {
                    "id": user.pk,
                    "username": user.get_username(),
                    "isSuperuser": user.is_superuser,
                },
            }
        )

    @extend_schema(responses={204: None})
    def delete(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)
