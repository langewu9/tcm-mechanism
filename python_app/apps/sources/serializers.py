from rest_framework import serializers

from apps.core.models import DataSource, SyncRun
from apps.sources.connectors.sqlite_tcm import SQLiteSourceError, validate_sqlite_source_config
from apps.sources.sqlite_sync import SQLITE_CONNECTOR


class DataSourceSyncSerializer(serializers.ModelSerializer):
    latest_run_status = serializers.CharField(read_only=True, allow_null=True, default=None)
    latest_run_at = serializers.DateTimeField(read_only=True, allow_null=True, default=None)
    connector_type = serializers.SerializerMethodField()

    class Meta:
        model = DataSource
        fields = [
            "id", "slug", "name", "description", "access_mode", "documentation_url",
            "license_note", "enabled", "last_success_at", "latest_run_status", "latest_run_at", "connector_type",
        ]
        read_only_fields = fields

    def get_connector_type(self, obj) -> str:
        return (obj.configuration or {}).get("connector") or ("reactome-catalog" if obj.slug == "reactome" else "")


class SQLiteSourceCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    description = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    databaseFile = serializers.CharField(max_length=300)
    table = serializers.CharField(max_length=80)
    herbColumn = serializers.CharField(max_length=80)
    compoundColumn = serializers.CharField(max_length=80)
    targetColumn = serializers.CharField(max_length=80)
    diseaseTargetTable = serializers.CharField(max_length=80, required=False, allow_blank=True)
    diseaseColumn = serializers.CharField(max_length=80, required=False, allow_blank=True)
    diseaseTargetColumn = serializers.CharField(max_length=80, required=False, allow_blank=True)
    diseaseSourceColumn = serializers.CharField(max_length=80, required=False, allow_blank=True)
    diseaseHerbTargetTable = serializers.CharField(max_length=80, required=False, allow_blank=True)
    diseaseHerbColumn = serializers.CharField(max_length=80, required=False, allow_blank=True)
    diseaseHerbHerbColumn = serializers.CharField(max_length=80, required=False, allow_blank=True)
    diseaseHerbTargetColumn = serializers.CharField(max_length=80, required=False, allow_blank=True)

    def validate(self, attrs):
        try:
            validate_sqlite_source_config({**attrs, "connector": SQLITE_CONNECTOR})
        except SQLiteSourceError as exc:
            raise serializers.ValidationError({"databaseFile": str(exc)}) from exc
        return attrs


class SQLiteSourceTestResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    rowCount = serializers.IntegerField()
    fileBytes = serializers.IntegerField()
    checksumSha256 = serializers.CharField()
    columns = serializers.ListField(child=serializers.CharField())
    mapping = serializers.JSONField()
    tableRowCounts = serializers.JSONField()


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
