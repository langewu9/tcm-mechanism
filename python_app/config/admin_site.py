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
            path("platform-integrations/", self.admin_view(self.integration_monitor), name="platform-integrations"),
        ] + super().get_urls()

    def integration_monitor(self, request):
        from django.http import HttpResponseNotAllowed
        from django.template.response import TemplateResponse
        from django.urls import reverse

        if request.method not in {"GET", "HEAD"}:
            return HttpResponseNotAllowed(["GET", "HEAD"])
        # The checks retain the fixed inputs and consent rules of the old React
        # maintenance page. The existing API remains the only test executor.
        checks = [
            {"target": "qwen", "title": "Qwen / 本机模型", "description": "向配置的本机/内网模型发送一条不含研究数据的合成短文本。", "consent": "同意向配置的本机/内网模型发送本次合成测试文本。"},
            {"target": "disease", "title": "疾病证据检索", "description": "使用 Pulmonary fibrosis 检查本地目录与别名查询。", "local": True},
            {"target": "herb", "title": "中药证据检索", "description": "使用粳米检查本地中药—成分—靶点证据。", "local": True},
            {"target": "component", "title": "成分靶点检索", "description": "使用 quercetin 检查本地成分证据。", "local": True},
            {"target": "chembl", "title": "ChEMBL 官方接口", "description": "只发送测试词 quercetin，不发送研究者上传数据。", "consent": "同意将本次测试词 quercetin 发送到 ChEMBL 官方服务。"},
            {"target": "intersection", "title": "靶点交集", "description": "计算本地目录交集，不保存分析任务。", "local": True},
            {"target": "compare", "title": "成分比对", "description": "比较固定合成测试名称，不读取用户上传数据。", "local": True},
            {"target": "scientist", "title": "AI Scientist", "description": "main 所需 Excel/SQLite 数据未提供，暂不可测试。", "unavailable": True},
        ]
        return TemplateResponse(request, "admin/integration_monitor.html", {
            **self.each_context(request), "title": "API 接入监测", "checks": checks,
            "status_url": reverse("admin-integration-status"), "test_url": reverse("admin-integration-test"),
        })

    def has_permission(self, request):
        return super().has_permission(request) and request.user.is_superuser
