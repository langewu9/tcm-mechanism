from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..serializers.research import (
    NetworkPharmacologyRequestSerializer,
    NetworkPharmacologyResponseSerializer,
)
from ..models import AnalysisTask, MedicalCaseCandidate
from ..services.network_pharmacology import NetworkPharmacologyInputError, build_network_pharmacology, parse_herb_names


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
        source_case_candidate = None
        if data.get("source_case_id"):
            try:
                source_case_candidate = MedicalCaseCandidate.objects.select_related(
                    "medical_case", "task", "entity"
                ).get(
                    pk=data["source_candidate_id"],
                    medical_case_id=data["source_case_id"],
                    medical_case__owner=request.user,
                    task__owner=request.user,
                    task__medical_case_id=data["source_case_id"],
                )
            except MedicalCaseCandidate.DoesNotExist as exc:
                raise NotFound("没有找到当前账号下的医案分析候选。") from exc
            if (
                source_case_candidate.review_status != MedicalCaseCandidate.ReviewStatus.ACCEPTED
                or source_case_candidate.candidate_type != MedicalCaseCandidate.CandidateType.FORMULA
                or not source_case_candidate.entity_id
                or source_case_candidate.task.status != AnalysisTask.Status.SUCCEEDED
            ):
                raise ValidationError({"source_candidate_id": "只有已确认且已完成分析的方剂候选可以进入网络药理流程。"})
            from ..services.case_analysis import case_input_sha256

            if source_case_candidate.task.input_parameters.get("caseContentSha256") != case_input_sha256(source_case_candidate.medical_case):
                raise ValidationError({"source_candidate_id": "医案内容已改变；请重新分析并确认方剂候选。"})
            if source_case_candidate.entity.label.casefold() not in {name.casefold() for name in parse_herb_names(data["herb"])}:
                raise ValidationError({"herb": "查询条件必须保留已确认的规范方剂名称。"})
        try:
            result = build_network_pharmacology(
                user=request.user,
                herb_query=data["herb"],
                disease_query=data["disease"],
                row_limit=data["limit"],
                source_case_candidate=source_case_candidate,
            )
        except NetworkPharmacologyInputError as exc:
            raise ValidationError({"source_candidate_id": str(exc)}) from exc
        return Response(result)
