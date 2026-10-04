"""Session-based authentication endpoints for the React client."""

import logging

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, AuthenticationFailed
from rest_framework.throttling import AnonRateThrottle
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import ResearcherProfile
from apps.core.services.account_verification import (
    EmailVerificationUnavailable,
    InvalidEmailVerificationToken,
    send_admin_registration_notice,
    send_verification_email,
    verify_email_token,
)


logger = logging.getLogger(__name__)

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
                user = user_model.objects.create_user(
                    username=validated_data["username"],
                    email=validated_data["email"],
                    password=validated_data["password"],
                    is_active=False,
                    is_staff=False,
                    is_superuser=False,
                )
                ResearcherProfile.objects.create(user=user)
                return user
        except IntegrityError as exc:
            raise serializers.ValidationError({"username": "该用户名已被使用，请重新选择。"}) from exc


class CsrfTokenSerializer(serializers.Serializer):
    csrfToken = serializers.CharField()


class RegistrationResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["pending_verification"])
    message = serializers.CharField()


class EmailVerificationRequestSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=4096, trim_whitespace=True)


class EmailVerificationResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["verified", "already_verified"])
    accountActive = serializers.BooleanField()
    message = serializers.CharField()


class ResendVerificationRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)


class ResendVerificationResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["accepted"])
    message = serializers.CharField()


class RegistrationRateThrottle(AnonRateThrottle):
    scope = "registration"


class EmailVerificationRateThrottle(AnonRateThrottle):
    scope = "email_verification"


class EmailDeliveryUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "目前无法发送验证邮件，请稍后重试或联系平台管理员。"
    default_code = "EMAIL_DELIVERY_UNAVAILABLE"


class SessionUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    name = serializers.CharField()
    email = serializers.EmailField(allow_blank=True)
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
        try:
            with transaction.atomic():
                user = serializer.save()
                send_verification_email(user)
        except EmailVerificationUnavailable as exc:
            logger.warning("Researcher verification email unavailable reason=%s", str(exc))
            raise EmailDeliveryUnavailable from exc
        return Response(
            {
                "status": "pending_verification",
                "message": "验证邮件已发送。请先确认邮箱，随后等待平台管理员审核启用账号。",
            },
            status=status.HTTP_201_CREATED,
        )


class EmailVerificationView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [EmailVerificationRateThrottle]

    @extend_schema(request=EmailVerificationRequestSerializer, responses=EmailVerificationResponseSerializer)
    def post(self, request):
        serializer = EmailVerificationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            profile, changed = verify_email_token(serializer.validated_data["token"])
        except InvalidEmailVerificationToken as exc:
            raise serializers.ValidationError({"token": str(exc)}) from exc
        if changed:
            send_admin_registration_notice(profile.user)
        return Response(
            {
                "status": "verified" if changed else "already_verified",
                "accountActive": profile.user.is_active,
                "message": (
                    "邮箱已验证，账号还需平台管理员审核启用。"
                    if not profile.user.is_active
                    else "邮箱已验证，账号可以登录。"
                ),
            }
        )


class ResendVerificationEmailView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [EmailVerificationRateThrottle]

    @extend_schema(request=ResendVerificationRequestSerializer, responses=ResendVerificationResponseSerializer)
    def post(self, request):
        serializer = ResendVerificationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = get_user_model().objects.filter(email__iexact=serializer.validated_data["email"]).first()
        profile = ResearcherProfile.objects.filter(user=user).first() if user else None
        if profile and not profile.email_verified_at:
            try:
                send_verification_email(user)
            except EmailVerificationUnavailable as exc:
                logger.warning("Researcher verification resend unavailable reason=%s", str(exc))
        return Response(
            {
                "status": "accepted",
                "message": "如果该邮箱对应待验证的研究者申请，新的验证邮件已发送。",
            }
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
                    "name": request.user.get_full_name() or request.user.get_username(),
                    "email": request.user.email,
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
        profile = ResearcherProfile.objects.filter(user=user).first()
        if profile and not profile.email_verified_at:
            raise AuthenticationFailed("请先通过注册邮箱中的链接完成邮箱验证。", code="email_not_verified")
        login(request, user)
        return Response(
            {
                "authenticated": True,
                "user": {
                    "id": user.pk,
                    "username": user.get_username(),
                    "name": user.get_full_name() or user.get_username(),
                    "email": user.email,
                    "isSuperuser": user.is_superuser,
                },
            }
        )

    @extend_schema(responses={204: None})
    def delete(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)
