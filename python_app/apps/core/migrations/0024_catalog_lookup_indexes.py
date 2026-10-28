"""Indexes for exact names and entity-scoped graph traversal; no data rewrite."""

from django.db import migrations, models
from django.db.models.functions import Upper


class Migration(migrations.Migration):
    dependencies = [("core", "0023_master_identity_tables")]

    operations = [
        migrations.AddIndex(
            model_name="knowledgeentity",
            index=models.Index(Upper("label"), models.F("entity_type"), name="entity_exact_name_idx"),
        ),
        migrations.AddIndex(
            model_name="sourceentitymapping",
            index=models.Index(Upper("source_label"), models.F("entity_type"), models.F("status"), name="mapping_exact_name_idx"),
        ),
        migrations.AddIndex(
            model_name="evidencerelation",
            index=models.Index(fields=["subject", "relation_type"], name="evidence_subject_type_idx"),
        ),
        migrations.AddIndex(
            model_name="evidencerelation",
            index=models.Index(fields=["object", "relation_type"], name="evidence_object_type_idx"),
        ),
    ]
