from django.urls import path

from apps.core.views.integrations import IntegrationStatusView, IntegrationTestView


urlpatterns = [
    path("integrations/status/", IntegrationStatusView.as_view(), name="admin-integration-status"),
    path("integrations/test/", IntegrationTestView.as_view(), name="admin-integration-test"),
]
