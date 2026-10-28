from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.serializers.research import AnalysisTaskSerializer
from apps.core.services.catalog_visualization import CatalogueChanged, freeze_catalog_query


class CatalogSnapshotRequestSerializer(serializers.Serializer):
    queryType = serializers.ChoiceField(choices=["herb", "compound", "disease", "pathway", "entity", "comparison"])
    queries = serializers.ListField(child=serializers.CharField(max_length=160, allow_blank=True), max_length=12, required=False)
    entityId = serializers.IntegerField(min_value=1, required=False)
    expectedSha256 = serializers.RegexField(r"^[a-f0-9]{64}$")
    detected = serializers.CharField(max_length=6000, required=False)
    reference = serializers.CharField(max_length=6000, required=False)

    def validate(self, values):
        kind, queries = values["queryType"], values.get("queries", [])
        if kind == "comparison":
            if not values.get("detected") or not values.get("reference") or queries: raise serializers.ValidationError("请提供检测与参考名称列表。")
        elif kind == "entity":
            if not values.get("entityId") or queries: raise serializers.ValidationError("知识目录图表需要明确实体 ID。")
        elif not queries or (kind in {"disease", "pathway"} and len(queries) != 1):
            raise serializers.ValidationError("请提供本次检索的原始查询条件。")
        elif kind != "pathway" and any(not query.strip() or len(query) > 120 for query in queries):
            raise serializers.ValidationError("名称不能为空且最多 120 个字符。")
        return values


class CatalogSnapshotView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=CatalogSnapshotRequestSerializer, responses=AnalysisTaskSerializer)
    def post(self, request):
        serializer = CatalogSnapshotRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            task = freeze_catalog_query(user=request.user, parameters=serializer.validated_data)
        except CatalogueChanged as exc:
            return Response({"detail": str(exc), "code": "CATALOGUE_CHANGED"}, status=409)
        except ValueError as exc:
            raise ValidationError({"queries": str(exc)}) from exc
        return Response(AnalysisTaskSerializer(task, context={"request": request}).data)
