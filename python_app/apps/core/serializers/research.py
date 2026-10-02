from django.conf import settings
from django.core.files.storage import default_storage
from rest_framework import serializers

from ..models import AnalysisTask, MedicalCase, ResearchDataset


class ResearchDatasetSerializer(serializers.ModelSerializer):
    owner_id = serializers.ReadOnlyField()
    owner_username = serializers.ReadOnlyField(source="owner.get_username")
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
    owner_username = serializers.ReadOnlyField(source="owner.get_username")

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
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "owner_id", "owner_username", "review_status", "reviewed_at", "created_at", "updated_at"]


class AnalysisTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalysisTask
        fields = [
            "id",
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
