from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..serializers.research import (
    AnalysisTaskSerializer,
    NetworkPharmacologyRequestSerializer,
    NetworkPharmacologyResponseSerializer,
)
from ..models import AnalysisTask, MedicalCaseCandidate
from ..services.network_pharmacology import NetworkPharmacologyInputError, build_network_pharmacology, parse_herb_names


class NetworkPharmacologyView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=NetworkPharmacologyRequestSerializer,
        responses={200: NetworkPharmacologyResponseSerializer, 202: AnalysisTaskSerializer},
    )
    def post(self, request):
        serializer = NetworkPharmacologyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        source_case_candidate = None
        if data.get("source_case_id"):
            try:
                source_case_candidate = MedicalCaseCandidate.objects.select_related(
                    "medical_case", "task", "entity__source_release__source"
                ).get(
                    pk=data["source_candidate_id"],
                    medical_case_id=data["source_case_id"],
                    medical_case__archived_at__isnull=True,
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
            from ..services.case_analysis import candidate_entity_available, case_input_sha256

            if not candidate_entity_available(source_case_candidate):
                raise ValidationError({"source_candidate_id": "方剂实体或来源已不可用，请重新核对并确认候选。"})

            if source_case_candidate.task.input_parameters.get("caseContentSha256") != case_input_sha256(source_case_candidate.medical_case):
                raise ValidationError({"source_candidate_id": "医案内容已改变；请重新分析并确认方剂候选。"})
            if source_case_candidate.entity.label.casefold() not in {name.casefold() for name in parse_herb_names(data["herb"])}:
                raise ValidationError({"herb": "查询条件必须保留已确认的规范方剂名称。"})
        if data["complete"]:
            from ..services.complete_evidence import VERSION, dispatch_complete_task
            from ..services.network_pharmacology import STATISTICS_VERSION
            parameters = {"analysisKind": "network_pharmacology", "complete": True,
                          "algorithmVersion": VERSION, "statisticsVersion": STATISTICS_VERSION,
                          "herb": data["herb"], "disease": data["disease"]}
            if source_case_candidate:
                parameters.update(sourceCaseId=source_case_candidate.medical_case_id,
                                  sourceCandidateId=source_case_candidate.pk,
                                  sourceFormulaStableId=source_case_candidate.entity.stable_id,
                                  caseContentSha256=source_case_candidate.task.input_parameters["caseContentSha256"])
            task = AnalysisTask.objects.create(owner=request.user, created_by=request.user,
                        task_type=AnalysisTask.TaskType.NETWORK,
                        medical_case=source_case_candidate.medical_case if source_case_candidate else None,
                        input_parameters=parameters)
            dispatch_complete_task(task, request=request)
            return Response(AnalysisTaskSerializer(task).data, status=202)
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
