"""Email ownership verification for researcher accounts."""

from __future__ import annotations

import hashlib
import hmac
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.http import urlencode

from apps.core.models import ResearcherProfile


logger = logging.getLogger(__name__)
TOKEN_SALT = "researcher-email-verification-v1"


class EmailVerificationUnavailable(RuntimeError):
    """The platform cannot safely issue a verification link right now."""


class InvalidEmailVerificationToken(ValueError):
    """A verification token is invalid, expired, or no longer matches the email."""


def _email_digest(email: str) -> str:
    return hashlib.sha256(email.strip().casefold().encode("utf-8")).hexdigest()


def _signer() -> signing.TimestampSigner:
    return signing.TimestampSigner(salt=TOKEN_SALT)


def _verification_url(token: str) -> str:
    base_url = settings.PUBLIC_BASE_URL.rstrip("/")
    return f"{base_url}/verify-email?{urlencode({'token': token})}"


def send_verification_email(user) -> None:
    if not user.email:
        raise EmailVerificationUnavailable("研究者账号没有可验证的邮箱地址。")
    if not settings.DEFAULT_FROM_EMAIL:
        raise EmailVerificationUnavailable("平台尚未配置验证邮件发件地址。")
    if not settings.PUBLIC_BASE_URL:
        raise EmailVerificationUnavailable("平台尚未配置对外访问地址。")
    if not settings.DEBUG and not settings.EMAIL_HOST:
        raise EmailVerificationUnavailable("平台尚未配置邮件服务器。")

    token = _signer().sign_object({"user_id": user.pk, "email_sha256": _email_digest(user.email)})
    verification_url = _verification_url(token)
    try:
        sent = send_mail(
            subject="验证你的岐黄研究平台邮箱",
            message=(
                f"你好，{user.get_username()}：\n\n"
                f"请在 {settings.EMAIL_VERIFICATION_MAX_AGE_SECONDS // 3600} 小时内打开以下链接并确认邮箱：\n"
                f"{verification_url}\n\n如果你没有申请账号，可以忽略此邮件。"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception as exc:
        raise EmailVerificationUnavailable("验证邮件发送失败。") from exc
    if sent != 1:
        raise EmailVerificationUnavailable("验证邮件没有成功交给邮件服务器。")


def send_admin_registration_notice(user) -> None:
    recipients = settings.ADMIN_NOTIFICATION_EMAILS
    if not recipients:
        return
    try:
        send_mail(
            subject="新的研究者账号申请",
            message=(
                f"有新的研究者账号申请：{user.get_username()}（{user.email}）。\n"
                "申请者完成邮箱验证后，可由平台管理员在 Django Admin 审核并启用。"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )
    except Exception:
        logger.exception("Researcher registration notification failed user_id=%s", user.pk)


def verify_email_token(token: str) -> tuple[ResearcherProfile, bool]:
    try:
        payload = _signer().unsign_object(token, max_age=settings.EMAIL_VERIFICATION_MAX_AGE_SECONDS)
        user_id = int(payload["user_id"])
        email_digest = str(payload["email_sha256"])
    except (signing.BadSignature, signing.SignatureExpired, KeyError, TypeError, ValueError) as exc:
        raise InvalidEmailVerificationToken("验证链接无效或已过期，请重新发送验证邮件。") from exc

    user_model = get_user_model()
    try:
        with transaction.atomic():
            user = user_model.objects.select_for_update().get(pk=user_id)
            if not user.email or not hmac.compare_digest(email_digest, _email_digest(user.email)):
                raise InvalidEmailVerificationToken("邮箱地址已变更，请重新发送验证邮件。")
            profile = ResearcherProfile.objects.select_for_update().get(user=user)
            if profile.email_verified_at:
                return profile, False
            profile.email_verified_at = timezone.now()
            profile.save(update_fields=["email_verified_at", "updated_at"])
            return profile, True
    except (user_model.DoesNotExist, ResearcherProfile.DoesNotExist) as exc:
        raise InvalidEmailVerificationToken("验证链接无效或已过期，请重新发送验证邮件。") from exc
