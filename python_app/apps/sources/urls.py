from django.urls import path

from apps.sources.views import (
    DataSourceListView,
    ReactomeApplyView,
    ReactomePreviewView,
    SQLiteSourceTestView,
    SyncRunListView,
)


urlpatterns = [
    path("sources/", DataSourceListView.as_view(), name="sync-source-list"),
    path("sources/<int:source_id>/test/", SQLiteSourceTestView.as_view(), name="sync-source-test"),
    path("sources/<int:source_id>/sync/", ReactomePreviewView.as_view(), name="sync-source-preview"),
    path("sync-runs/", SyncRunListView.as_view(), name="sync-run-list"),
    path("sync-runs/<int:run_id>/apply/", ReactomeApplyView.as_view(), name="sync-run-apply"),
]
