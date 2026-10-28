"""Explicit, restartable local imports. No scheduler, network or model access.

Two streaming passes avoid loading millions of rows into RAM. Batches remain
inactive until a full count/checksum audit succeeds; publication is atomic.
"""
from collections import Counter, defaultdict
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from apps.core.models import (CanonicalIdentifier, DataSource, EntityIdentifier,
    EvidenceRelation, KnowledgeEntity, SourceEntityMapping, SourceRecord, SourceRelease, SyncRun)
from .legacy_workbooks import SOURCES, normalize_row, sha256_file, workbook_indexed_rows
from .master_identity import identity_key

PARSER_VERSION = "local-workbooks-master-v1"
BATCH_SIZE = 2000


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _key_tuple(key):
    return tuple(key[name] for name in ("entity_type", "namespace", "identifier", "taxon_key", "scope"))


def _reference(ref, source, certified):
    # Species can only be lifted from an exact accession in a versioned,
    # active, reviewed catalog. Never infer human from a name/symbol.
    if ref.namespace.upper() == "UNIPROT" and ref.identifier in certified:
        ref = replace(ref, taxon_key=certified[ref.identifier])
    key, method = identity_key(entity_type=ref.entity_type, namespace=ref.namespace,
        identifier=ref.identifier, taxon_key=ref.taxon_key, source=source)
    return ref, key, method


def _certified_taxa():
    rows = EntityIdentifier.objects.filter(namespace="uniprot", is_active=True,
        entity__is_active=True, source_release__source__enabled=True,
        source_release__source__slug="uniprot-human", entity__taxon_key="9606")
    return dict(rows.values_list("identifier", "entity__taxon_key"))


def _insert_rows(model, names, rows):
    """Bound executemany, using Django field prep (SQLite and PostgreSQL).

    No REPLACE/ignore-conflicts: a conflicting immutable row fails the batch.
    """
    if not rows:
        return
    fields = [model._meta.get_field(name) for name in names]
    quote = connection.ops.quote_name
    columns = ",".join(quote(field.column) for field in fields)
    placeholders = ",".join(["%s"] * len(fields))
    sql = f"INSERT INTO {quote(model._meta.db_table)} ({columns}) VALUES ({placeholders})"
    prepared = [tuple(field.get_db_prep_save(value, connection) for field, value in zip(fields, row)) for row in rows]
    with connection.cursor() as cursor:
        cursor.executemany(sql, prepared)


def _scan(path, definition, source, certified, progress):
    references = {}
    counts = Counter(rows=0, relations=0, accepted=0, quarantined=0,
        invalid_identifier_edges=0, invalid_aliases=0)
    for number, raw in workbook_indexed_rows(path, definition):
        record = normalize_row(definition.slug, raw)
        valid_edges = 0
        for edge in record.relations:
            try:
                endpoints = [_reference(ref, source, certified) for ref in (edge.subject, edge.object)]
            except ValidationError:
                counts["invalid_identifier_edges"] += 1
                continue
            valid_edges += 1
            for ref, key, method in endpoints:
                token = _key_tuple(key)
                item = references.setdefault(token, {"ref": ref, "key": key, "method": method,
                    "labels": set(), "observations": set(), "symbol": ""})
                item["labels"].add(ref.label)
                item["observations"].add((key["namespace"], ref.identifier, ref.label, key["taxon_key"]))
                for namespace, identifier, _ in ref.aliases:
                    try:
                        alias, _ = identity_key(entity_type=ref.entity_type, namespace=namespace,
                            identifier=identifier, taxon_key=ref.taxon_key, source=source)
                        item["observations"].add((alias["namespace"], identifier, ref.label, alias["taxon_key"]))
                    except ValidationError:
                        counts["invalid_aliases"] += 1
                if ref.entity_type == "gene":
                    item["symbol"] = ref.label if " " not in ref.label else ""
                elif ref is endpoints[1][0] and definition.slug == "hit":
                    item["symbol"] = str(raw.get("Symbol") or "").strip()
        counts["rows"] += 1
        counts["relations"] += valid_edges
        counts["accepted" if valid_edges else "quarantined"] += 1
        if counts["rows"] % 50000 == 0:
            progress(f"{definition.slug}: audited {counts['rows']:,} rows / {len(references):,} identities")
    return references, dict(counts)


def _bind_references(release, references):
    """Primary bindings are authoritative; secondary aliases cannot merge them."""
    registry = {_key_tuple(dict(zip(("entity_type", "namespace", "identifier", "taxon_key", "scope"), row[:5]))): row[5]
        for row in CanonicalIdentifier.objects.values_list("entity_type", "namespace", "identifier", "taxon_key", "scope", "entity_id")}
    entities = {}
    fresh, pending = [], []
    for token, item in references.items():
        if token in registry:
            entities[token] = registry[token]
            continue
        key, ref = item["key"], item["ref"]
        stable = "master:" + hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:48]
        fresh.append(KnowledgeEntity(entity_type=ref.entity_type, stable_id=stable,
            label=ref.label, taxon_key=key["taxon_key"], is_active=False,
            identity_status="identifier_bound" if item["method"] == "strong_identifier" else "source_scoped",
            source_release=release if key["scope"] else None,
            organism="Homo sapiens" if key["taxon_key"] == "9606" else "",
            synonyms=sorted(item["labels"] - {ref.label})[:50],
            metadata={"source": release.source.slug, "symbol": item["symbol"],
                "speciesVerification": "exact_reviewed_uniprot_accession" if key["taxon_key"] == "9606" else "not_supplied",
                "sourceIdentifier": ref.identifier}))
        pending.append(token)
    KnowledgeEntity.objects.bulk_create(fresh, batch_size=500)
    for token, entity in zip(pending, fresh):
        entities[token] = entity.pk
        registry[token] = entity.pk
    bindings = [CanonicalIdentifier(entity_id=entities[token], **references[token]["key"],
        source=release.source if references[token]["key"]["scope"] else None,
        match_method=references[token]["method"]) for token in pending]
    CanonicalIdentifier.objects.bulk_create(bindings, batch_size=500)

    observations = defaultdict(lambda: {"entities": set(), "labels": set()})
    for token, item in references.items():
        for namespace, identifier, label, taxon in item["observations"]:
            key = (token[0], namespace, identifier, taxon)
            observations[key]["entities"].add(entities[token])
            observations[key]["labels"].add(label)
    mappings, aliases = [], []
    for (kind, namespace, identifier, taxon), observed in observations.items():
        candidate_ids = sorted(observed["entities"])
        alias, method = identity_key(entity_type=kind, namespace=namespace, identifier=identifier,
            taxon_key=taxon, source=release.source)
        alias_token = _key_tuple(alias)
        bound = registry.get(alias_token)
        status, reason = "mapped", ""
        if len(candidate_ids) != 1:
            status, reason = "ambiguous", "Source identifier refers to multiple primary identities; no merge."
        elif bound is not None and bound != candidate_ids[0]:
            status, reason = "conflict", "Secondary ID conflicts with authoritative primary binding; no merge."
        elif bound is None:
            registry[alias_token] = candidate_ids[0]
            aliases.append(CanonicalIdentifier(entity_id=candidate_ids[0], **alias,
                source=release.source if alias["scope"] else None, match_method="explicit_row_cross_reference"))
        mappings.append(SourceEntityMapping(source_release=release, entity_type=kind,
            namespace=namespace, source_entity_id=identifier, taxon_key=taxon,
            source_label=sorted(observed["labels"])[0],
            entity_id=candidate_ids[0] if status == "mapped" else None,
            status=status, reason=reason, match_method=method,
            metadata={"candidateEntityPks": candidate_ids, "observedLabels": sorted(observed["labels"])[:50],
                "normalizedIdentifier": alias["identifier"], "scope": alias["scope"]}))
    CanonicalIdentifier.objects.bulk_create(aliases, batch_size=500)
    # Resuming an incomplete version repeats the same observations, not rows.
    existing = set(SourceEntityMapping.objects.filter(source_release=release).values_list(
        "entity_type", "namespace", "source_entity_id", "taxon_key"))
    SourceEntityMapping.objects.bulk_create([m for m in mappings if
        (m.entity_type, m.namespace, m.source_entity_id, m.taxon_key) not in existing], batch_size=500)
    stable_ids = {}
    ids = list(set(entities.values()))
    for offset in range(0, len(ids), 500):
        stable_ids.update(KnowledgeEntity.objects.filter(pk__in=ids[offset:offset + 500]).values_list("pk", "stable_id"))
    return entities, stable_ids


def _write_batch(release, batch, entities, stable_ids, certified):
    now = timezone.now()
    records, relations = [], []
    for number, record in batch:
        edge_rows = []
        for slot, edge in enumerate(record.relations):
            try:
                endpoints = [_reference(ref, release.source, certified) for ref in (edge.subject, edge.object)]
                subject, target = [entities[_key_tuple(item[1])] for item in endpoints]
            except ValidationError:
                continue
            metadata = {**edge.metadata, "parserVersion": PARSER_VERSION, "worksheetRow": number}
            if metadata.get("context") == "disease_herb_target_triple":
                for ref in (endpoint for spec in record.relations for endpoint in (spec.subject, spec.object)):
                    if ref.entity_type in {"herb", "disease"}:
                        _, key, _ = _reference(ref, release.source, certified)
                        metadata[f"{ref.entity_type}StableId"] = stable_ids[entities[_key_tuple(key)]]
            edge_rows.append((slot, subject, target, edge, metadata))
        raw_id = f"Sheet1:{number:09d}"
        records.append((release.pk, raw_id, record.payload_sha256, record.payload,
            "accepted" if edge_rows else "quarantined", now))
        for slot, subject, target, edge, metadata in edge_rows:
            relations.append((raw_id, slot, subject, target, edge, metadata))
    with transaction.atomic():
        _insert_rows(SourceRecord, ("source_release", "source_record_id", "payload_sha256", "payload", "status", "created_at"), records)
        raw_pks = {}
        for offset in range(0, len(records), 400):
            ids = [row[1] for row in records[offset:offset + 400]]
            raw_pks.update(SourceRecord.objects.filter(source_release=release, source_record_id__in=ids).values_list("source_record_id", "pk"))
        rows = [(release.pk, f"{raw_id}:edge:{slot}", raw_pks[raw_id], subject, target,
            edge.relation_type, edge.evidence_type, edge.score, edge.evidence_text, "", False,
            metadata, None, now) for raw_id, slot, subject, target, edge, metadata in relations]
        _insert_rows(EvidenceRelation, ("source_release", "source_record_id", "source_record_ref", "subject", "object",
            "relation_type", "evidence_type", "score", "evidence_text", "organism", "is_active", "metadata", "observed_at", "created_at"), rows)
        release.metadata = {**release.metadata, "lastImportedRow": batch[-1][0]}
        release.save(update_fields=["metadata"])


def _publish(release, counts, entities):
    """No partial versions are exposed to the analysis readers."""
    with transaction.atomic():
        release = SourceRelease.objects.select_for_update().get(pk=release.pk)
        actual_rows = SourceRecord.objects.filter(source_release=release).count()
        actual_edges = EvidenceRelation.objects.filter(source_release=release).count()
        actual_quarantine = SourceRecord.objects.filter(source_release=release, status="quarantined").count()
        if (actual_rows, actual_edges, actual_quarantine) != (counts["rows"], counts["relations"], counts["quarantined"]):
            raise ValidationError("Full import reconciliation failed; incomplete release remains inactive.")
        if EvidenceRelation.objects.filter(source_release=release, source_record_ref=None).exists():
            raise ValidationError("Evidence lost its raw provenance; release remains inactive.")
        # Retire only old versions belonging to THIS source. Never delete history.
        EvidenceRelation.objects.filter(source_release__source=release.source).exclude(source_release=release).update(is_active=False)
        ids = list(set(entities.values()))
        for offset in range(0, len(ids), 500):
            KnowledgeEntity.objects.filter(pk__in=ids[offset:offset + 500], is_active=False).update(is_active=True)
        EvidenceRelation.objects.filter(source_release=release).update(is_active=True)
        release.published_at = timezone.now()
        release.metadata = {**release.metadata, "importState": "published", "counts": counts,
            "publishedAt": release.published_at.isoformat(), "internalUseOnly": True}
        release.save(update_fields=["published_at", "metadata"])
        DataSource.objects.filter(pk=release.source_id).update(enabled=True, last_success_at=release.published_at)
    return release


def import_workbook(directory, slug, *, apply=False, progress=lambda message: None):
    definition = SOURCES[slug]
    path = (Path(directory) / definition.filename).resolve(strict=True)
    checksum = sha256_file(path)
    version = f"{PARSER_VERSION}:{checksum}"
    source = DataSource.objects.filter(slug=slug).first()
    if source is None:
        source = DataSource(slug=slug, name=definition.name, access_mode="manual", enabled=False,
            license_note="User-authorized internal research use; not licensed for public redistribution.",
            configuration={"connector": "local-workbooks-master", "filename": definition.filename})
        if apply:
            source.save()
    old = SourceRelease.objects.filter(source=source, version=version).first() if source.pk else None
    if old and old.metadata.get("importState") == "published":
        return {"source": slug, "state": "unchanged", **old.metadata["counts"]}
    certified = _certified_taxa()
    references, counts = _scan(path, definition, source, certified, progress)
    if checksum != sha256_file(path):
        raise ValidationError("Workbook changed during audit; no publication allowed.")
    if not apply:
        return {"source": slug, "state": "preview", "checksum": checksum,
            "uniquePrimaryIdentities": len(references), **counts}
    release, _ = SourceRelease.objects.get_or_create(source=source, version=version,
        defaults={"checksum_sha256": checksum, "metadata": {"parserVersion": PARSER_VERSION,
            "filename": definition.filename, "importState": "staging", "internalUseOnly": True}})
    if release.checksum_sha256 != checksum:
        raise ValidationError("Immutable source-version checksum mismatch.")
    run = SyncRun.objects.create(source=source, release=release, status="running", started_at=timezone.now())
    previous_rows = SourceRecord.objects.filter(source_release=release).count()
    try:
        with transaction.atomic():
            entities, stable_ids = _bind_references(release, references)
        last_row = int(release.metadata.get("lastImportedRow", 0))
        batch, seen = [], 0
        for number, raw in workbook_indexed_rows(path, definition):
            seen += 1
            if number <= last_row:
                continue
            batch.append((number, normalize_row(slug, raw)))
            if len(batch) == BATCH_SIZE:
                _write_batch(release, batch, entities, stable_ids, certified)
                batch.clear()
                if seen % 50000 == 0:
                    progress(f"{slug}: staged {seen:,}/{counts['rows']:,} rows (not published yet)")
        if batch:
            _write_batch(release, batch, entities, stable_ids, certified)
        if checksum != sha256_file(path):
            raise ValidationError("Workbook changed during import; release remains inactive.")
        release = _publish(release, counts, entities)
        run.status, run.records_seen, run.records_created = "succeeded", counts["rows"], counts["rows"] - previous_rows
        run.preview_summary = {"mode": "apply", "connector": "local-workbooks-master",
            "actorCommand": "import_local_workbooks", "parserVersion": PARSER_VERSION, "checksum": checksum, **counts}
        run.finished_at = timezone.now()
        run.save()
        return {"source": slug, "state": "published", "releaseId": release.pk,
            "uniquePrimaryIdentities": len(references), **counts}
    except Exception as exc:
        run.status, run.error_summary, run.finished_at = "failed", str(exc)[:1000], timezone.now()
        run.save(update_fields=["status", "error_summary", "finished_at"])
        raise
