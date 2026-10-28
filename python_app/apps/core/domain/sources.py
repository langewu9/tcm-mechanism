from django.conf import settings
from django.db import models

class DataSource(models.Model):
    class AccessMode(models.TextChoices):
        API = "api", "公开 API"
        DOWNLOAD = "download", "版本文件导入"
        MANUAL = "manual", "人工审核导入"

    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    access_mode = models.CharField(max_length=16, choices=AccessMode.choices)
    configuration = models.JSONField(default=dict, blank=True)
    documentation_url = models.URLField(blank=True)
    license_note = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    refresh_interval_hours = models.PositiveIntegerField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_preview_requested_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class SourceRelease(models.Model):
    source = models.ForeignKey(DataSource, on_delete=models.PROTECT, related_name="releases")
    version = models.CharField(max_length=120)
    published_at = models.DateTimeField(null=True, blank=True)
    checksum_sha256 = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["source__name", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["source", "version"], name="uniq_source_release_version")
        ]

    def __str__(self) -> str:
        return f"{self.source.slug}:{self.version}"


class SyncRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "等待中"
        RUNNING = "running", "运行中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"

    class Trigger(models.TextChoices):
        MANUAL = "manual", "人工触发"
        SCHEDULED = "scheduled", "定时任务"

    source = models.ForeignKey(DataSource, on_delete=models.PROTECT, related_name="sync_runs")
    release = models.ForeignKey(
        SourceRelease, on_delete=models.PROTECT, null=True, blank=True, related_name="sync_runs"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    trigger = models.CharField(max_length=16, choices=Trigger.choices, default=Trigger.MANUAL)
    cursor = models.TextField(blank=True)
    records_seen = models.PositiveBigIntegerField(default=0)
    records_created = models.PositiveBigIntegerField(default=0)
    records_updated = models.PositiveBigIntegerField(default=0)
    records_retired = models.PositiveBigIntegerField(default=0)
    error_summary = models.TextField(blank=True)
    preview_summary = models.JSONField(default=dict, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="source_sync_runs",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.source.slug} · {self.status} · {self.created_at:%Y-%m-%d %H:%M}"


class SourceRecord(models.Model):
    """Immutable raw-row identity within an explicitly versioned source."""
    source_release = models.ForeignKey(SourceRelease, on_delete=models.PROTECT, related_name="raw_records")
    source_record_id = models.CharField(max_length=240)
    payload_sha256 = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=24, choices=[("accepted", "已接收"), ("quarantined", "待核查")])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source_release", "source_record_id"], name="uniq_master_raw_record")]
