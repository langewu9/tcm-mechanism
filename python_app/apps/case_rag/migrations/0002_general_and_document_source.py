from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("case_rag", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="casecorpusdocument", name="source_workbook",
            field=models.CharField(max_length=255, blank=True),
        ),
        migrations.AddField(
            model_name="casecorpusdocument", name="source_workbook_sha256",
            field=models.CharField(max_length=64, blank=True),
        ),
        migrations.AlterField(
            model_name="casecorpusdocument", name="category",
            field=models.CharField(max_length=16, choices=[
                ("pulmonary", "肺系疾病"), ("stroke", "中风"), ("stomach", "胃病"),
                ("pharyngitis", "咽炎"), ("general", "综合"),
            ]),
        ),
    ]
