"""Deployment checks for shared controls that need production configuration."""
from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


@register(Tags.security)
def request_limit_checks(app_configs, **kwargs):
    errors = []
    for name in ("DATA_UPLOAD_MAX_MEMORY_SIZE", "DATASET_UPLOAD_MAX_BYTES"):
        value = getattr(settings, name, None)
        if type(value) is not int or value <= 0:
            errors.append(Error(f"{name} must be a positive byte limit.", id="platform.E001"))
    return errors


@register(Tags.security, deploy=True)
def shared_control_checks(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    messages = []
    backend = settings.CACHES["default"]["BACKEND"]
    if "LocMemCache" in backend or "DummyCache" in backend:
        messages.append(Warning(
            "Use a shared cache for limits across API workers.",
            hint="Configure CACHE_URL to the private Redis cache DB.",
            id="platform.W001",
        ))
    if any(marker in settings.SECRET_KEY.lower() for marker in ("replace-with", "unsafe-key", "dev-only")):
        messages.append(Error(
            "Replace the example Django secret before deployment.", id="platform.E002"
        ))
    return messages
