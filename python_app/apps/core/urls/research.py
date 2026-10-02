from django.urls import include, path
from rest_framework.routers import DefaultRouter

from ..views import AnalysisTaskViewSet, MedicalCaseViewSet, ResearchDatasetViewSet
from ..views.research import VisualizationArtifactDownloadView

router = DefaultRouter()
router.register("datasets", ResearchDatasetViewSet, basename="dataset")
router.register("cases", MedicalCaseViewSet, basename="case")
router.register("analysis-tasks", AnalysisTaskViewSet, basename="analysis-task")

urlpatterns = [
    path("", include(router.urls)),
    path(
        "analysis-artifacts/<int:pk>/download/",
        VisualizationArtifactDownloadView.as_view(),
        name="analysis-artifact-download",
    ),
]
