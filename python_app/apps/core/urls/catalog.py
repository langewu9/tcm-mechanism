from django.urls import include, path
from rest_framework.routers import DefaultRouter

from ..views import DataSourceViewSet, EvidenceRelationViewSet, KnowledgeEntityViewSet

router = DefaultRouter()
router.register("sources", DataSourceViewSet, basename="source")
router.register("entities", KnowledgeEntityViewSet, basename="entity")
router.register("evidence", EvidenceRelationViewSet, basename="evidence")

urlpatterns = [path("", include(router.urls))]
