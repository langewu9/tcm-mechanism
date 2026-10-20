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
    index_template = "admin/platform_index.html"

    def get_urls(self):
        from django.urls import path
        from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
        from apps.core.permissions import IsPlatformAdministrator

        return [
            path("platform-api/schema/", self.admin_view(SpectacularAPIView.as_view(
                permission_classes=[IsPlatformAdministrator],
            )), name="platform-api-schema"),
            path("platform-api/", self.admin_view(SpectacularSwaggerView.as_view(
                url_name="admin:platform-api-schema", permission_classes=[IsPlatformAdministrator],
            )), name="platform-api-docs"),
        ] + super().get_urls()

    def has_permission(self, request):
        return super().has_permission(request) and request.user.is_superuser
