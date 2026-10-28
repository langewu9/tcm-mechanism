from django.urls import path
from .views import CaseCorpusDetailView, CaseCorpusListView, CaseCorpusSummaryView

urlpatterns = [
    path("", CaseCorpusListView.as_view(), name="case-corpus-list"),
    path("summary/", CaseCorpusSummaryView.as_view(), name="case-corpus-summary"),
    path("<int:pk>/", CaseCorpusDetailView.as_view(), name="case-corpus-detail"),
]
