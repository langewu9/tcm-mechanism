from rest_framework import serializers

from ..models import DataSource, EvidenceRelation, KnowledgeEntity


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
    source_slug = serializers.CharField(source="source_release.source.slug", read_only=True)
    source_version = serializers.CharField(source="source_release.version", read_only=True)

    class Meta:
        model = KnowledgeEntity
        fields = [
            "id",
            "entity_type",
            "stable_id",
            "label",
            "organism",
            "is_active",
            "source_release",
            "canonical_id", "taxon_key", "identity_status",
            "source_slug",
            "source_version",
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
            "is_active",
            "source_slug",
            "source_version",
            "observed_at",
            "source_release",
            "source_record_id",
            "source_record_ref",
        ]
        read_only_fields = fields
