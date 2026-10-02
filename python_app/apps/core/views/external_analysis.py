from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..serializers.research import (
    ExternalGeneListRequestSerializer,
    AnalysisTaskSerializer,
    StringNetworkRequestSerializer,
)
from ..services.external_analysis import (
    enqueue_reactome_enrichment,
    enqueue_string_network,
)


class ReactomeEnrichmentView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ExternalGeneListRequestSerializer, responses={202: AnalysisTaskSerializer})
    def post(self, request):
        serializer = ExternalGeneListRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            task = enqueue_reactome_enrichment(request.user, serializer.validated_data["targets"])
        except ValueError as exc:
            raise ValidationError({"targets": str(exc)}) from exc
        return Response(AnalysisTaskSerializer(task).data, status=status.HTTP_202_ACCEPTED)


class StringNetworkView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=StringNetworkRequestSerializer, responses={202: AnalysisTaskSerializer})
    def post(self, request):
        serializer = StringNetworkRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            task = enqueue_string_network(request.user, values["targets"], values["required_score"])
        except ValueError as exc:
            raise ValidationError({"targets": str(exc)}) from exc
        return Response(AnalysisTaskSerializer(task).data, status=status.HTTP_202_ACCEPTED)
