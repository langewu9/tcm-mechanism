from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models

from .sources import SourceRelease

class ResearchDataset(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="research_datasets"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    original_filename = models.CharField(max_length=255, blank=True)
    storage_key = models.CharField(max_length=500, blank=True)
    content_sha256 = models.CharField(max_length=64, blank=True)
    byte_size = models.PositiveBigIntegerField(default=0)
    columns_mapping = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner", "created_at"], name="dataset_owner_created_idx")]

    def __str__(self) -> str:
        return self.name


class MedicalCase(models.Model):
    class ReviewStatus(models.TextChoices):
        DRAFT = "draft", "草稿"
        REVIEWED = "reviewed", "已审核"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="medical_cases"
    )
    title = models.CharField(max_length=200)
    deidentified_text = models.TextField(help_text="只保存去标识化后的医案文本。")
    structured_data = models.JSONField(default=dict, blank=True)
    source_reference = models.CharField(max_length=500, blank=True, help_text="文献、病例集或其他可核查来源。")
    research_notes = models.TextField(blank=True)
    review_status = models.CharField(
        max_length=16, choices=ReviewStatus.choices, default=ReviewStatus.DRAFT
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner", "updated_at"], name="case_owner_updated_idx")]

    def __str__(self) -> str:
        return self.title


class AnalysisTask(models.Model):
    class TaskType(models.TextChoices):
        PROTEOMICS = "proteomics", "蛋白组学"
        CASE_LINK = "case_link", "医案药理关联"
        NETWORK = "network", "网络药理"

    class Status(models.TextChoices):
        QUEUED = "queued", "排队中"
        RUNNING = "running", "运行中"
        SUCCEEDED = "succeeded", "已完成"
        FAILED = "failed", "失败"
        CANCELLED = "cancelled", "已取消"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="analysis_tasks"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_analysis_tasks",
    )
    task_type = models.CharField(max_length=20, choices=TaskType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    dataset = models.ForeignKey(
        ResearchDataset, on_delete=models.PROTECT, null=True, blank=True, related_name="analysis_tasks"
    )
    medical_case = models.ForeignKey(
        MedicalCase, on_delete=models.PROTECT, null=True, blank=True, related_name="analysis_tasks"
    )
    input_parameters = models.JSONField(default=dict, blank=True)
    source_releases = models.ManyToManyField(SourceRelease, blank=True, related_name="analysis_tasks")
    progress = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(100)])
    result = models.JSONField(default=dict, blank=True)
    error_summary = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner", "status"], name="task_owner_status_idx")]

    def __str__(self) -> str:
        return f"{self.get_task_type_display()} · {self.status}"
