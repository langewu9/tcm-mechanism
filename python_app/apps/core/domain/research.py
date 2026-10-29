from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models

from .sources import SourceRelease


class RetainedResearchQuerySet(models.QuerySet):
    def delete(self):
        raise models.ProtectedError("研究资料须保留溯源，请使用归档操作。", list(self[:1]))


class RetainedResearchRecord(models.Model):
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="%(class)s_archived_records",
    )
    objects = RetainedResearchQuerySet.as_manager()

    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        raise models.ProtectedError("研究资料须保留溯源，请使用归档操作。", [self])


class ResearchDataset(RetainedResearchRecord):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="research_datasets"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    original_filename = models.CharField(max_length=255, blank=True)
    storage_key = models.CharField(max_length=500, blank=True)
    content_sha256 = models.CharField(max_length=64, blank=True)
    byte_size = models.PositiveBigIntegerField(default=0)
    row_count = models.PositiveBigIntegerField(default=0)
    columns = models.JSONField(default=list, blank=True)
    columns_mapping = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner", "created_at"], name="dataset_owner_created_idx")]

    def __str__(self) -> str:
        return self.name


class ResearchDatasetRow(models.Model):
    dataset = models.ForeignKey(
        ResearchDataset, on_delete=models.CASCADE, related_name="rows"
    )
    row_index = models.PositiveIntegerField()
    data = models.JSONField()

    class Meta:
        ordering = ["row_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "row_index"], name="dataset_row_index_unique"
            )
        ]

    def __str__(self) -> str:
        return f"数据集 #{self.dataset_id} · 第 {self.row_index + 1} 行"


class MedicalCase(RetainedResearchRecord):
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
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_medical_cases",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner", "updated_at"], name="case_owner_updated_idx")]

    def __str__(self) -> str:
        return self.title


class MedicalCaseCandidate(models.Model):
    class CandidateType(models.TextChoices):
        SYNDROME = "syndrome", "证候"
        FORMULA = "formula", "方剂"

    class MatchStatus(models.TextChoices):
        EXACT = "exact", "已关联规范实体"
        UNMATCHED = "unmatched", "知识库暂无实体"
        AMBIGUOUS = "ambiguous", "多个实体同名"

    class ReviewStatus(models.TextChoices):
        PENDING = "pending", "待研究者确认"
        ACCEPTED = "accepted", "已确认"
        REJECTED = "rejected", "已驳回"

    task = models.ForeignKey(
        "core.AnalysisTask", on_delete=models.CASCADE, related_name="case_candidates"
    )
    medical_case = models.ForeignKey(
        MedicalCase, on_delete=models.PROTECT, related_name="analysis_candidates"
    )
    candidate_type = models.CharField(max_length=12, choices=CandidateType.choices)
    label = models.CharField(max_length=300)
    entity = models.ForeignKey(
        "core.KnowledgeEntity",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="medical_case_candidates",
    )
    match_status = models.CharField(max_length=12, choices=MatchStatus.choices)
    confidence = models.DecimalField(max_digits=5, decimal_places=4)
    rank = models.PositiveSmallIntegerField()
    evidence = models.JSONField(default=list)
    knowledge_evidence = models.JSONField(default=list, blank=True)
    review_status = models.CharField(
        max_length=12, choices=ReviewStatus.choices, default=ReviewStatus.PENDING
    )
    review_note = models.CharField(max_length=1000, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_case_candidates",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["candidate_type", "rank", "id"]
        indexes = [
            models.Index(fields=["task", "candidate_type", "rank"], name="case_candidate_task_idx"),
            models.Index(fields=["medical_case", "review_status"], name="case_candidate_review_idx"),
        ]

    def __str__(self) -> str:
        return f"医案 #{self.medical_case_id} · {self.get_candidate_type_display()} · {self.label}"


class MedicalCaseAuditEvent(models.Model):
    class Action(models.TextChoices):
        CREATED = "created", "创建"
        UPDATED = "updated", "修改"
        REVIEWED = "reviewed", "审核"
        CANDIDATE_REVIEWED = "candidate", "候选确认"
        ANALYSIS_REQUESTED = "analyzed", "启动分析"
        DELETED = "deleted", "删除"
        ARCHIVED = "archived", "归档"
        RESTORED = "restored", "恢复"

    case = models.ForeignKey(
        MedicalCase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    case_id_snapshot = models.PositiveBigIntegerField()
    case_title_snapshot = models.CharField(max_length=200)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="medical_case_audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="medical_case_actions",
    )
    action = models.CharField(max_length=16, choices=Action.choices)
    changed_fields = models.JSONField(default=list, blank=True)
    content_hashes = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["owner", "created_at"], name="case_audit_owner_created_idx"),
            models.Index(fields=["case_id_snapshot", "created_at"], name="case_audit_case_created_idx"),
        ]

    def __str__(self) -> str:
        return f"医案 #{self.case_id_snapshot} · {self.get_action_display()}"


class ResearchDatasetAuditEvent(models.Model):
    class Action(models.TextChoices):
        CREATED = "created", "上传"
        ARCHIVED = "archived", "归档"
        RESTORED = "restored", "恢复"

    dataset = models.ForeignKey(ResearchDataset, on_delete=models.PROTECT, related_name="audit_events")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="dataset_audit_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="dataset_actions")
    action = models.CharField(max_length=16, choices=Action.choices)
    content_sha256 = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class AnalysisTask(models.Model):
    class TaskType(models.TextChoices):
        PROTEOMICS = "proteomics", "蛋白组学"
        CASE_LINK = "case_link", "医案药理关联"
        NETWORK = "network", "网络药理"
        VISUALIZATION = "visualization", "R 图表"
        RESEARCH_ASSISTANT = "research_assistant", "科研助手"
        TEXT_ANALYSIS = "text_analysis", "证候与方药规则分析"

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
    parent_task = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="derived_tasks"
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
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["owner", "status"], name="task_owner_status_idx"),
            models.Index(fields=["owner", "-created_at", "-id"], name="task_owner_created_id_idx"),
            models.Index(fields=["-created_at", "-id"], name="task_created_id_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_task_type_display()} · {self.status}"


class AnalysisSnapshotRow(models.Model):
    """Frozen rows; written by a running task, never edited through API/admin."""
    task = models.ForeignKey(AnalysisTask, on_delete=models.PROTECT, related_name="snapshot_rows")
    table = models.CharField(max_length=40)
    ordinal = models.PositiveIntegerField()
    payload = models.JSONField()

    class Meta:
        ordering = ["ordinal"]
        constraints = [models.UniqueConstraint(fields=["task", "table", "ordinal"], name="snapshot_task_table_row_uniq")]


class VisualizationArtifact(models.Model):
    task = models.ForeignKey(
        AnalysisTask, on_delete=models.PROTECT, related_name="visualization_artifacts"
    )
    render_task = models.ForeignKey(
        AnalysisTask, on_delete=models.PROTECT, related_name="rendered_artifacts"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="visualization_artifacts"
    )
    chart_key = models.CharField(max_length=48)
    file_format = models.CharField(max_length=8)
    filename = models.CharField(max_length=200)
    mime_type = models.CharField(max_length=100)
    storage_key = models.CharField(max_length=500, unique=True)
    content_sha256 = models.CharField(max_length=64)
    input_sha256 = models.CharField(max_length=64)
    byte_size = models.PositiveBigIntegerField()
    renderer_version = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["file_format", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["task", "chart_key", "file_format", "input_sha256"],
                name="uniq_task_chart_artifact_input",
            )
        ]
        indexes = [models.Index(fields=["owner", "created_at"], name="viz_owner_created_idx")]

    def __str__(self) -> str:
        return f"任务 #{self.task_id} · {self.chart_key}.{self.file_format}"
