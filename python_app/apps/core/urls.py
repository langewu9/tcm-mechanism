from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AnalysisTaskViewSet,
    DataSourceViewSet,
    EvidenceRelationViewSet,
    KnowledgeEntityViewSet,
    MedicalCaseViewSet,
    ResearchDatasetViewSet,
    health,
)


router = DefaultRouter()
router.register("datasets", ResearchDatasetViewSet, basename="dataset")
router.register("cases", MedicalCaseViewSet, basename="case")
router.register("analysis-tasks", AnalysisTaskViewSet, basename="analysis-task")
router.register("sources", DataSourceViewSet, basename="source")
router.register("entities", KnowledgeEntityViewSet, basename="entity")
router.register("evidence", EvidenceRelationViewSet, basename="evidence")

urlpatterns = [
    path("health/", health, name="api-health"),
    path("", include(router.urls)),
]
