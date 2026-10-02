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
    documentation_url = models.URLField(blank=True)
    license_note = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    refresh_interval_hours = models.PositiveIntegerField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
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
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.source.slug} · {self.status} · {self.created_at:%Y-%m-%d %H:%M}"
