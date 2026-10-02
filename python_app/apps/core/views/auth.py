"""Session-based authentication endpoints for the React client."""

from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, trim_whitespace=False)


@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def csrf_token(request):
    return Response({"csrfToken": get_token(request)})


@api_view(["GET", "POST", "DELETE"])
@permission_classes([AllowAny])
def session(request):
    if request.method == "GET":
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

    if request.method == "DELETE":
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    credentials = LoginSerializer(data=request.data)
    credentials.is_valid(raise_exception=True)
    user = authenticate(request, **credentials.validated_data)
    if user is None:
        raise AuthenticationFailed("用户名或密码不正确。", code="invalid_credentials")
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


# DRF marks API views csrf_exempt because it normally performs CSRF checks only
# for authenticated SessionAuthentication requests. Login must also be protected.
session.csrf_exempt = False
csrf_token.csrf_exempt = False
