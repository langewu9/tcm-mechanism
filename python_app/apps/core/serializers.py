from rest_framework import serializers

from .models import (
    AnalysisTask,
    DataSource,
    EvidenceRelation,
    KnowledgeEntity,
    MedicalCase,
    ResearchDataset,
)


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


class DataSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataSource
        fields = [
            "id",
            "slug",
            "name",
            "description",
            "access_mode",
            "documentation_url",
            "license_note",
            "enabled",
            "refresh_interval_hours",
            "last_success_at",
        ]
        read_only_fields = fields


class KnowledgeEntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeEntity
        fields = [
            "id",
            "entity_type",
            "stable_id",
            "label",
            "organism",
            "synonyms",
            "metadata",
        ]
        read_only_fields = fields


class EvidenceRelationSerializer(serializers.ModelSerializer):
    subject_label = serializers.CharField(source="subject.label", read_only=True)
    object_label = serializers.CharField(source="object.label", read_only=True)
    source_slug = serializers.CharField(source="source_release.source.slug", read_only=True)
    source_version = serializers.CharField(source="source_release.version", read_only=True)

    class Meta:
        model = EvidenceRelation
        fields = [
            "id",
            "subject",
            "subject_label",
            "object",
            "object_label",
            "relation_type",
            "evidence_type",
            "score",
            "evidence_text",
            "organism",
            "source_slug",
            "source_version",
            "observed_at",
        ]
        read_only_fields = fields
