from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "平台核心"

    def ready(self):
        from . import checks  # noqa: F401 - register application checks
