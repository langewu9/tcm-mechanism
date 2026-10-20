"""Minimal access evidence: identities and record IDs, never research content."""

from django.conf import settings
from django.db import models


class SensitiveAccessEvent(models.Model):
    class Action(models.TextChoices):
        LIST = "list", "列表访问"
        VIEW = "view", "查看"
        DOWNLOAD = "download", "发放文件响应"
        EXPORT = "export", "导出"
        QUOTA_CHANGE = "quota_change", "调整上传配额"

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sensitive_access_events")
    operation = models.CharField(max_length=80)
    action = models.CharField(max_length=16, choices=Action.choices)
    channel = models.CharField(max_length=8, choices=[("api", "业务接口"), ("admin", "管理后台")])
    method = models.CharField(max_length=8)
    status_code = models.PositiveSmallIntegerField()
    request_id = models.UUIDField()
    resources = models.JSONField(default=list)
    resources_truncated = models.BooleanField(default=False)
    quota_changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        default_permissions = ("view",)
        indexes = [
            models.Index(fields=["actor", "-created_at", "-id"], name="access_actor_created_idx"),
            models.Index(fields=["-created_at", "-id"], name="access_created_idx"),
        ]

    def __str__(self):
        return f"{self.actor_id} · {self.operation} · {self.request_id}"


class ResearchUploadQuota(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="upload_quota")
    storage_limit_mib = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="累计容量上限（MiB）",
        help_text="留空使用平台默认值；1024 MiB = 1 GiB；0 表示不再接受新上传。归档文件仍占用容量。",
    )
    dataset_limit = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="累计数据集数量上限",
        help_text="留空使用平台默认值；0 表示不再接受新上传。调低额度不会删除已有数据。",
    )
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="upload_quota_changes")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "研究资料上传额度"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"用户 #{self.user_id} 的上传额度"
