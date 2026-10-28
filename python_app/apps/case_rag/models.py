from django.db import models


class RagCorpusRelease(models.Model):
    corpus_slug = models.SlugField(max_length=80, default="curated-tcm-cases")
    name = models.CharField(max_length=160)
    version = models.CharField(max_length=120)
    workbook_name = models.CharField(max_length=255)
    checksum_sha256 = models.CharField(max_length=64)
    record_count = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["corpus_slug", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["corpus_slug", "version"], name="uniq_rag_corpus_version"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} · {self.version}"


class CaseCorpusDocument(models.Model):
    class Category(models.TextChoices):
        PULMONARY = "pulmonary", "肺系疾病"
        STROKE = "stroke", "中风"
        STOMACH = "stomach", "胃病"
        PHARYNGITIS = "pharyngitis", "咽炎"
        GENERAL = "general", "综合"

    release = models.ForeignKey(
        RagCorpusRelease, on_delete=models.PROTECT, related_name="documents"
    )
    source_record_id = models.CharField(max_length=160)
    source_sheet = models.CharField(max_length=80)
    source_workbook = models.CharField(max_length=255, blank=True)
    source_workbook_sha256 = models.CharField(max_length=64, blank=True)
    category = models.CharField(max_length=16, choices=Category.choices)
    title = models.CharField(max_length=300)
    source_reference = models.TextField(blank=True)
    source_link = models.TextField(blank=True)
    source_doctor = models.CharField(max_length=160, blank=True)
    original_text = models.TextField()
    structured_data = models.JSONField(default=dict)
    search_text = models.TextField()
    extraction_status = models.CharField(max_length=240, blank=True)
    content_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["source_sheet", "source_record_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["release", "source_record_id"], name="uniq_case_rag_source_record"
            ),
        ]
        indexes = [
            models.Index(fields=["release", "category"], name="case_rag_release_cat_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.title} · {self.source_record_id}"
