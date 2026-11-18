from django.urls import include, path
from rest_framework.routers import DefaultRouter

from ..views import AnalysisTaskViewSet, MedicalCaseViewSet, ResearchAssistantView, ResearchDatasetViewSet, ResearchDashboardView
from ..views.research import VisualizationArtifactDownloadView
from ..views.case_statistics import CaseStatisticsView
from ..views.text_analysis import TextAnalysisView

router = DefaultRouter()
router.register("datasets", ResearchDatasetViewSet, basename="dataset")
router.register("cases", MedicalCaseViewSet, basename="case")
router.register("analysis-tasks", AnalysisTaskViewSet, basename="analysis-task")

urlpatterns = [
    path("case-corpus/", include("apps.case_rag.urls")),
    path("case-statistics/", CaseStatisticsView.as_view(), name="case-statistics"),
    path("dashboard/", ResearchDashboardView.as_view(), name="research-dashboard"),
    path("assistant/", ResearchAssistantView.as_view(), name="research-assistant"),
    path("text-analysis/", TextAnalysisView.as_view(), name="text-analysis"),
    path("", include(router.urls)),
    path(
        "analysis-artifacts/<int:pk>/download/",
        VisualizationArtifactDownloadView.as_view(),
        name="analysis-artifact-download",
    ),
]
