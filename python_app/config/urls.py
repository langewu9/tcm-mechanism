from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from apps.core.views.admin_overview import AdminOverviewView

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="admin:index", permanent=False), name="backend-root"),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("django-admin/", admin.site.urls),
    path("api/v1/research/", include("apps.core.urls.research")),
    path("api/v1/catalog/", include("apps.core.urls.catalog")),
    path("api/v1/admin/overview/", AdminOverviewView.as_view(), name="admin-overview"),
    path("api/v1/admin/", include("apps.sources.urls")),
    path("api/v1/", include("apps.core.urls")),
    path("api/schema/", RedirectView.as_view(pattern_name="admin:platform-api-schema", permanent=False), name="api-schema"),
    path("api/docs/", RedirectView.as_view(pattern_name="admin:platform-api-docs", permanent=False), name="api-docs"),
]
