"""Read-only identity inventory of one already imported local preview source.

This describes recorded evidence and same-name candidates. It neither verifies
biology nor merges entities, infers species or calls external services.
"""
import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
VAR = ROOT / "python_app" / "var"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", type=int, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "python_app"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()
    from django.conf import settings
    from django.db import connection
    from django.db.models import Prefetch
    from apps.core.models import DataSource, EntityIdentifier, KnowledgeEntity
    from apps.sources.uniprot_identity import canonical

    if not settings.DEBUG or connection.vendor != "sqlite":
        parser.error("This audit is restricted to the local DEBUG SQLite preview.")
    # Enforce read-only at the database connection, including accidental ORM writes.
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA query_only = ON")
    source = DataSource.objects.get(pk=args.source_id)
    entities = KnowledgeEntity.objects.filter(
        source_release__source=source, is_active=True, entity_type__in=["protein", "gene"],
    ).select_related("source_release").prefetch_related(Prefetch(
        "identifiers", queryset=EntityIdentifier.objects.filter(
            is_active=True, source_release__source__enabled=True,
        ).select_related("source_release__source"),
    )).order_by("id")
    rows, names = [], defaultdict(list)
    for entity in entities:
        metadata = entity.metadata if isinstance(entity.metadata, dict) else {}
        row = {
            "entityId": entity.pk, "stableId": entity.stable_id, "label": entity.label,
            "entityType": entity.entity_type, "organism": entity.organism,
            "identifierStatus": metadata.get("identifierStatus", "not_recorded"),
            "symbol": metadata.get("symbol") or metadata.get("gene_symbol") or metadata.get("geneSymbol"),
            "sourceReleaseId": entity.source_release_id, "sourceVersion": entity.source_release.version,
            "externalIdentifiers": [{"namespace": item.namespace, "identifier": item.identifier,
                                     "sourceReleaseId": item.source_release_id,
                                     "source": item.source_release.source.slug,
                                     "sourceVersion": item.source_release.version} for item in entity.identifiers.all()],
        }
        rows.append(row)
        names[canonical(entity.label)].append(entity.pk)
    report = {
        "scope": "local imported catalogue; recorded evidence only", "sourceId": source.pk,
        "sourceSlug": source.slug, "sourceEnabled": source.enabled, "entityCount": len(rows),
        "unknownSpeciesCount": sum(not row["organism"].strip() for row in rows),
        "identifierStatusCounts": dict(Counter(row["identifierStatus"] for row in rows)),
        "withoutActiveExternalIdentifierCount": sum(not row["externalIdentifiers"] for row in rows),
        "sameNameCandidates": [{"canonicalLabel": name, "entityIds": ids}
                               for name, ids in names.items() if len(ids) > 1],
        "externalCalls": False, "databaseWrites": False, "rows": rows,
    }
    destination = VAR / f"catalogue-identity-source-{source.pk}.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, ensure_ascii=False, indent=2))
    print(f"Report: {destination}")


if __name__ == "__main__":
    main()
