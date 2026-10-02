from django.urls import path
from django.views.decorators.csrf import csrf_protect

from ..views import HealthView, HomeStatsView
from ..views.auth import CsrfTokenView, SessionView


def csrf_checked(view):
    protected = csrf_protect(view)
    protected.csrf_exempt = False
    return protected


urlpatterns = [
    path("health/", HealthView.as_view(), name="api-health"),
    path("home-stats/", HomeStatsView.as_view(), name="home-stats"),
    path("auth/csrf/", csrf_checked(CsrfTokenView.as_view()), name="auth-csrf"),
    path("auth/session/", csrf_checked(SessionView.as_view()), name="auth-session"),
]
