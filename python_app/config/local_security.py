"""Narrow defaults for the repository's loopback-only Vite development UI."""

LOCAL_FRONTEND_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")


def trusted_csrf_origins(configured, *, debug):
    # Explicit deployment configuration takes priority. Production gets no
    # development-origin exception; tokens/cookies are still mandatory.
    if configured:
        return list(configured)
    return list(LOCAL_FRONTEND_ORIGINS) if debug else []
