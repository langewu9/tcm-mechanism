from django.urls import path
from django.views.decorators.csrf import csrf_protect

from ..views import HealthView, HomeStatsView
from ..views.auth import CsrfTokenView, ResearcherRegistrationView, SessionView
from ..views.network_pharmacology import NetworkPharmacologyView
from ..views.external_analysis import ReactomeEnrichmentView, StringNetworkView


def csrf_checked(view):
    protected = csrf_protect(view)
    protected.csrf_exempt = False
    return protected


urlpatterns = [
    path("health/", HealthView.as_view(), name="api-health"),
    path("home-stats/", HomeStatsView.as_view(), name="home-stats"),
    path("analysis/network-pharmacology/", NetworkPharmacologyView.as_view(), name="network-pharmacology"),
    path("analysis/pathway-enrichment/", ReactomeEnrichmentView.as_view(), name="pathway-enrichment"),
    path("analysis/string-network/", StringNetworkView.as_view(), name="string-network"),
    path("auth/csrf/", csrf_checked(CsrfTokenView.as_view()), name="auth-csrf"),
    path("auth/session/", csrf_checked(SessionView.as_view()), name="auth-session"),
    path("auth/register/", csrf_checked(ResearcherRegistrationView.as_view()), name="auth-register"),
]
