from rest_framework.permissions import BasePermission


class IsPlatformAdministrator(BasePermission):
    """Only the platform owner may inspect platform-wide research records."""

    message = "只有平台超级管理员可以查看平台管理信息。"

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class IsPlatformMaintenanceAdministrator(IsPlatformAdministrator):
    """Technical maintenance follows the stricter Django admin-site boundary."""

    def has_permission(self, request, view):
        return bool(super().has_permission(request, view) and request.user.is_active and request.user.is_staff)
