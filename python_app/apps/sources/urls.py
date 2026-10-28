from django.urls import path
from apps.sources.master_views import MasterTableSummaryView
from apps.sources.target_identity_views import TargetIdentityListView

from apps.sources.views import (
    DataSourceDeleteView,
    DataSourceListView,
    SourceSyncApplyView,
    SourceSyncPreviewView,
    SQLiteSourceTestView,
    SyncRunListView,
)


urlpatterns = [
    path("target-identities/", TargetIdentityListView.as_view(), name="target-identity-list"),
    path("master-table/", MasterTableSummaryView.as_view(), name="master-table-summary"),
    path("sources/", DataSourceListView.as_view(), name="sync-source-list"),
    path("sources/<int:source_id>/", DataSourceDeleteView.as_view(), name="sync-source-delete"),
    path("sources/<int:source_id>/test/", SQLiteSourceTestView.as_view(), name="sync-source-test"),
    path("sources/<int:source_id>/sync/", SourceSyncPreviewView.as_view(), name="sync-source-preview"),
    path("sync-runs/", SyncRunListView.as_view(), name="sync-run-list"),
    path("sync-runs/<int:run_id>/apply/", SourceSyncApplyView.as_view(), name="sync-run-apply"),
]
