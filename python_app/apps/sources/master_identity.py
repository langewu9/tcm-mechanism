"""Species-aware identity resolution; names never establish cross-source identity."""
import hashlib
import json
import re
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from apps.core.models import CanonicalIdentifier, DataSource, EntityIdentifier, KnowledgeEntity, SourceEntityMapping, SourceRecord

ALIASES = {'pubchem_cid': 'pubchem', 'chembl_compound': 'chembl-compound', 'chembl_target': 'chembl-target', 'ncbi_gene': 'entrez', 'gene_symbol': 'symbol', 'uniprotkb': 'uniprot'}
KINDS = set(KnowledgeEntity.EntityType.values)
STRONG = {
    'pubchem': ('compound', r'[1-9][0-9]*'),
    'chembl-compound': ('compound', r'CHEMBL[0-9]+'),
    'chembl-target': ('protein', r'CHEMBL[0-9]+'),
    'uniprot': ('protein', r'(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})(?:-[1-9][0-9]*)?'),
    'entrez': ('gene', r'[1-9][0-9]*'),
    'hgnc': ('gene', r'HGNC:[0-9]+'),
    'reactome': ('pathway', r'R-[A-Z]{3}-[0-9]+'),
    'string': ('protein', r'[1-9][0-9]*\.[A-Za-z0-9_.-]+'),
    'inchikey': ('compound', r'[A-Z]{14}-[A-Z]{10}-[A-Z]'),
}

def identity_key(*, entity_type, namespace, identifier, taxon_key='unknown', source):
    if entity_type not in KINDS: raise ValidationError('Unsupported entity type.')
    namespace = ALIASES.get(namespace.strip().lower(), namespace.strip().lower())
    value = str(identifier).strip()
    if not re.fullmatch(r'[a-z0-9_.-]{1,64}', namespace) or not value or len(value) > 300:
        raise ValidationError('Invalid namespace or identifier.')
    taxon = str(taxon_key or 'unknown').strip()
    if taxon not in {'unknown', 'not_applicable'} and not re.fullmatch(r'[1-9][0-9]*', taxon):
        raise ValidationError('Species must be an NCBI taxonomy ID or explicitly unknown.')
    scope, method = source.slug, 'source_scoped'
    if namespace in STRONG:
        kind, pattern = STRONG[namespace]
        if namespace in {'chembl-compound', 'chembl-target', 'uniprot', 'hgnc', 'reactome', 'inchikey'}:
            value = value.upper()
        if entity_type != kind or not re.fullmatch(pattern, value):
            raise ValidationError('Identifier type/format does not match the master entity type.')
        if kind == 'compound': taxon = 'not_applicable'
        if namespace == 'hgnc':
            if taxon not in {'unknown', '9606'}: raise ValidationError('HGNC is human-specific.')
            taxon = '9606'
        if namespace == 'reactome' and value.startswith('R-HSA-'):
            if taxon not in {'unknown', '9606'}: raise ValidationError('Human pathway species conflict.')
            taxon = '9606'
        if namespace == 'string':
            observed_taxon = value.split('.', 1)[0]
            if taxon not in {'unknown', observed_taxon}: raise ValidationError('STRING species conflict.')
            taxon = observed_taxon
        # Unknown species stays source-scoped for biological identifiers.
        if taxon != 'unknown': scope, method = '', 'strong_identifier'
    elif namespace == 'symbol' or namespace.endswith('_name'):
        value = ' '.join(value.casefold().split())
    return {'entity_type': entity_type, 'namespace': namespace, 'identifier': value, 'taxon_key': taxon, 'scope': scope}, method

def preserve_source_record(*, release, record_id, payload, status='accepted'):
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    if status not in {'accepted', 'quarantined'}: raise ValidationError('Invalid row status.')
    with transaction.atomic():
        record, _ = SourceRecord.objects.get_or_create(source_release=release, source_record_id=record_id,
            defaults={'payload_sha256': digest, 'payload': payload, 'status': status})
        if record.payload_sha256 != digest: raise ValidationError('A source row changed inside the same release; original row preserved.')
        return record

def resolve_source_identity(*, release, entity_type, namespace, identifier, label='', taxon_key='unknown', expected_entity=None, record=None):
    """Reuse a strong ID, or create a source-scoped entity; never merge by label."""
    key, method = identity_key(entity_type=entity_type, namespace=namespace, identifier=identifier, taxon_key=taxon_key, source=release.source)
    if record and record.source_release_id != release.pk: raise ValidationError('Raw row belongs to another release.')
    if expected_entity and (expected_entity.entity_type != entity_type or expected_entity.taxon_key != key['taxon_key']):
        raise ValidationError('Existing entity kind/species is incompatible.')
    # Different sources can race for a new global identifier: unique constraint
    # rolls back the losing entity creation, then one bounded retry reuses the winner.
    for attempt in range(2):
        try:
            with transaction.atomic():
                DataSource.objects.select_for_update().get(pk=release.source_id)
                binding = CanonicalIdentifier.objects.select_related('entity').filter(**key).first()
                mapping_key = {'source_release': release, 'entity_type': entity_type,
                    'namespace': key['namespace'], 'source_entity_id': str(identifier), 'taxon_key': key['taxon_key']}
                old = SourceEntityMapping.objects.select_related('entity').filter(**mapping_key).first()
                if binding and expected_entity and binding.entity_id != expected_entity.pk:
                    defaults = {'entity': binding.entity, 'status': 'conflict', 'reason': 'Strong identifier already belongs to a different master entity; no merge performed.',
                        'source_label': label[:300], 'match_method': method,
                        'metadata': {'proposedCanonicalId': str(expected_entity.canonical_id), 'retainedCanonicalId': str(binding.entity.canonical_id)}}
                    if old:
                        # Keep the original observation and original identity intact.
                        old.status, old.reason = 'conflict', defaults['reason']
                        old.metadata = {**old.metadata, **defaults['metadata']}
                        old.save(update_fields=['status', 'reason', 'metadata'])
                        return old
                    return SourceEntityMapping.objects.create(**mapping_key, **defaults)
                if old:
                    if binding and old.entity_id != binding.entity_id: raise ValidationError('Mapping conflicts with the master registry.')
                    return old
                if not binding:
                    entity = expected_entity
                    if entity is None:
                        stable = 'master:' + hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:48]
                        entity = KnowledgeEntity.objects.create(entity_type=entity_type, stable_id=stable,
                            label=(label or str(identifier))[:300], source_release=release if key['scope'] else None,
                            taxon_key=key['taxon_key'], organism='Homo sapiens' if key['taxon_key'] == '9606' else '',
                            identity_status='identifier_bound' if method == 'strong_identifier' else 'source_scoped')
                    binding = CanonicalIdentifier.objects.create(**key, entity=entity,
                        source=release.source if key['scope'] else None, match_method=method)
                return SourceEntityMapping.objects.create(**mapping_key, entity=binding.entity, source_record=record,
                    source_label=label[:300], status='mapped', match_method=method,
                    metadata={'normalizedIdentifier': key['identifier'], 'scope': key['scope']})
        except IntegrityError:
            if attempt: raise

def bootstrap_existing_master_ids():
    """Bind existing stable IDs without redefining biological identity or FK targets."""
    bindings, mappings = [], []
    for entity in KnowledgeEntity.objects.select_related('source_release__source').exclude(source_release=None).iterator(chunk_size=500):
        source = entity.source_release.source
        bindings.append(CanonicalIdentifier(entity=entity, entity_type=entity.entity_type,
            namespace='platform-stable-id', identifier=entity.stable_id, taxon_key=entity.taxon_key,
            scope=source.slug, source=source, match_method='legacy_pk_preserved'))
        mappings.append(SourceEntityMapping(source_release=entity.source_release, entity=entity,
            entity_type=entity.entity_type, namespace='platform-stable-id', source_entity_id=entity.stable_id,
            source_label=entity.label, taxon_key=entity.taxon_key, status='mapped', match_method='legacy_pk_preserved',
            metadata={'legacyEntityPk': entity.pk, 'canonicalId': str(entity.canonical_id), 'identityNotReinferred': True}))
        if len(bindings) == 500:
            _bootstrap_batch(bindings, mappings); bindings.clear(); mappings.clear()
    if bindings: _bootstrap_batch(bindings, mappings)
    # Retain legacy cross-references without promoting them to biological identity.
    observations = {}
    for row in EntityIdentifier.objects.select_related('entity').all().iterator(chunk_size=1000):
        key = (row.source_release_id, row.entity.entity_type, row.namespace, row.identifier, row.entity.taxon_key)
        item = observations.setdefault(key, {'entities': set(), 'ids': [], 'label': row.entity.label})
        item['entities'].add(row.entity_id); item['ids'].append(row.pk)
    batch = []
    for key, item in observations.items():
        unambiguous = len(item['entities']) == 1
        batch.append(SourceEntityMapping(source_release_id=key[0], entity_type=key[1], namespace=key[2],
            source_entity_id=key[3], taxon_key=key[4], source_label=item['label'],
            entity_id=next(iter(item['entities'])) if unambiguous else None,
            status='mapped' if unambiguous else 'ambiguous', match_method='legacy_cross_reference',
            reason='' if unambiguous else 'Existing source identifier refers to multiple entities; no automatic merge.',
            metadata={'legacyIdentifierPks': item['ids'], 'candidateEntityPks': sorted(item['entities']), 'identityNotReinferred': True}))
        if len(batch) == 500:
            SourceEntityMapping.objects.bulk_create(batch, ignore_conflicts=True, batch_size=500); batch.clear()
    if batch: SourceEntityMapping.objects.bulk_create(batch, ignore_conflicts=True, batch_size=500)

@transaction.atomic
def _bootstrap_batch(bindings, mappings):
    # No silent conflicting-identity overwrite, including during a repeated run.
    existing_by_key = {(row.entity_type, row.namespace, row.identifier, row.taxon_key, row.scope): row.entity_id
        for row in CanonicalIdentifier.objects.filter(namespace='platform-stable-id',
            identifier__in=[item.identifier for item in bindings], scope__in={item.scope for item in bindings})}
    for binding in bindings:
        existing_pk = existing_by_key.get((binding.entity_type, binding.namespace, binding.identifier, binding.taxon_key, binding.scope))
        if existing_pk is not None and existing_pk != binding.entity_id: raise ValidationError('Existing legacy binding points to a different entity.')
    CanonicalIdentifier.objects.bulk_create(bindings, ignore_conflicts=True, batch_size=500)
    SourceEntityMapping.objects.bulk_create(mappings, ignore_conflicts=True, batch_size=500)
