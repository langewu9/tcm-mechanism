"""Settings used only to check the pre-existing original SQLite schema."""

from .settings import *  # noqa: F403

# The original database is intentionally not migrated. Exclude the new sidecar
# app from its read-only migration check; the normal runtime settings still
# load it, and its own schema is migrated against the separate case_rag alias.
INSTALLED_APPS = [
    app for app in INSTALLED_APPS  # noqa: F405
    if app != "apps.case_rag.apps.CaseRagConfig"
]
# This configuration is only for the original schema's migration check. Its
# runtime URL tree now includes the sidecar app intentionally excluded above.
ROOT_URLCONF = "config.urls_original_sqlite_check"
