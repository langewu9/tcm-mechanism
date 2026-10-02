from django.urls import include, path
from rest_framework.routers import DefaultRouter

from ..views import DataSourceViewSet, EntityNeighborhoodView, EvidenceRelationViewSet, KnowledgeEntityViewSet

router = DefaultRouter()
router.register("sources", DataSourceViewSet, basename="source")
router.register("entities", KnowledgeEntityViewSet, basename="entity")
router.register("evidence", EvidenceRelationViewSet, basename="evidence")

urlpatterns = [
    path("entities/<int:entity_id>/neighborhood/", EntityNeighborhoodView.as_view(), name="entity-neighborhood"),
    path("", include(router.urls)),
]
