"""Login-only limits shared by session API workers."""
import hashlib
from rest_framework.throttling import SimpleRateThrottle


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
