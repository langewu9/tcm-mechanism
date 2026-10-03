from django.db import models


class ProteomicsRowResult(models.Model):
    class MappingStatus(models.TextChoices):
        DATABASE = "database", "本地知识库精确匹配"
        EXTERNAL = "external", "外部数据库映射"
        UNVERIFIED = "unverified", "未验证的基因符号格式"
        AMBIGUOUS = "ambiguous", "本地标识存在歧义"
        UNMAPPED = "unmapped", "未映射"
        MISSING = "missing", "缺少标识"

    task = models.ForeignKey(
        "core.AnalysisTask", on_delete=models.CASCADE, related_name="proteomics_rows"
    )
    row_index = models.PositiveIntegerField()
    original_label = models.CharField(max_length=500, blank=True)
    protein_name = models.CharField(max_length=500, blank=True)
    normalized_symbol = models.CharField(max_length=160, blank=True)
    external_identifiers = models.JSONField(default=list, blank=True)
    mapping_status = models.CharField(max_length=16, choices=MappingStatus.choices)
    mapping_source = models.CharField(max_length=160, blank=True)
    matched_entity = models.ForeignKey(
        "core.KnowledgeEntity",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proteomics_mapping_rows",
    )
    log2_fold_change = models.FloatField(null=True, blank=True)
    p_value = models.FloatField(null=True, blank=True)
    fdr = models.FloatField(null=True, blank=True)
    direction = models.CharField(max_length=80, blank=True)
    selected = models.BooleanField(default=False)
    exclusion_reasons = models.JSONField(default=list, blank=True)
    qc_warnings = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["row_index"]
        constraints = [
            models.UniqueConstraint(fields=["task", "row_index"], name="uniq_proteomics_task_row")
        ]
        indexes = [
            models.Index(fields=["task", "selected"], name="proteomics_task_selected_idx"),
            models.Index(fields=["task", "normalized_symbol"], name="proteomics_task_symbol_idx"),
        ]

    def __str__(self) -> str:
        return f"task:{self.task_id} row:{self.row_index} {self.original_label}"
