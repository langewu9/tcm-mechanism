from rest_framework import serializers

from ..models import AnalysisTask, MedicalCase, ResearchDataset


class ResearchDatasetSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResearchDataset
        fields = [
            "id",
            "name",
            "description",
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
            "original_filename",
            "content_sha256",
            "byte_size",
            "created_at",
            "updated_at",
        ]


class MedicalCaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicalCase
        fields = [
            "id",
            "title",
            "deidentified_text",
            "structured_data",
            "research_notes",
            "review_status",
            "reviewed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "review_status", "reviewed_at", "created_at", "updated_at"]


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
