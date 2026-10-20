"""Keep the maintenance site behind the same owner boundary as admin APIs."""

from django.contrib.admin import AdminSite
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.exceptions import ValidationError


class PlatformAdminAuthenticationForm(AdminAuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_superuser:
            raise ValidationError("只有平台超级管理员可以登录管理后台。", code="invalid_login")


class PlatformAdminSite(AdminSite):
    login_form = PlatformAdminAuthenticationForm

    def has_permission(self, request):
        return super().has_permission(request) and request.user.is_superuser
