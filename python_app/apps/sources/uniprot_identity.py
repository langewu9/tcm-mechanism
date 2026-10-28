"""One conservative identity plan shared by UniProt preview and application.

Same-name records with unknown species or unverified symbols stay separate.
Existing accessions have stronger identity evidence than a new symbol match;
an incompatible owner requires review rather than silently moving the ID.
"""
import hashlib
import json
from dataclasses import dataclass

from django.db.models import Q

from apps.core.models import DataSource, EntityIdentifier, KnowledgeEntity
from apps.sources.connectors.uniprot import UniProtCatalogSnapshot


IDENTITY_POLICY = "uniprot-human-identity-2"
HUMAN_NAMES = {"homo sapiens", "homo sapiens (human)"}
UNVERIFIED_STATUSES = {"name_only", "unverified_symbol"}


def canonical(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _identity(entity):
    metadata = entity.metadata if isinstance(entity.metadata, dict) else {}
    value = metadata.get("symbol") or metadata.get("gene_symbol") or metadata.get("geneSymbol")
    symbol = canonical(value) if isinstance(value, str) else ""
    return symbol, metadata.get("identifierStatus"), canonical(entity.organism)


@dataclass
class UniProtIdentityPlan:
    existing: dict[str, EntityIdentifier]
    local_entities: dict[str, KnowledgeEntity]
    summary: dict


def build_identity_plan(source: DataSource, snapshot: UniProtCatalogSnapshot, *, lock=False) -> UniProtIdentityPlan:
    symbols = {canonical(item.primary_gene) for item in snapshot.proteins if item.primary_gene}
    accessions = {item.accession for item in snapshot.proteins}
    identifiers = EntityIdentifier.objects.filter(namespace="uniprot", identifier__in=accessions)
    targets = KnowledgeEntity.objects.filter(
        entity_type__in=[KnowledgeEntity.EntityType.GENE, KnowledgeEntity.EntityType.PROTEIN],
        is_active=True,
    ).filter(Q(source_release__isnull=True) | Q(source_release__source__enabled=True)).exclude(
        source_release__source=source,
    )
    if lock:
        identifiers = identifiers.select_for_update(of=("self",))
        targets = targets.select_for_update(of=("self",))
    existing = {row.identifier: row for row in identifiers.select_related(
        "entity__source_release__source", "source_release__source",
    )}
    eligible: dict[str, list[KnowledgeEntity]] = {}
    unknown, other, unverified = [], [], []
    evidence = []
    for entity in targets.select_related("source_release__source").order_by("id"):
        symbol, status, organism = _identity(entity)
        if symbol not in symbols:
            continue
        evidence.append([entity.pk, entity.stable_id, symbol, status, organism, entity.source_release_id])
        if not organism:
            unknown.append(entity.pk)
        elif organism not in HUMAN_NAMES:
            other.append(entity.pk)
        if status in UNVERIFIED_STATUSES:
            unverified.append(entity.pk)
        if organism in HUMAN_NAMES and status not in UNVERIFIED_STATUSES:
            eligible.setdefault(symbol, []).append(entity)

    local_entities = {}
    conflicts, decisions = [], []
    preserved = 0
    fallback_keys = {
        ("gene", f"uniprot-gene:{item.primary_gene}"[:160]) if item.primary_gene else
        ("protein", f"uniprot:{item.accession}") for item in snapshot.proteins
    }
    reserved_entities = {
        (entity.entity_type, entity.stable_id): entity
        for entity in KnowledgeEntity.objects.filter(
            entity_type__in={key[0] for key in fallback_keys}, stable_id__in={key[1] for key in fallback_keys},
        ).select_related("source_release__source")
    }
    for protein in snapshot.proteins:
        symbol = canonical(protein.primary_gene)
        previous = existing.get(protein.accession)
        if previous is not None:
            entity = previous.entity
            entity_symbol, status, organism = _identity(entity)
            owned = bool(entity.source_release_id and entity.source_release.source_id == source.pk)
            source_enabled = not entity.source_release_id or entity.source_release.source.enabled
            compatible = (
                entity.entity_type in [KnowledgeEntity.EntityType.GENE, KnowledgeEntity.EntityType.PROTEIN]
                and organism in HUMAN_NAMES and status not in UNVERIFIED_STATUSES
                and (owned or entity.is_active and source_enabled)
                and (not entity_symbol or not symbol or entity_symbol == symbol)
            )
            # Existing gene-level fallbacks cannot silently change gene identity.
            if owned:
                expected_key = ("gene", f"uniprot-gene:{protein.primary_gene}"[:160]) if symbol else (
                    "protein", f"uniprot:{protein.accession}")
                compatible = compatible and (entity.entity_type, entity.stable_id) == expected_key
            previous_proof = [previous.pk, previous.entity_id, previous.source_release_id, previous.is_active,
                              entity.stable_id, entity_symbol, status, organism, entity.is_active, source_enabled,
                              previous.metadata]
            if not compatible:
                conflicts.append(protein.accession)
                decisions.append([protein.accession, "conflict", previous_proof])
                continue
            preserved += 1
            if not owned:
                local_entities[protein.accession] = entity
            decisions.append([protein.accession, "existing_accession", previous_proof])
        else:
            matches = eligible.get(symbol, [])
            if len(matches) == 1:
                local_entities[protein.accession] = matches[0]
                decisions.append([protein.accession, "local_human_symbol", matches[0].pk])
            else:
                key = ("gene", f"uniprot-gene:{protein.primary_gene}"[:160]) if symbol else (
                    "protein", f"uniprot:{protein.accession}")
                reserved = reserved_entities.get(key)
                if reserved and (not reserved.source_release_id or reserved.source_release.source_id != source.pk):
                    conflicts.append(protein.accession)
                    decisions.append([protein.accession, "reserved_identity_conflict", reserved.pk, reserved.source_release_id])
                else:
                    decisions.append([protein.accession, "separate_catalogue_entity", symbol,
                                      reserved.pk if reserved else None])

    proof = {"policy": IDENTITY_POLICY, "candidates": evidence, "decisions": sorted(decisions)}
    fingerprint = hashlib.sha256(json.dumps(proof, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return UniProtIdentityPlan(existing=existing, local_entities=local_entities, summary={
        "identityPolicy": IDENTITY_POLICY,
        "identityPlanSha256": fingerprint,
        "geneSymbolsMappedToExistingTargets": len({
            canonical(item.primary_gene) for item in snapshot.proteins if item.accession in local_entities
        }),
        "ambiguousLocalGeneSymbols": sum(len(matches) > 1 for matches in eligible.values()),
        "unknownSpeciesLocalTargets": len(unknown),
        "otherSpeciesLocalTargets": len(other),
        "unverifiedLocalTargets": len(unverified),
        "preservedAccessionMappings": preserved,
        "identifierConflicts": len(conflicts),
    })
