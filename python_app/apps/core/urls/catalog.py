from django.urls import include, path
from rest_framework.routers import DefaultRouter

from ..views import BatchHerbEvidenceView, DataSourceViewSet, DiseaseAliasSearchView, EntityNeighborhoodView, EvidenceRelationViewSet, KnowledgeEntityViewSet
from ..views.pathway_catalog import ReactomePathwayCatalogView

router = DefaultRouter()
router.register("sources", DataSourceViewSet, basename="source")
router.register("entities", KnowledgeEntityViewSet, basename="entity")
router.register("evidence", EvidenceRelationViewSet, basename="evidence")

urlpatterns = [
    path("pathways/reactome/", ReactomePathwayCatalogView.as_view(), name="reactome-pathway-catalog"),
    path("diseases/alias-search/", DiseaseAliasSearchView.as_view(), name="disease-alias-search"),
    path("herb-evidence/batch/", BatchHerbEvidenceView.as_view(), name="batch-herb-evidence"),
    path("entities/<int:entity_id>/neighborhood/", EntityNeighborhoodView.as_view(), name="entity-neighborhood"),
    path("", include(router.urls)),
]
