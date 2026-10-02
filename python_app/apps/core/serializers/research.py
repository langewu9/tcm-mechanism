from django.conf import settings
from django.core.files.storage import default_storage
from rest_framework import serializers

from ..exceptions import ResourceConflict
from ..models import AnalysisTask, MedicalCase, MedicalCaseAuditEvent, ResearchDataset


class ResearchDatasetSerializer(serializers.ModelSerializer):
    owner_id = serializers.ReadOnlyField()
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    file = serializers.FileField(write_only=True, required=False)

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
            "columns_mapping",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "owner_id",
            "owner_username",
            "original_filename",
            "content_sha256",
            "byte_size",
            "created_at",
            "updated_at",
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
        if self.instance and "file" in attrs and self.instance.analysis_tasks.exists():
            raise ResourceConflict("数据集已有分析任务，不能替换原始文件；请另存为新数据集。")
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

    def create(self, validated_data):
        upload = validated_data.pop("file")
        storage_key = self._store_upload(validated_data, upload)
        try:
            return ResearchDataset.objects.create(**validated_data)
        except Exception:
            default_storage.delete(storage_key)
            raise

    def update(self, instance, validated_data):
        upload = validated_data.pop("file", None)
        old_storage_key = instance.storage_key
        new_storage_key = self._store_upload(validated_data, upload, instance.owner_id) if upload else None
        try:
            updated = super().update(instance, validated_data)
        except Exception:
            if new_storage_key:
                default_storage.delete(new_storage_key)
            raise
        if new_storage_key and old_storage_key:
            default_storage.delete(old_storage_key)
        return updated


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
        ]
        read_only_fields = ["id", "owner_id", "owner_username", "review_status", "reviewed_at", "reviewed_by_username", "created_at", "updated_at"]


class MedicalCaseAuditEventSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source="actor.username", read_only=True, allow_null=True)

    class Meta:
        model = MedicalCaseAuditEvent
        fields = [
            "id", "case_id_snapshot", "case_title_snapshot", "actor_username", "action",
            "changed_fields", "content_hashes", "metadata", "created_at",
        ]
        read_only_fields = fields


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


class NetworkPharmacologyRequestSerializer(serializers.Serializer):
    herb = serializers.CharField(max_length=1200)
    disease = serializers.CharField(max_length=300)
    limit = serializers.IntegerField(required=False, default=12000, min_value=500, max_value=30000)

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
        return value.strip()


class NetworkPharmacologyResponseSerializer(serializers.Serializer):
    taskId = serializers.IntegerField()
    summary = serializers.JSONField()
    targets = serializers.ListField(child=serializers.JSONField())
    network = serializers.JSONField()
    charts = serializers.JSONField()
    limits = serializers.JSONField()


class ExternalGeneListRequestSerializer(serializers.Serializer):
    targets = serializers.ListField(
        child=serializers.CharField(max_length=120), min_length=2, max_length=500
    )
    consent = serializers.BooleanField()

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
