"""Versioned research data and user-owned work records."""

from django.conf import settings
from django.core.validators import MaxValueValidator
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


class KnowledgeEntity(models.Model):
    class EntityType(models.TextChoices):
        HERB = "herb", "中药"
        FORMULA = "formula", "方剂"
        COMPOUND = "compound", "成分"
        PROTEIN = "protein", "蛋白"
        GENE = "gene", "基因"
        DISEASE = "disease", "疾病"
        PATHWAY = "pathway", "通路"

    entity_type = models.CharField(max_length=16, choices=EntityType.choices)
    stable_id = models.CharField(max_length=160)
    label = models.CharField(max_length=300)
    organism = models.CharField(max_length=120, blank=True)
    synonyms = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["entity_type", "label"]
        constraints = [
            models.UniqueConstraint(
                fields=["entity_type", "stable_id"], name="uniq_knowledge_entity_type_id"
            )
        ]
        indexes = [models.Index(fields=["entity_type", "label"], name="entity_type_label_idx")]

    def __str__(self) -> str:
        return f"{self.get_entity_type_display()}: {self.label} ({self.stable_id})"


class EvidenceRelation(models.Model):
    source_release = models.ForeignKey(
        SourceRelease, on_delete=models.PROTECT, related_name="evidence_relations"
    )
    source_record_id = models.CharField(max_length=240)
    subject = models.ForeignKey(
        KnowledgeEntity, on_delete=models.PROTECT, related_name="outgoing_evidence"
    )
    object = models.ForeignKey(
        KnowledgeEntity, on_delete=models.PROTECT, related_name="incoming_evidence"
    )
    relation_type = models.CharField(max_length=80)
    evidence_type = models.CharField(max_length=120)
    score = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    evidence_text = models.TextField(blank=True)
    organism = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    observed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["subject__label", "relation_type", "object__label"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_release", "source_record_id"], name="uniq_release_source_record"
            )
        ]
        indexes = [
            models.Index(fields=["relation_type", "evidence_type"], name="evidence_relation_type_idx")
        ]

    def __str__(self) -> str:
        return f"{self.subject} —{self.relation_type}→ {self.object}"


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
    task_type = models.CharField(max_length=20, choices=TaskType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    dataset = models.ForeignKey(
        ResearchDataset, on_delete=models.SET_NULL, null=True, blank=True, related_name="analysis_tasks"
    )
    medical_case = models.ForeignKey(
        MedicalCase, on_delete=models.SET_NULL, null=True, blank=True, related_name="analysis_tasks"
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
