from django.db import migrations, models


def seed_string_crosswalk_source(apps, schema_editor):
    DataSource = apps.get_model("core", "DataSource")
    manager = DataSource.objects.using(schema_editor.connection.alias)
    source, _ = manager.get_or_create(
        slug="string",
        defaults={
            "name": "STRING 人类标识映射与互作服务",
            "description": "提供经版本记录的 STRING 人类蛋白标识映射和用户主动请求的互作分析。标识同步只关联本地已有实体，不下载或创建完整蛋白目录。",
            "access_mode": "api",
            "configuration": {"connector": "string-human-identifier-crosswalk"},
            "documentation_url": "https://string-db.org/help/api/",
            "license_note": "同步前请核对 STRING 当前许可和引用要求。标识匹配仅供研究检索，不代表实体同一性或因果关系。",
            "enabled": True,
            "refresh_interval_hours": 720,
        },
    )
    configuration = source.configuration if isinstance(source.configuration, dict) else {}
    update_fields = []
    if not configuration.get("connector"):
        source.configuration = {**configuration, "connector": "string-human-identifier-crosswalk"}
        update_fields.append("configuration")
    if source.name == "STRING":
        source.name = "STRING 人类标识映射与互作服务"
        update_fields.append("name")
    if "标识映射" not in source.description:
        source.description = (
            source.description.strip()
            + " 本平台还提供版本化 STRING 人类标识映射，仅关联本地已有实体，不下载或创建完整蛋白目录。"
        ).strip()
        update_fields.append("description")
    if update_fields:
        source.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [("core", "0012_remove_entityidentifier_uniq_uniprot_accession_identifier_and_more")]

    operations = [
        migrations.RemoveConstraint(
            model_name="entityidentifier",
            name="uniq_global_external_identifier",
        ),
        migrations.AddConstraint(
            model_name="entityidentifier",
            constraint=models.UniqueConstraint(
                condition=models.Q(namespace__in=["uniprot", "pubchem", "string"]),
                fields=("namespace", "identifier"),
                name="uniq_global_external_identifier",
            ),
        ),
        migrations.RunPython(seed_string_crosswalk_source, migrations.RunPython.noop),
    ]
