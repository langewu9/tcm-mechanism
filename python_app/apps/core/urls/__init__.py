from django.urls import path

from ..views import csrf_token, health, home_stats, session

urlpatterns = [
    path("health/", health, name="api-health"),
    path("home-stats/", home_stats, name="home-stats"),
    path("auth/csrf/", csrf_token, name="auth-csrf"),
    path("auth/session/", session, name="auth-session"),
]
