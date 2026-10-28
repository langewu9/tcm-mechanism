import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="RagCorpusRelease",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("corpus_slug", models.SlugField(default="curated-tcm-cases", max_length=80)),
                ("name", models.CharField(max_length=160)),
                ("version", models.CharField(max_length=120)),
                ("workbook_name", models.CharField(max_length=255)),
                ("checksum_sha256", models.CharField(max_length=64)),
                ("record_count", models.PositiveIntegerField(default=0)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["corpus_slug", "-created_at"]},
        ),
        migrations.CreateModel(
            name="CaseCorpusDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_record_id", models.CharField(max_length=160)),
                ("source_sheet", models.CharField(max_length=80)),
                ("category", models.CharField(choices=[("pulmonary", "肺系疾病"), ("stroke", "中风"), ("stomach", "胃病"), ("pharyngitis", "咽炎")], max_length=16)),
                ("title", models.CharField(max_length=300)),
                ("source_reference", models.TextField(blank=True)),
                ("source_link", models.TextField(blank=True)),
                ("source_doctor", models.CharField(blank=True, max_length=160)),
                ("original_text", models.TextField()),
                ("structured_data", models.JSONField(default=dict)),
                ("search_text", models.TextField()),
                ("extraction_status", models.CharField(blank=True, max_length=240)),
                ("content_sha256", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("release", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="documents", to="case_rag.ragcorpusrelease")),
            ],
            options={"ordering": ["source_sheet", "source_record_id"]},
        ),
        migrations.AddConstraint(
            model_name="ragcorpusrelease",
            constraint=models.UniqueConstraint(fields=("corpus_slug", "version"), name="uniq_rag_corpus_version"),
        ),
        migrations.AddConstraint(
            model_name="casecorpusdocument",
            constraint=models.UniqueConstraint(fields=("release", "source_record_id"), name="uniq_case_rag_source_record"),
        ),
        migrations.AddIndex(
            model_name="casecorpusdocument",
            index=models.Index(fields=["release", "category"], name="case_rag_release_cat_idx"),
        ),
    ]
