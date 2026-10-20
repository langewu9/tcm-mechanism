from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.services.pathway_catalog import search_reactome_pathways


class PathwayQuerySerializer(serializers.Serializer):
    query = serializers.CharField(max_length=160, allow_blank=True, default="")


class PathwayAnnotationSourceSerializer(serializers.Serializer):
    sourceSlug = serializers.CharField()
    sourceVersion = serializers.CharField()


class PathwaySourceSerializer(PathwayAnnotationSourceSerializer):
    checksumSha256 = serializers.CharField()


class PathwayItemSerializer(serializers.Serializer):
    entityId = serializers.IntegerField()
    stableId = serializers.CharField()
    name = serializers.CharField()
    species = serializers.CharField()
    sourceVersion = serializers.CharField()
    checksumSha256 = serializers.CharField()
    sourceUrl = serializers.URLField()
    lastSyncedAt = serializers.DateTimeField()
    targetAnnotations = serializers.IntegerField()
    annotationSources = PathwayAnnotationSourceSerializer(many=True)
    enrichmentRecords = serializers.IntegerField(allow_null=True)


class PathwayCatalogResponseSerializer(serializers.Serializer):
    query = serializers.CharField()
    catalogTotal = serializers.IntegerField()
    matchedTotal = serializers.IntegerField()
    maxItems = serializers.IntegerField()
    truncated = serializers.BooleanField()
    sourceCode = serializers.CharField()
    sources = PathwaySourceSerializer(many=True)
    items = PathwayItemSerializer(many=True)
    warnings = serializers.ListField(child=serializers.CharField())


class ReactomePathwayCatalogView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[PathwayQuerySerializer], responses=PathwayCatalogResponseSerializer)
    def get(self, request):
        serializer = PathwayQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return Response(search_reactome_pathways(serializer.validated_data["query"]))
