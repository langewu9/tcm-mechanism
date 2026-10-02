from django.db import migrations


def seed_pubchem_source(apps, schema_editor):
    DataSource = apps.get_model("core", "DataSource")
    DataSource.objects.using(schema_editor.connection.alias).get_or_create(
        slug="pubchem-compounds",
        defaults={
            "name": "PubChem 化合物属性",
            "description": "通过人工复核的 CID 与本地成分 stableId 映射同步基础化学属性。",
            "access_mode": "api",
            "configuration": {
                "connector": "pubchem-compound-catalog",
                "mappings": [],
            },
            "documentation_url": "https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest",
            "license_note": "使用 PubChem PUG REST；同步前须人工核对 PubChem CID 与本地成分 stableId，并遵守记录中适用的数据来源与引用要求。",
            "enabled": True,
            "refresh_interval_hours": 720,
        },
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0010_entityidentifier")]

    operations = [
        migrations.RunPython(seed_pubchem_source, migrations.RunPython.noop),
    ]
