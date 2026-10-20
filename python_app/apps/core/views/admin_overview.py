"""Read-only platform overview migrated from the main branch admin page."""

from django.contrib.auth import get_user_model
from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import AnalysisTask, MedicalCase, ResearchDataset
from apps.core.permissions import IsPlatformAdministrator


class AdminOverviewUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()
    email = serializers.CharField(allow_blank=True)
    role = serializers.SerializerMethodField()
    is_active = serializers.BooleanField()
    date_joined = serializers.DateTimeField()
    last_login = serializers.DateTimeField(allow_null=True)
    dataset_count = serializers.IntegerField()
    case_count = serializers.IntegerField()
    task_count = serializers.IntegerField()

    def get_name(self, user) -> str:
        return user.get_full_name().strip() or user.get_username()

    def get_role(self, user) -> str:
        return "ADMIN" if user.is_superuser else "RESEARCHER"


class AdminOverviewDatasetSerializer(serializers.ModelSerializer):
    owner_name = serializers.SerializerMethodField()

    class Meta:
        model = ResearchDataset
        fields = ["id", "name", "owner_name", "row_count", "created_at"]

    def get_owner_name(self, dataset) -> str:
        return dataset.owner.get_full_name().strip() or dataset.owner.get_username()


class AdminOverviewTaskSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    owner_name = serializers.SerializerMethodField()
    task_type = serializers.CharField()
    status = serializers.CharField()

    class Meta:
        model = AnalysisTask
        fields = ["id", "name", "owner_name", "task_type", "status", "created_at"]

    def get_name(self, task) -> str:
        parameters = task.input_parameters if isinstance(task.input_parameters, dict) else {}
        return str(parameters.get("name") or task.get_task_type_display())

    def get_owner_name(self, task) -> str:
        return task.owner.get_full_name().strip() or task.owner.get_username()


class AdminOverviewSerializer(serializers.Serializer):
    users = AdminOverviewUserSerializer(many=True)
    datasets = AdminOverviewDatasetSerializer(many=True)
    tasks = AdminOverviewTaskSerializer(many=True)


class AdminOverviewView(APIView):
    permission_classes = [IsPlatformAdministrator]

    @extend_schema(responses=AdminOverviewSerializer)
    def get(self, request):
        user_model = get_user_model()

        def owned_count(model):
            rows = (
                model.objects.filter(owner_id=OuterRef("pk"))
                .order_by()
                .values("owner_id")
                .annotate(total=Count("pk"))
            )
            return Coalesce(
                Subquery(rows.values("total")[:1]), Value(0), output_field=IntegerField()
            )

        users = user_model.objects.annotate(
            dataset_count=owned_count(ResearchDataset),
            case_count=owned_count(MedicalCase),
            task_count=owned_count(AnalysisTask),
        ).order_by("-date_joined", "-id")
        datasets = ResearchDataset.objects.select_related("owner").order_by("-created_at", "-id")[:10]
        tasks = AnalysisTask.objects.select_related("owner").order_by("-created_at", "-id")[:10]
        return Response(
            AdminOverviewSerializer(
                {"users": users, "datasets": datasets, "tasks": tasks}
            ).data
        )
