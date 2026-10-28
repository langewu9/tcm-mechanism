from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from rest_framework import serializers

from ..exceptions import ResourceConflict
from ..models import AnalysisTask, MedicalCase, MedicalCaseAuditEvent, MedicalCaseCandidate, ResearchDataset, ResearchDatasetAuditEvent, ResearchDatasetRow

DATASET_ROW_STORAGE_LIMIT = 5000


class ResearchDatasetSerializer(serializers.ModelSerializer):
    owner_id = serializers.ReadOnlyField()
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    file = serializers.FileField(write_only=True, required=False)
    rows = serializers.SerializerMethodField()

    class Meta:
        model = ResearchDataset
        fields = [
            "id",
            "owner_id",
            "owner_username",
            "name",
            "description",
            "file",
            "original_filename",
            "content_sha256",
            "byte_size",
            "row_count",
            "columns",
            "columns_mapping",
            "metadata",
            "rows",
            "created_at",
            "updated_at",
            "archived_at",
            "archived_by",
        ]
        read_only_fields = [
            "id",
            "owner_id",
            "owner_username",
            "original_filename",
            "content_sha256",
            "byte_size",
            "row_count",
            "columns",
            "created_at",
            "updated_at",
            "archived_at",
            "archived_by",
        ]

    def get_fields(self):
        fields = super().get_fields()
        view = self.context.get("view")
        action = getattr(view, "action", None)
        if action not in {"create", "retrieve"}:
            fields.pop("rows", None)
        return fields

    def get_rows(self, obj):
        view = self.context.get("view")
        limit = 25 if getattr(view, "action", None) == "create" else 100
        return [
            {"row_index": row.row_index, "data": row.data}
            for row in obj.rows.order_by("row_index")[:limit]
        ]

    def validate_file(self, upload):
        if upload.size == 0:
            raise serializers.ValidationError("文件为空，请选择包含数据的文件。")
        extension = upload.name.lower().rsplit(".", 1)[-1] if "." in upload.name else ""
        if extension not in {"csv", "tsv", "xls", "xlsx"}:
            raise serializers.ValidationError("仅支持 CSV、TSV、XLS 和 XLSX 文件。")
        if upload.size > settings.DATASET_UPLOAD_MAX_BYTES:
            max_mb = settings.DATASET_UPLOAD_MAX_BYTES // (1024 * 1024)
            raise serializers.ValidationError(f"文件不能超过 {max_mb} MB。")
        return upload

    def validate(self, attrs):
        if self.instance is None and "file" not in attrs:
            raise serializers.ValidationError({"file": "请上传 CSV 或 Excel 文件。"})
        if self.instance and "file" in attrs:
            raise ResourceConflict("原始文件须保留溯源，不能替换；请上传为新数据集。")
        return attrs

    def _store_upload(self, validated_data, upload, owner_id=None):
        from ..services.dataset_uploads import store_dataset_upload

        metadata = dict(validated_data.pop("metadata", {}) or {})
        owner_id = owner_id or validated_data["owner"].pk
        stored = store_dataset_upload(upload, owner_id)
        metadata.update(
            {
                "content_type": getattr(upload, "content_type", "") or "application/octet-stream",
                "checksum_algorithm": "sha256",
            }
        )
        validated_data.update(stored, metadata=metadata)
        return stored["storage_key"]

    @transaction.atomic
    def create(self, validated_data):
        from ..services.upload_quota import check_locked_upload_quota

        upload = validated_data.pop("file")
        check_locked_upload_quota(validated_data["owner"].pk, upload.size)
        storage_key = self._store_upload(validated_data, upload)
        try:
            parsed = self._parse_table(storage_key, validated_data["original_filename"])
            validated_data["row_count"] = len(parsed.rows)
            validated_data["columns"] = parsed.columns
            with transaction.atomic():
                dataset = ResearchDataset.objects.create(**validated_data)
                ResearchDatasetRow.objects.bulk_create(
                    [
                        ResearchDatasetRow(dataset=dataset, row_index=index, data=row)
                        for index, row in enumerate(parsed.rows[:DATASET_ROW_STORAGE_LIMIT])
                    ],
                    batch_size=1000,
                )
            return dataset
        except serializers.ValidationError:
            default_storage.delete(storage_key)
            raise
        except Exception:
            default_storage.delete(storage_key)
            raise

    @staticmethod
    def _parse_table(storage_key, filename):
        from apps.proteomics.exceptions import ProteomicsInputError
        from apps.proteomics.services import parse_dataset_table

        try:
            return parse_dataset_table(storage_key, filename)
        except ProteomicsInputError as exc:
            raise serializers.ValidationError({"file": str(exc)}) from exc

    def update(self, instance, validated_data):
        if "file" in validated_data:
            raise ResourceConflict("原始文件须保留溯源，不能替换；请上传为新数据集。")
        return super().update(instance, validated_data)


class MedicalCaseSerializer(serializers.ModelSerializer):
    owner_id = serializers.ReadOnlyField()
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    reviewed_by_username = serializers.CharField(source="reviewed_by.username", read_only=True, allow_null=True)

    class Meta:
        model = MedicalCase
        fields = [
            "id",
            "owner_id",
            "owner_username",
            "title",
            "deidentified_text",
            "structured_data",
            "source_reference",
            "research_notes",
            "review_status",
            "reviewed_at",
            "reviewed_by_username",
            "created_at",
            "updated_at",
            "archived_at",
            "archived_by",
        ]
        read_only_fields = ["id", "owner_id", "owner_username", "review_status", "reviewed_at", "reviewed_by_username", "created_at", "updated_at", "archived_at", "archived_by"]


class ResearchDatasetAuditEventSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source="actor.username", read_only=True)
    dataset_id = serializers.ReadOnlyField()

    class Meta:
        model = ResearchDatasetAuditEvent
        fields = ["id", "dataset_id", "actor_username", "action", "content_sha256", "created_at"]
        read_only_fields = fields


class MedicalCaseAuditEventSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source="actor.username", read_only=True, allow_null=True)

    class Meta:
        model = MedicalCaseAuditEvent
        fields = [
            "id", "case_id_snapshot", "case_title_snapshot", "actor_username", "action",
            "changed_fields", "content_hashes", "metadata", "created_at",
        ]
        read_only_fields = fields


class MedicalCaseCandidateSerializer(serializers.ModelSerializer):
    entity_stable_id = serializers.CharField(source="entity.stable_id", read_only=True, allow_null=True)
    entity_label = serializers.CharField(source="entity.label", read_only=True, allow_null=True)
    reviewed_by_username = serializers.CharField(source="reviewed_by.username", read_only=True, allow_null=True)

    class Meta:
        model = MedicalCaseCandidate
        fields = [
            "id", "task_id", "medical_case_id", "candidate_type", "label", "entity_id",
            "entity_stable_id", "entity_label", "match_status", "confidence", "rank",
            "evidence", "knowledge_evidence", "review_status", "review_note", "reviewed_by_username", "reviewed_at", "created_at",
        ]
        read_only_fields = fields


class CaseAnalysisRequestSerializer(serializers.Serializer):
    confirmLocalModel = serializers.BooleanField()

    def validate_confirmLocalModel(self, value):
        if not value:
            raise serializers.ValidationError("请确认医案已脱敏，并同意将本次内容提交给平台配置的本地模型。")
        return value


class CaseCandidateReviewRequestSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["accept", "reject"])
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class VisualizationRequestSerializer(serializers.Serializer):
    chartKey = serializers.ChoiceField(choices=[
        "overlap", "components", "pathways", "proteomics_summary", "proteomics_top_nodes",
        "proteomics_go_kegg_enrichment", "proteomics_volcano",
        "ppi_network", "ppi_degree", "evidence_network", "gene_pathway_network",
        "gene_pathway_distribution", "proteomics_go_kegg_bar", "reactome_enrichment",
        "catalog_summary", "catalog_degree",
    ])


class ResearchAssistantRequestSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=2000, trim_whitespace=True)
    entityIds = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=0, max_length=8
    )
    useModel = serializers.BooleanField(default=False)
    caseIds = serializers.ListField(child=serializers.IntegerField(min_value=1), max_length=4, required=False, default=list)
    caseCategory = serializers.ChoiceField(choices=["", "pulmonary", "stroke", "stomach", "pharyngitis", "general"], required=False, default="")
    confirmModelSharing = serializers.BooleanField(default=False)

    def validate(self, attrs):
        if attrs["useModel"] and not attrs["confirmModelSharing"]:
            raise serializers.ValidationError({
                "confirmModelSharing": "请先确认本次问题、所选知识记录及检索到的医案片段可以发送到已配置的本机/内网模型。"
            })
        if any(ord(character) < 32 and character not in "\n\r\t" for character in attrs["question"]):
            raise serializers.ValidationError({"question": "问题中包含不支持的控制字符。"})
        return attrs


class DashboardTaskSerializer(serializers.ModelSerializer):
    title = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    task_type = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)

    class Meta:
        model = AnalysisTask
        fields = ["id", "title", "summary", "task_type", "status", "created_at"]
        read_only_fields = fields

    def get_title(self, obj) -> str:
        parameters = obj.input_parameters if isinstance(obj.input_parameters, dict) else {}
        return str(parameters.get("name") or obj.get_task_type_display())

    def get_summary(self, obj) -> str:
        result = obj.result if isinstance(obj.result, dict) else {}
        summary = result.get("summary")
        if isinstance(summary, str):
            return summary
        if isinstance(summary, dict):
            values = [str(value) for value in summary.values() if value not in (None, "")]
            return " · ".join(values[:4])
        if obj.status == AnalysisTask.Status.FAILED and obj.error_summary:
            return obj.error_summary
        return "任务已保存，等待查看结果。"


class DashboardStatsSerializer(serializers.Serializer):
    datasets = serializers.IntegerField()
    cases = serializers.IntegerField()
    tasks = serializers.IntegerField()
    herbs = serializers.IntegerField()
    compounds = serializers.IntegerField()
    targets = serializers.IntegerField()
    pathways = serializers.IntegerField()


class ResearchDashboardSerializer(serializers.Serializer):
    stats = DashboardStatsSerializer()
    latest_tasks = DashboardTaskSerializer(many=True)


class AnalysisTaskSerializer(serializers.ModelSerializer):
    owner_id = serializers.ReadOnlyField()
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    requested_by_id = serializers.ReadOnlyField(source="created_by_id")
    requested_by_username = serializers.CharField(
        source="created_by.username", read_only=True, allow_null=True
    )

    class Meta:
        model = AnalysisTask
        fields = [
            "id",
            "owner_id",
            "owner_username",
            "requested_by_id",
            "requested_by_username",
            "task_type",
            "status",
            "dataset",
            "medical_case",
            "parent_task",
            "input_parameters",
            "source_releases",
            "progress",
            "result",
            "error_summary",
            "created_at",
            "started_at",
            "finished_at",
        ]
        read_only_fields = fields


class AnalysisTaskSummarySerializer(serializers.ModelSerializer):
    """List metadata only; full parameters, evidence and results stay in detail."""

    owner_id = serializers.ReadOnlyField()
    task_type = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    requested_by_id = serializers.ReadOnlyField(source="created_by_id")
    display_parameters = serializers.JSONField(source="list_display_parameters", read_only=True)

    class Meta:
        model = AnalysisTask
        fields = [
            "id", "owner_id", "owner_username", "requested_by_id", "task_type", "status",
            "dataset", "medical_case", "parent_task", "display_parameters", "progress",
            "error_summary", "created_at", "started_at", "finished_at",
        ]
        read_only_fields = fields


class NetworkPharmacologyRequestSerializer(serializers.Serializer):
    herb = serializers.CharField(max_length=1200)
    disease = serializers.CharField(max_length=300)
    limit = serializers.IntegerField(required=False, default=12000, min_value=500, max_value=30000)
    source_case_id = serializers.IntegerField(required=False, min_value=1)
    source_candidate_id = serializers.IntegerField(required=False, min_value=1)

    def validate(self, attrs):
        if bool(attrs.get("source_case_id")) != bool(attrs.get("source_candidate_id")):
            raise serializers.ValidationError("关联医案分析时必须同时提交医案和候选方剂 ID。")
        return attrs

    def validate_herb(self, value):
        from apps.core.services.network_pharmacology import parse_herb_names

        names = parse_herb_names(value)
        if not names:
            raise serializers.ValidationError("请输入至少一味中药。")
        if len(names) > 12:
            raise serializers.ValidationError("一次最多分析 12 味中药。")
        return value

    def validate_disease(self, value):
        if not value.strip():
            raise serializers.ValidationError("请输入疾病名称。")
        if any(ord(character) < 32 for character in value):
            raise serializers.ValidationError("疾病名称包含不支持的控制字符。")
        return value.strip()


class NetworkPharmacologyResponseSerializer(serializers.Serializer):
    dataQuality = serializers.JSONField(required=False)
    targetIdentity = serializers.JSONField(required=False)
    taskId = serializers.IntegerField()
    summary = serializers.JSONField()
    targets = serializers.ListField(child=serializers.JSONField())
    raw = serializers.JSONField()
    rawLimits = serializers.JSONField()
    network = serializers.JSONField()
    charts = serializers.JSONField()
    limits = serializers.JSONField()


class ExternalGeneListRequestSerializer(serializers.Serializer):
    targets = serializers.ListField(
        child=serializers.CharField(max_length=120), min_length=2, max_length=500, required=False
    )
    source_task_id = serializers.IntegerField(required=False, min_value=1)
    consent = serializers.BooleanField()

    def validate(self, attrs):
        if "targets" not in attrs and "source_task_id" not in attrs:
            raise serializers.ValidationError({"targets": "请提供基因标识，或关联已完成的本地网络药理任务。"})
        return attrs

    def validate_consent(self, value):
        if not value:
            raise serializers.ValidationError("请明确同意将基因标识发送至所选外部数据库。")
        return value

    def validate_targets(self, values):
        unique = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if len(unique) < 2:
            raise serializers.ValidationError("至少需要 2 个非空基因/蛋白标识。")
        return unique


class ReactomeEnrichmentResponseSerializer(serializers.Serializer):
    taskId = serializers.IntegerField()
    result = serializers.JSONField()


class StringNetworkRequestSerializer(ExternalGeneListRequestSerializer):
    required_score = serializers.IntegerField(required=False, default=700, min_value=0, max_value=1000)
