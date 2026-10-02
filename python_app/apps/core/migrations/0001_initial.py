import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="DataSource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slug", models.SlugField(max_length=80, unique=True)),
                ("name", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True)),
                ("access_mode", models.CharField(choices=[("api", "公开 API"), ("download", "版本文件导入"), ("manual", "人工审核导入")], max_length=16)),
                ("documentation_url", models.URLField(blank=True)),
                ("license_note", models.TextField(blank=True)),
                ("enabled", models.BooleanField(default=True)),
                ("refresh_interval_hours", models.PositiveIntegerField(blank=True, null=True)),
                ("last_success_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="KnowledgeEntity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("entity_type", models.CharField(choices=[("herb", "中药"), ("formula", "方剂"), ("compound", "成分"), ("protein", "蛋白"), ("gene", "基因"), ("disease", "疾病"), ("pathway", "通路")], max_length=16)),
                ("stable_id", models.CharField(max_length=160)),
                ("label", models.CharField(max_length=300)),
                ("organism", models.CharField(blank=True, max_length=120)),
                ("synonyms", models.JSONField(blank=True, default=list)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["entity_type", "label"]},
        ),
        migrations.CreateModel(
            name="MedicalCase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("deidentified_text", models.TextField(help_text="只保存去标识化后的医案文本。")),
                ("structured_data", models.JSONField(blank=True, default=dict)),
                ("research_notes", models.TextField(blank=True)),
                ("review_status", models.CharField(choices=[("draft", "草稿"), ("reviewed", "已审核")], default="draft", max_length=16)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="medical_cases", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-updated_at"]},
        ),
        migrations.CreateModel(
            name="ResearchDataset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("original_filename", models.CharField(blank=True, max_length=255)),
                ("storage_key", models.CharField(blank=True, max_length=500)),
                ("content_sha256", models.CharField(blank=True, max_length=64)),
                ("byte_size", models.PositiveBigIntegerField(default=0)),
                ("columns_mapping", models.JSONField(blank=True, default=dict)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="research_datasets", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="SourceRelease",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version", models.CharField(max_length=120)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("checksum_sha256", models.CharField(blank=True, max_length=64)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("source", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="releases", to="core.datasource")),
            ],
            options={"ordering": ["source__name", "-created_at"]},
        ),
        migrations.CreateModel(
            name="SyncRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("pending", "等待中"), ("running", "运行中"), ("succeeded", "成功"), ("failed", "失败")], default="pending", max_length=16)),
                ("trigger", models.CharField(choices=[("manual", "人工触发"), ("scheduled", "定时任务")], default="manual", max_length=16)),
                ("cursor", models.TextField(blank=True)),
                ("records_seen", models.PositiveBigIntegerField(default=0)),
                ("records_created", models.PositiveBigIntegerField(default=0)),
                ("records_updated", models.PositiveBigIntegerField(default=0)),
                ("records_retired", models.PositiveBigIntegerField(default=0)),
                ("error_summary", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("release", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="sync_runs", to="core.sourcerelease")),
                ("source", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sync_runs", to="core.datasource")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="AnalysisTask",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("task_type", models.CharField(choices=[("proteomics", "蛋白组学"), ("case_link", "医案药理关联"), ("network", "网络药理")], max_length=20)),
                ("status", models.CharField(choices=[("queued", "排队中"), ("running", "运行中"), ("succeeded", "已完成"), ("failed", "失败"), ("cancelled", "已取消")], default="queued", max_length=16)),
                ("input_parameters", models.JSONField(blank=True, default=dict)),
                ("progress", models.PositiveSmallIntegerField(default=0, validators=[django.core.validators.MaxValueValidator(100)])),
                ("result", models.JSONField(blank=True, default=dict)),
                ("error_summary", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("dataset", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="analysis_tasks", to="core.researchdataset")),
                ("medical_case", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="analysis_tasks", to="core.medicalcase")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="analysis_tasks", to=settings.AUTH_USER_MODEL)),
                ("source_releases", models.ManyToManyField(blank=True, related_name="analysis_tasks", to="core.sourcerelease")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="EvidenceRelation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_record_id", models.CharField(max_length=240)),
                ("relation_type", models.CharField(max_length=80)),
                ("evidence_type", models.CharField(max_length=120)),
                ("score", models.DecimalField(blank=True, decimal_places=6, max_digits=10, null=True)),
                ("evidence_text", models.TextField(blank=True)),
                ("organism", models.CharField(blank=True, max_length=120)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("observed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("object", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="incoming_evidence", to="core.knowledgeentity")),
                ("source_release", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="evidence_relations", to="core.sourcerelease")),
                ("subject", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="outgoing_evidence", to="core.knowledgeentity")),
            ],
            options={"ordering": ["subject__label", "relation_type", "object__label"]},
        ),
        migrations.AddConstraint(
            model_name="sourcerelease",
            constraint=models.UniqueConstraint(fields=("source", "version"), name="uniq_source_release_version"),
        ),
        migrations.AddConstraint(
            model_name="knowledgeentity",
            constraint=models.UniqueConstraint(fields=("entity_type", "stable_id"), name="uniq_knowledge_entity_type_id"),
        ),
        migrations.AddConstraint(
            model_name="evidencerelation",
            constraint=models.UniqueConstraint(fields=("source_release", "source_record_id"), name="uniq_release_source_record"),
        ),
        migrations.AddIndex(
            model_name="knowledgeentity",
            index=models.Index(fields=["entity_type", "label"], name="entity_type_label_idx"),
        ),
        migrations.AddIndex(
            model_name="evidencerelation",
            index=models.Index(fields=["relation_type", "evidence_type"], name="evidence_relation_type_idx"),
        ),
        migrations.AddIndex(
            model_name="researchdataset",
            index=models.Index(fields=["owner", "created_at"], name="dataset_owner_created_idx"),
        ),
        migrations.AddIndex(
            model_name="medicalcase",
            index=models.Index(fields=["owner", "updated_at"], name="case_owner_updated_idx"),
        ),
        migrations.AddIndex(
            model_name="analysistask",
            index=models.Index(fields=["owner", "status"], name="task_owner_status_idx"),
        ),
    ]
