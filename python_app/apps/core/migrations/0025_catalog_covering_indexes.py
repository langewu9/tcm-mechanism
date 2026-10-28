from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0024_catalog_lookup_indexes")]
    operations = [
        migrations.AddIndex(model_name="evidencerelation", index=models.Index(
            fields=["subject", "relation_type", "is_active", "object", "source_release"], name="evidence_subject_cover_idx")),
        migrations.AddIndex(model_name="evidencerelation", index=models.Index(
            fields=["object", "relation_type", "is_active", "subject", "source_release"], name="evidence_object_cover_idx")),
    ]
