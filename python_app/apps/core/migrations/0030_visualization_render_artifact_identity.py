from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0029_merge_platform_and_snapshots")]

    operations = [
        migrations.RemoveConstraint(
            model_name="visualizationartifact",
            name="uniq_task_chart_artifact_input",
        ),
        migrations.AddConstraint(
            model_name="visualizationartifact",
            constraint=models.UniqueConstraint(
                fields=("render_task", "file_format"),
                name="uniq_render_artifact_format",
            ),
        ),
    ]
