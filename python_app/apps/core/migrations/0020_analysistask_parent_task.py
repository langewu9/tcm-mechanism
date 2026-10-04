from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0019_add_text_analysis_task_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="analysistask",
            name="parent_task",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="derived_tasks",
                to="core.analysistask",
            ),
        ),
    ]
