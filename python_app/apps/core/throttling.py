"""Shared login, authenticated API and expensive research submission limits."""
import hashlib
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle


class LoginIPThrottle(SimpleRateThrottle):
    scope = "login_ip"

    def get_cache_key(self, request, view):
        if request.method != "POST":
            return None
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LoginAccountThrottle(SimpleRateThrottle):
    scope = "login_account"

    def get_cache_key(self, request, view):
        if request.method != "POST":
            return None
        username = request.data.get("username", "") if isinstance(request.data, dict) else ""
        if not isinstance(username, str) or not username.strip():
            return None
        digest = hashlib.sha256(username.strip().casefold().encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}


class PlatformUserThrottle(UserRateThrottle):
    scope = "platform_user"

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None
        return super().get_cache_key(request, view)


class ResearchSubmissionThrottle(PlatformUserThrottle):
    """A shared per-user budget for expensive research submissions."""
    scope = "research_submission"
    paths = {
        "/api/v1/research/assistant/", "/api/v1/research/text-analysis/",
        "/api/v1/analysis/network-pharmacology/", "/api/v1/analysis/pathway-enrichment/",
        "/api/v1/analysis/string-network/",
        "/api/v1/catalog/herb-evidence/batch/", "/api/v1/catalog/herb-evidence/analyses/",
        "/api/v1/catalog/diseases/evidence-analyses/",
    }

    def get_cache_key(self, request, view):
        research_action = request.path.startswith("/api/v1/research/") and request.path.endswith(
            ("/analyze/", "/analysis/", "/visualizations/")
        )
        if request.method != "POST" or not (research_action or request.path in self.paths):
            return None
        return super().get_cache_key(request, view)


class DatasetUploadThrottle(PlatformUserThrottle):
    """Give synchronous file parsing a separately configurable per-user budget."""
    scope = "dataset_upload"

    def get_cache_key(self, request, view):
        if request.method != "POST" or getattr(view, "action", None) != "create":
            return None
        return super().get_cache_key(request, view)
