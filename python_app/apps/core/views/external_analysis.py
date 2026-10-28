from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from ..serializers.chembl import (
    ChemblActivityRequestSerializer,
    ChemblActivityResponseSerializer,
    ComponentCompareRequestSerializer,
    ComponentCompareResponseSerializer,
    ChemblMoleculeSearchRequestSerializer,
    ChemblMoleculeSearchResponseSerializer,
)
from ..serializers.research import (
    ExternalGeneListRequestSerializer,
    AnalysisTaskSerializer,
    StringNetworkRequestSerializer,
)
from ..services.external_analysis import (
    enqueue_reactome_enrichment,
    enqueue_string_network,
)
from ..services.chembl import ChemblServiceError, molecule_activities, search_molecules
from ..services.component_names import compare_components_multilingual
from ..models import AnalysisTask


def _owned_source_task(user, values):
    source_task_id = values.get("source_task_id")
    if source_task_id is None:
        return None
    try:
        # Superusers can inspect all tasks, but cannot submit another
        # researcher's private candidate identifiers to an external provider.
        return AnalysisTask.objects.get(pk=source_task_id, owner=user)
    except AnalysisTask.DoesNotExist as exc:
        raise NotFound("没有找到当前账号下的来源任务。") from exc


class ChemblUnavailable(APIException):
    status_code = 503
    default_detail = "ChEMBL 服务暂时不可用，请稍后重试。"
    default_code = "service_unavailable"


class ReactomeEnrichmentView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ExternalGeneListRequestSerializer, responses={202: AnalysisTaskSerializer})
    def post(self, request):
        serializer = ExternalGeneListRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        source_task = _owned_source_task(request.user, values)
        try:
            task = enqueue_reactome_enrichment(
                request.user, values.get("targets"), source_task=source_task,
            )
        except ValueError as exc:
            raise ValidationError({"source_task_id" if source_task else "targets": str(exc)}) from exc
        return Response(AnalysisTaskSerializer(task).data, status=status.HTTP_202_ACCEPTED)


class StringNetworkView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=StringNetworkRequestSerializer, responses={202: AnalysisTaskSerializer})
    def post(self, request):
        serializer = StringNetworkRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        source_task = _owned_source_task(request.user, values)
        try:
            task = enqueue_string_network(
                request.user, values.get("targets"), values["required_score"], source_task=source_task,
            )
        except ValueError as exc:
            raise ValidationError({"source_task_id" if source_task else "targets": str(exc)}) from exc
        return Response(AnalysisTaskSerializer(task).data, status=status.HTTP_202_ACCEPTED)


class ChemblMoleculeSearchView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "chembl"

    @extend_schema(request=ChemblMoleculeSearchRequestSerializer, responses=ChemblMoleculeSearchResponseSerializer)
    def post(self, request):
        serializer = ChemblMoleculeSearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = search_molecules(serializer.validated_data["query"])
        except ValueError as exc:
            raise ValidationError({"query": str(exc)}) from exc
        except ChemblServiceError as exc:
            raise ChemblUnavailable(str(exc)) from exc
        return Response(result)


class ChemblActivitySearchView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "chembl"

    @extend_schema(request=ChemblActivityRequestSerializer, responses=ChemblActivityResponseSerializer)
    def post(self, request):
        serializer = ChemblActivityRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chembl_id = serializer.validated_data["chemblId"]
        try:
            result = molecule_activities(chembl_id)
        except ValueError as exc:
            raise ValidationError({"chemblId": str(exc)}) from exc
        except ChemblServiceError as exc:
            raise ChemblUnavailable(str(exc)) from exc
        return Response(result)


class ComponentCompareView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ComponentCompareRequestSerializer, responses=ComponentCompareResponseSerializer)
    def post(self, request):
        serializer = ComponentCompareRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = compare_components_multilingual(
                serializer.validated_data["detected"],
                serializer.validated_data["reference"],
            )
        except ValueError as exc:
            raise ValidationError({"components": str(exc)}) from exc
        from apps.core.services.catalog_visualization import fingerprint_result
        return Response(fingerprint_result(result))
