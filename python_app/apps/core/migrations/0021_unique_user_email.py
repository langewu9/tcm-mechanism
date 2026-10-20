"""Enforce email identity without replacing the existing Django auth model."""
from django.conf import settings
from django.db import migrations

INDEX_NAME = "tcm_unique_nonblank_user_email"


def add_index(apps, schema_editor):
    if schema_editor.connection.vendor not in {"sqlite", "postgresql"}:
        raise RuntimeError("Email identity migration supports SQLite and PostgreSQL only.")
    user = apps.get_model(settings.AUTH_USER_MODEL)
    quote = schema_editor.quote_name
    table = quote(user._meta.db_table)
    email = quote(user._meta.get_field("email").column)
    pk = quote(user._meta.pk.column)
    expression = f"LOWER(TRIM({email}))"
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"SELECT MIN({pk}), COUNT(*) FROM {table} WHERE TRIM({email}) <> '' "
            f"GROUP BY {expression} HAVING COUNT(*) > 1 LIMIT 10"
        )
        duplicates = cursor.fetchall()
    if duplicates:
        raise RuntimeError(
            "Duplicate normalized user emails: (first user ID, count)="
            f"{duplicates}. Review accounts manually before migrating; no records were changed."
        )
    schema_editor.execute(
        f"CREATE UNIQUE INDEX {quote(INDEX_NAME)} ON {table} ({expression}) "
        f"WHERE TRIM({email}) <> ''"
    )


def drop_index(apps, schema_editor):
    schema_editor.execute(f"DROP INDEX {schema_editor.quote_name(INDEX_NAME)}")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0020_analysistask_parent_task"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    if settings.AUTH_USER_MODEL == "auth.User":
        dependencies.append(("auth", "0012_alter_user_first_name_max_length"))
    operations = [migrations.RunPython(add_index, drop_index)]
