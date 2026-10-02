"""Session-based authentication endpoints for the React client."""

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.throttling import AnonRateThrottle
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class ResearcherRegistrationSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    password_confirmation = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_username(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("请输入用户名。")
        user_model = get_user_model()
        if user_model.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("该用户名已被使用。")
        try:
            for validator in user_model._meta.get_field("username").validators:
                validator(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return value

    def validate_email(self, value):
        email = value.strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("该邮箱已登记，请联系平台管理员。")
        return email

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirmation"]:
            raise serializers.ValidationError({"password_confirmation": "两次输入的密码不一致。"})
        candidate = get_user_model()(username=attrs["username"], email=attrs["email"])
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs

    def create(self, validated_data):
        user_model = get_user_model()
        validated_data.pop("password_confirmation")
        try:
            with transaction.atomic():
                return user_model.objects.create_user(
                    username=validated_data["username"],
                    email=validated_data["email"],
                    password=validated_data["password"],
                    is_active=False,
                    is_staff=False,
                    is_superuser=False,
                )
        except IntegrityError as exc:
            raise serializers.ValidationError({"username": "该用户名已被使用，请重新选择。"}) from exc


class CsrfTokenSerializer(serializers.Serializer):
    csrfToken = serializers.CharField()


class RegistrationResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["pending_approval"])
    message = serializers.CharField()


class RegistrationRateThrottle(AnonRateThrottle):
    scope = "registration"


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


class ResearcherRegistrationView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [RegistrationRateThrottle]

    @extend_schema(request=ResearcherRegistrationSerializer, responses={201: RegistrationResponseSerializer})
    def post(self, request):
        serializer = ResearcherRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"status": "pending_approval", "message": "申请已提交，请等待平台管理员审核启用账号。"},
            status=status.HTTP_201_CREATED,
        )


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
