from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0021_unique_user_email")]
    operations = [
        migrations.AddField(
            model_name="datasource", name="last_preview_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
