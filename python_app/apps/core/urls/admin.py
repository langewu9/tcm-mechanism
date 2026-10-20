from django.urls import path

from apps.core.views.integrations import IntegrationStatusView, IntegrationTestView
from apps.core.views.runtime_logs import RuntimeLogView


urlpatterns = [
    path("runtime-logs/", RuntimeLogView.as_view(), name="admin-runtime-logs"),
    path("integrations/status/", IntegrationStatusView.as_view(), name="admin-integration-status"),
    path("integrations/test/", IntegrationTestView.as_view(), name="admin-integration-test"),
]
