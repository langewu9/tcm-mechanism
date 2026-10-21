"""Settings for the independently runnable Django application."""

from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["127.0.0.1", "localhost"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
)
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

DEBUG = env.bool("DJANGO_DEBUG", default=False)
SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY before running outside development.")
    SECRET_KEY = "local-only-unsafe-key-do-not-use-in-production"

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "config.admin_apps.PlatformAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "apps.core.apps.CoreConfig",
    "apps.proteomics.apps.ProteomicsConfig",
    "apps.sources.apps.SourcesConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.api_errors.ApiErrorEnvelopeMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "config.access_audit.SensitiveAccessAuditMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DATABASE_CONN_MAX_AGE", default=60)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = (BASE_DIR / env("MEDIA_ROOT", default="var/media")).resolve()
MEDIA_URL = "media/"
# Private operational diagnostics, separate from uploads and the business DB.
RUNTIME_LOG_DIR = Path(env("RUNTIME_LOG_DIR", default=str(BASE_DIR / "var/runtime-logs")))
PUBLIC_BASE_URL = env(
    "PUBLIC_BASE_URL",
    default="http://127.0.0.1:5173" if DEBUG else "",
).rstrip("/")
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default=(
        "django.core.mail.backends.console.EmailBackend"
        if DEBUG
        else "django.core.mail.backends.smtp.EmailBackend"
    ),
)
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@localhost" if DEBUG else "")
EMAIL_VERIFICATION_MAX_AGE_SECONDS = env.int("EMAIL_VERIFICATION_MAX_AGE_SECONDS", default=24 * 60 * 60)
ADMIN_NOTIFICATION_EMAILS = env.list("ADMIN_NOTIFICATION_EMAILS", default=[])
S3_STORAGE_ENABLED = env.bool("S3_STORAGE_ENABLED", default=False)
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage" if S3_STORAGE_ENABLED else "django.core.files.storage.FileSystemStorage",
        "OPTIONS": (
            {
                "bucket_name": env("S3_BUCKET_NAME"),
                "endpoint_url": env("S3_ENDPOINT_URL", default=None) or None,
                "access_key": env("S3_ACCESS_KEY_ID"),
                "secret_key": env("S3_SECRET_ACCESS_KEY"),
                "region_name": env("S3_REGION", default="us-east-1"),
                "addressing_style": env("S3_ADDRESSING_STYLE", default="path"),
                "default_acl": None,
                "querystring_auth": True,
                "file_overwrite": False,
            }
            if S3_STORAGE_ENABLED
            else {"location": str(MEDIA_ROOT), "base_url": MEDIA_URL}
        ),
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
DATASET_UPLOAD_MAX_BYTES = env.int("DATASET_UPLOAD_MAX_BYTES", default=100 * 1024 * 1024)
DATASET_STORAGE_QUOTA_BYTES = env.int("DATASET_STORAGE_QUOTA_BYTES", default=1024 * 1024 * 1024)
DATASET_COUNT_QUOTA = env.int("DATASET_COUNT_QUOTA", default=100)
DATA_UPLOAD_MAX_MEMORY_SIZE = env.int("API_REQUEST_MAX_BYTES", default=1024 * 1024)
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FILES = 1
PROTEOMICS_MAX_ROWS = env.int("PROTEOMICS_MAX_ROWS", default=25_000)
LOCAL_ANALYSIS_RELATION_LIMIT = env.int("LOCAL_ANALYSIS_RELATION_LIMIT", default=50_000)
PROTEOMICS_MAX_COLUMNS = env.int("PROTEOMICS_MAX_COLUMNS", default=250)
PROTEOMICS_MAX_CELLS = env.int("PROTEOMICS_MAX_CELLS", default=1_000_000)
SQLITE_SOURCE_ROOT = env("SQLITE_SOURCE_ROOT", default="")
SQLITE_SOURCE_MAX_BYTES = env.int("SQLITE_SOURCE_MAX_BYTES", default=512 * 1024 * 1024)
SQLITE_SOURCE_MAX_ROWS = env.int("SQLITE_SOURCE_MAX_ROWS", default=500_000)
STRING_DB_VERSION = env("STRING_DB_VERSION", default="")
CASE_MODEL_BASE_URL = env("CASE_MODEL_BASE_URL", default="")
CASE_MODEL_NAME = env("CASE_MODEL_NAME", default="")
CASE_MODEL_VERSION = env("CASE_MODEL_VERSION", default="未配置")
CASE_MODEL_API_KEY = env("CASE_MODEL_API_KEY", default="")
CASE_MODEL_TIMEOUT_SECONDS = env.int("CASE_MODEL_TIMEOUT_SECONDS", default=180)
CASE_ANALYSIS_MAX_INPUT_CHARS = env.int("CASE_ANALYSIS_MAX_INPUT_CHARS", default=20000)
R_VIZ_BASE_URL = env("R_VIZ_BASE_URL", default="")
R_VIZ_API_TOKEN = env("R_VIZ_API_TOKEN", default="")
R_VIZ_MAX_RESPONSE_BYTES = env.int("R_VIZ_MAX_RESPONSE_BYTES", default=20 * 1024 * 1024)

SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=not DEBUG)
SESSION_COOKIE_SECURE = env.bool("DJANGO_SESSION_COOKIE_SECURE", default=not DEBUG)
SESSION_COOKIE_NAME = env("DJANGO_SESSION_COOKIE_NAME", default="sessionid")
CSRF_COOKIE_NAME = env("DJANGO_CSRF_COOKIE_NAME", default="csrftoken")
CSRF_COOKIE_SECURE = env.bool("DJANGO_CSRF_COOKIE_SECURE", default=not DEBUG)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env.bool("DJANGO_SECURE_HSTS_PRELOAD", default=False)
# Subdomain coverage and browser preloading require a domain owner's explicit
# decision. Keep HSTS for this host without requiring these optional policies.
# All other deployment warnings still fail the production setup check.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
if env.bool("DJANGO_USE_X_FORWARDED_PROTO", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
CSRF_FAILURE_VIEW = "config.api_errors.csrf_failure"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "config.api_errors.api_exception_handler",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "config.parsers.BoundedJSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "apps.core.throttling.PlatformUserThrottle",
        "apps.core.throttling.ResearchSubmissionThrottle",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "NUM_PROXIES": 1,
    "DEFAULT_THROTTLE_RATES": {
        "registration": "5/hour",
        "email_verification": "5/hour",
        "chembl": "10/hour",
        "login_ip": env("DJANGO_LOGIN_IP_RATE", default="30/min"),
        "login_account": env("DJANGO_LOGIN_ACCOUNT_RATE", default="10/min"),
        "platform_user": env("DJANGO_USER_RATE", default="600/min"),
        "research_submission": env("DJANGO_RESEARCH_SUBMISSION_RATE", default="120/hour"),
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "岐黄中医药理智能平台 API",
    "DESCRIPTION": "React/Vite 研究者平台 API；包含用户隔离的数据集、医案和异步蛋白组学分析。",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://127.0.0.1:6379/0")
CACHE_URL = env("CACHE_URL", default="")
if CACHE_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": CACHE_URL,
            "KEY_PREFIX": "tcm-platform",
        }
    }
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 1200
CELERY_TASK_SOFT_TIME_LIMIT = 1080
CELERY_TASK_IGNORE_RESULT = True
SOURCE_SCHEDULED_PREVIEWS_ENABLED = env.bool("SOURCE_SCHEDULED_PREVIEWS_ENABLED", default=False)
CELERY_BEAT_SCHEDULE = (
    {"source-preview-scan": {"task": "sources.schedule_previews", "schedule": 60.0}}
    if SOURCE_SCHEDULED_PREVIEWS_ENABLED else {}
)
