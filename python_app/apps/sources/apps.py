from django.apps import AppConfig


class SourcesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sources"
    verbose_name = "外部数据源同步"
