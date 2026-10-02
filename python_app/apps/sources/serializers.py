from rest_framework import serializers

from apps.core.models import DataSource, SyncRun


class DataSourceSyncSerializer(serializers.ModelSerializer):
    latest_run_status = serializers.CharField(read_only=True)
    latest_run_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = DataSource
        fields = [
            "id", "slug", "name", "description", "access_mode", "documentation_url",
            "license_note", "enabled", "last_success_at", "latest_run_status", "latest_run_at",
        ]
        read_only_fields = fields


class SyncRunSerializer(serializers.ModelSerializer):
    source_slug = serializers.CharField(source="source.slug", read_only=True)
    source_name = serializers.CharField(source="source.name", read_only=True)
    release_version = serializers.CharField(source="release.version", read_only=True, allow_null=True)
    release_checksum = serializers.CharField(source="release.checksum_sha256", read_only=True, allow_null=True)
    requested_by_username = serializers.CharField(source="requested_by.username", read_only=True, allow_null=True)

    class Meta:
        model = SyncRun
        fields = [
            "id", "source", "source_slug", "source_name", "release", "release_version",
            "release_checksum", "status", "trigger", "records_seen", "records_created",
            "records_updated", "records_retired", "error_summary", "preview_summary",
            "requested_by", "requested_by_username", "started_at", "finished_at", "created_at",
        ]
        read_only_fields = fields


class SyncPreviewRequestSerializer(serializers.Serializer):
    """Empty body accepted to keep this action explicit and extensible."""


class SyncPreviewResponseSerializer(serializers.Serializer):
    run = SyncRunSerializer()


class SyncApplyResponseSerializer(serializers.Serializer):
    run = SyncRunSerializer()
