"""Versioned target identity overlay; original entity PKs/evidence are immutable."""
from collections import Counter, defaultdict
import hashlib
import json
import re

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.models import (CanonicalIdentifier, DataSource, EntityIdentifier, KnowledgeEntity,
    SourceRelease, TargetIdentityMapping, TargetMaster)
from .connectors.target_reference import load_reference

RESOLVER_VERSION = 'target-identity-v1'
SOURCE_SLUG = 'target-reference-uniprot-human'
STRONG_NAMESPACES = {'entrez', 'ncbi_gene', 'uniprot', 'uniprotkb'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def name_key(value): return ' '.join(str(value).casefold().split())
def target_key(namespace, identifier): return f'{namespace}:9606:{identifier}'


class ReferenceIndex:
    def __init__(self, rows):
        self.masters, self.proteins, self.gene_proteins = {}, {}, defaultdict(set)
        self.names = {'gene': defaultdict(set), 'protein': defaultdict(set)}
        for row in rows:
            pk = target_key('uniprot', row['accession'])
            self.proteins[row['accession']] = row
            self.masters[pk] = {'namespace': 'uniprot', 'identifier': row['accession'], 'taxon_key': row['taxon'],
                'label': row['proteinName'][:300], 'symbol': row['symbol'][:100]}
            names = {row['proteinName'], row['proteinName'].split(' (', 1)[0]}
            names.update(n for n in re.findall(r'\(([^()]*)\)', row['proteinName']) if not n.startswith('EC '))
            for name in names: self.names['protein'][name_key(name)].add(pk)
            for gene in row['geneIds']:
                gk = target_key('entrez', gene)
                self.gene_proteins[gk].add(pk)
                self.masters.setdefault(gk, {'namespace': 'entrez', 'identifier': gene, 'taxon_key': row['taxon'],
                    'label': row['symbol'] or f'NCBI Gene {gene}', 'symbol': row['symbol'][:100]})
                if row['symbol']: self.names['gene'][name_key(row['symbol'])].add(gk)

    def gene_for(self, key):
        if key.startswith('entrez:'): return key
        genes = self.proteins[key.rsplit(':', 1)[1]]['geneIds']
        return target_key('entrez', genes[0]) if len(genes) == 1 else None

    def resolve(self, record):
        kind, taxon = record['kind'], record['taxon']
        output = {'status': 'unmapped', 'master': None, 'gene': None, 'method': '', 'candidates': [],
            'candidateCount': 0, 'evidence': {'originalTaxon': taxon, 'strongIdentifiers': record['ids']}}
        resolved, incompatible, unresolved, gene_choices = set(), [], [], set()
        for namespace, identifier in record['ids']:
            namespace = {'ncbi_gene': 'entrez', 'uniprotkb': 'uniprot'}.get(namespace, namespace)
            if namespace == 'entrez' and kind == 'gene':
                key = target_key('entrez', identifier)
                if key in self.masters: resolved.add(key)
                else: unresolved.append([namespace, identifier])
            elif namespace == 'uniprot':
                key = target_key('uniprot', identifier.upper())
                if key in self.masters:
                    if kind == 'gene':
                        gene = self.gene_for(key)
                        if gene: resolved.add(gene)
                        else: gene_choices.update(target_key('entrez', g) for g in self.proteins[identifier.upper()]['geneIds'])
                    else: resolved.add(key)
                else: unresolved.append([namespace, identifier])
        if resolved and taxon not in {'unknown', '9606'}: incompatible.append('Reference species conflicts with original species')
        if len(resolved) > 1: incompatible.append('Explicit identifiers disagree')
        if incompatible:
            output.update(status='conflict', method='identifier_conflict')
            output['evidence']['reasons'] = incompatible
        elif len(resolved) == 1:
            key = next(iter(resolved))
            output.update(status='verified', master=key, gene=self.gene_for(key), method='exact_standard_identifier')
        elif gene_choices:
            output.update(status='ambiguous', method='identifier_one_to_many', candidateCount=len(gene_choices))
            output['candidates'] = [{'key': key, 'geneKey': key, **self.masters[key]} for key in sorted(gene_choices)[:20]]
        else:
            # Names only propose candidates; an unknown species is never assigned human.
            keys = set()
            if taxon in {'unknown', '9606'}:
                for name in [record['label'], record['metadata'].get('symbol', '')]:
                    if name: keys.update(self.names[kind].get(name_key(name), set()))
            output.update(status='candidate' if len(keys) == 1 else 'ambiguous' if keys else 'unmapped',
                method='exact_name_candidate' if keys else 'no_reference_identity', candidateCount=len(keys))
            output['candidates'] = [{'key': key, 'geneKey': self.gene_for(key), **self.masters[key]}
                                    for key in sorted(keys)[:20]]
        output['evidence']['unresolvedIdentifiers'] = unresolved
        return output


def input_profiles(entity_ids=None):
    """Bulk read current names/species/strong IDs; reused to reject stale mappings."""
    qs = KnowledgeEntity.objects.filter(entity_type__in=['gene', 'protein'], is_active=True).filter(
        Q(source_release__isnull=True) | Q(source_release__source__enabled=True))
    rows = {}
    supplemental = DataSource.objects.filter(slug='tcmsp',enabled=True).first()
    supplement_id=(supplemental.configuration.get('activeSupplementReleaseId') if supplemental else None)
    groups = [None] if entity_ids is None else [sorted(entity_ids)[i:i+500] for i in range(0, len(entity_ids), 500)]
    for group in groups:
        batch = qs if group is None else qs.filter(pk__in=group)
        for e in batch.values('id', 'entity_type', 'taxon_key', 'label', 'metadata', 'source_release_id',
                'source_release__source__slug', 'source_release__source__configuration'):
            metadata = e['metadata'] or {}
            record = {'id': e['id'], 'kind': e['entity_type'], 'taxon': e['taxon_key'], 'label': e['label'],
                'metadata': metadata, 'sourceReleaseId': e['source_release_id'], 'ids': [],
                'source': e['source_release__source__slug'] or metadata.get('source', 'global')}
            config = e['source_release__source__configuration'] or {}
            if config.get('connector') == 'uniprot-human-catalog' and metadata.get('accession'):
                # Explicit accession carried by the original reviewed UniProt entry,
                # not a gene/protein equality inferred from a name.
                record['ids'].append(['uniprot', str(metadata['accession'])])
            rows[e['id']] = record
        identifier_query = {'entity_id__in': batch.order_by().values('pk'), 'namespace__in': STRONG_NAMESPACES}
        ids = CanonicalIdentifier.objects.filter(**identifier_query).filter(Q(source__isnull=True) | Q(source__enabled=True))
        aliases = EntityIdentifier.objects.filter(**identifier_query, is_active=True, source_release__source__enabled=True)
        for model_rows in [ids.values_list('entity_id', 'namespace', 'identifier'), aliases.values_list('entity_id', 'namespace', 'identifier')]:
            for pk, ns, value in model_rows: rows[pk]['ids'].append([ns, value])
        if supplement_id:
            from apps.core.models import SourceEntityMapping
            links=SourceEntityMapping.objects.filter(source_release_id=supplement_id,source_release__published_at__isnull=False,
                source_release__metadata__targetIdentityPolicy='unique_reviewed_human_v1',entity_id__in=batch.order_by().values('pk'),
                namespace='tcmsp.target_id',status='mapped',match_method='validated_supplemental_identifier',metadata__identityVerified=True)
            for pk,metadata,record in links.values_list('entity_id','metadata','source_record_id'):
                rows[pk]['ids'].append(['uniprot',metadata['uniprot']])
                rows[pk].setdefault('supplementalCrossReferences',[]).append({'releaseId':supplement_id,'recordId':record,
                    'uniprot':metadata['uniprot'],'referenceSha256':metadata['referenceSha256']})
    for r in rows.values(): r['ids'] = [list(v) for v in sorted(set(tuple(v) for v in r['ids']))]
    return rows


def current_release():
    source = DataSource.objects.filter(slug=SOURCE_SLUG, enabled=True).first()
    if not source: return None
    pk = source.configuration.get('activeTargetIdentityRelease')
    return SourceRelease.objects.filter(pk=pk, source=source, metadata__identityState='published').first() if pk else None


def build_target_identities(manifest_path, *, apply=False):
    manifest, rows = load_reference(manifest_path)
    index = ReferenceIndex(rows)
    profiles = input_profiles()
    fingerprint = digest([profiles[pk] for pk in sorted(profiles)])
    resolutions = {pk: index.resolve(record) for pk, record in profiles.items()}
    counts = dict(Counter(r['status'] for r in resolutions.values()))
    version = f"{manifest['version']}+{manifest['sha256'][:12]}+{fingerprint[:12]}+v1"
    result = {'version': version, 'resolverVersion': RESOLVER_VERSION, 'referenceProteins': len(rows),
        'standardTargets': len(index.masters), 'inputRecords': len(profiles), 'statuses': counts,
        'referenceSha256': manifest['sha256'], 'inputSha256': fingerprint, 'applied': False}
    if not apply: return result
    # All inserts and the publication pointer switch commit together. Failure
    # leaves the previous reference/current result available and never merges FKs.
    with transaction.atomic():
        source, _ = DataSource.objects.get_or_create(slug=SOURCE_SLUG, defaults={'name': 'UniProt靶点标准编号对照',
            'access_mode': 'download', 'documentation_url': 'https://www.uniprot.org/help/api_queries',
            'license_note': 'UniProt CC BY 4.0; public identity reference, no local queries uploaded.',
            'configuration': {'connector': 'target-identity-reference'}})
        source = DataSource.objects.select_for_update().get(pk=source.pk)
        release, fresh = SourceRelease.objects.get_or_create(source=source, version=version, defaults={
            'checksum_sha256': manifest['sha256'], 'metadata': {'identityState': 'building', 'reference': manifest, **result}})
        if not fresh:
            if release.metadata.get('identityState') != 'published' or release.target_identity_mappings.count() != len(profiles):
                raise ValueError('Existing identity version is incomplete; refusing publication.')
        else:
            existing = set(TargetMaster.objects.values_list('key', flat=True))
            TargetMaster.objects.bulk_create([TargetMaster(key=key, reference_release=release, **attrs)
                for key, attrs in index.masters.items() if key not in existing], batch_size=500)
            TargetIdentityMapping.objects.bulk_create([TargetIdentityMapping(entity_id=pk, reference_release=release,
                status=r['status'], master_id=r['master'], gene_id=r['gene'], match_method=r['method'],
                input_sha256=digest(profiles[pk]), evidence=r['evidence'], candidates=r['candidates'],
                candidate_count=r['candidateCount']) for pk, r in resolutions.items()], batch_size=300)
            if release.target_identity_mappings.count() != len(profiles): raise ValueError('Identity mapping count mismatch.')
            release.metadata = {**release.metadata, 'identityState': 'published', 'applied': True}
            release.published_at = timezone.now(); release.save(update_fields=['metadata', 'published_at'])
        source.configuration = {**source.configuration, 'activeTargetIdentityRelease': release.pk}
        source.last_success_at = timezone.now(); source.save(update_fields=['configuration', 'last_success_at'])
    return {**result, 'applied': True, 'releaseId': release.pk}
