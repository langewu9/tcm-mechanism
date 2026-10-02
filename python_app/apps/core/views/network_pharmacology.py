from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..serializers.research import (
    NetworkPharmacologyRequestSerializer,
    NetworkPharmacologyResponseSerializer,
)
from ..services.network_pharmacology import build_network_pharmacology


class NetworkPharmacologyView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=NetworkPharmacologyRequestSerializer,
        responses={200: NetworkPharmacologyResponseSerializer},
    )
    def post(self, request):
        serializer = NetworkPharmacologyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = build_network_pharmacology(
            user=request.user,
            herb_query=data["herb"],
            disease_query=data["disease"],
            row_limit=data["limit"],
        )
        return Response(result)
