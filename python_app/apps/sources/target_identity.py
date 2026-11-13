"""Versioned target identity overlay; original entity PKs/evidence are immutable."""
from collections import Counter, defaultdict
import hashlib
import json
import re

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.models import (CanonicalIdentifier, DataSource, EntityIdentifier, KnowledgeEntity,
    SourceEntityMapping, SourceRelease, TargetIdentityMapping, TargetMaster)
from .connectors.ncbi_gene_reference import identity_name_variants
from .connectors.target_reference import ACCESSION, load_reference
from .connectors.ncbi_gene_taxonomy_reference import load_reference as load_taxonomy_reference
from .connectors.uniprot_accession_taxonomy import load_reference as load_uniprot_taxonomy_reference

RESOLVER_VERSION = 'target-identity-v7-taxonomy-name-disambiguation'
SOURCE_SLUG = 'target-reference-uniprot-human'
STRONG_NAMESPACES = {'entrez', 'ncbi_gene', 'uniprot', 'uniprotkb'}
SOURCE_SPECIES_ASSERTIONS = {
    slug: {
        'taxon': '9606', 'organism': 'Homo sapiens',
        'basis': 'user_confirmed_project_scope_human_with_public_id_override',
        'confirmedAt': '2026-11-03',
    }
    for slug in ('batman', 'herb', 'hit', 'tcmip', 'tcmsp', 'disease-herb', 'disease-targets')
}
NON_HUMAN_NAME_MARKER = re.compile(
    r'\b(?:HSV(?:-\d+)?|HCMV|HIV(?:-\d+)?|rhinovirus|herpesvirus)\b|'
    r'\b(?:bacterial|bacteria)\b|'
    r'\b(?:Escherichia|Pseudomonas|Staphylococcus|Streptococcus|Mycobacterium)\b|'
    r'\b(?:urease|enoyl[- ]ACP reductase)\b|'
    r'\bruvb\b(?!\s+like\s+aaa\s+atpase\s+[12]\b)', re.I,
)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def name_key(value): return ' '.join(str(value).casefold().split())
def loose_name_key(value): return ''.join(char for char in str(value).casefold() if char.isalnum())
def target_key(namespace, identifier, taxon='9606'): return f'{namespace}:{taxon}:{identifier}'
def usable_reference_name(value):
    value = str(value or '').strip()
    return value if value.casefold() not in {'', '-', 'na', 'n/a', 'none', 'null'} else ''


class ReferenceIndex:
    def __init__(self, rows, gene_rows=()):
        self.masters, self.proteins_by_key, self.proteins_by_accession = {}, {}, defaultdict(set)
        self.gene_keys_by_id = defaultdict(set)
        self.noncurrent_gene_ids = {}
        self.taxon_names = {'9606': 'Homo sapiens'}
        self.names = {'gene': defaultdict(set), 'protein': defaultdict(set)}
        self.normalized_names = {'gene': defaultdict(set), 'protein': defaultdict(set)}
        self.gene_names = defaultdict(set)
        self.normalized_gene_names = defaultdict(set)
        self.official_gene_symbols = defaultdict(set)
        self.normalized_official_gene_symbols = defaultdict(set)
        self.official_gene_names = defaultdict(set)
        self.normalized_official_gene_names = defaultdict(set)
        self.master_sources = defaultdict(set)
        for row in rows:
            taxon = str(row.get('taxon') or '9606')
            if row.get('organismName'):
                self.taxon_names[taxon] = row['organismName']
            pk = target_key('uniprot', row['accession'], taxon)
            self.proteins_by_key[pk] = row
            self.proteins_by_accession[row['accession'].upper()].add(pk)
            self.masters[pk] = {'namespace': 'uniprot', 'identifier': row['accession'], 'taxon_key': taxon,
                'label': row['proteinName'][:300], 'symbol': row['symbol'][:100]}
            self.master_sources[pk].add('UniProt public accession reference')
            names = {row['proteinName'], row['proteinName'].split(' (', 1)[0]}
            names.update(n for n in re.findall(r'\(([^()]*)\)', row['proteinName']) if not n.startswith('EC '))
            for name in names:
                self.names['protein'][name_key(name)].add(pk)
                normalized = loose_name_key(name)
                if normalized: self.normalized_names['protein'][normalized].add(pk)
            for gene in row['geneIds']:
                gk = target_key('entrez', gene, taxon)
                self.gene_keys_by_id[gene].add(gk)
                self.masters.setdefault(gk, {'namespace': 'entrez', 'identifier': gene, 'taxon_key': taxon,
                    'label': row['symbol'] or f'NCBI Gene {gene}', 'symbol': row['symbol'][:100]})
                self.master_sources[gk].add('UniProt GeneID cross-reference')
                if row['symbol']:
                    self.names['gene'][name_key(row['symbol'])].add(gk)
                    normalized = loose_name_key(row['symbol'])
                    if normalized: self.normalized_names['gene'][normalized].add(gk)
        for row in gene_rows:
            if not row.get('identityUsable', True):
                self.noncurrent_gene_ids[str(row['geneId'])] = row
                continue
            taxon = str(row.get('taxon') or '9606')
            if row.get('organism'):
                common = row.get('commonName')
                self.taxon_names[taxon] = f"{row['organism']} ({common})" if common and common.casefold() not in row['organism'].casefold() else row['organism']
            elif row.get('commonName') and taxon not in self.taxon_names:
                self.taxon_names[taxon] = row['commonName']
            key = target_key('entrez', row['geneId'], taxon)
            self.gene_keys_by_id[str(row['geneId'])].add(key)
            symbol = usable_reference_name(row['officialSymbol'])
            # NCBI's fallback symbol can be a historical or weakly classified
            # label. Keep it as an alias, but do not let unknown records outrank
            # the nomenclature-authority symbol.
            if not symbol and row.get('geneType', '').casefold() != 'unknown':
                symbol = usable_reference_name(row['symbol'])
            # Only the nomenclature-authority full name gets priority. NCBI's
            # free-form description stays in the broader alias index below;
            # pseudogene descriptions often duplicate a coding gene's name.
            official_name = usable_reference_name(row['officialName'])
            master_label = official_name or usable_reference_name(row['description']) or symbol
            self.masters.setdefault(key, {'namespace': 'entrez', 'identifier': row['geneId'], 'taxon_key': taxon,
                'label': (master_label or f"NCBI Gene {row['geneId']}")[:300],
                'symbol': symbol[:100]})
            self.master_sources[key].add('NCBI Gene human nomenclature' if taxon == '9606' else 'NCBI Gene nomenclature')
            for variant in identity_name_variants(symbol):
                normalized = name_key(variant)
                self.official_gene_symbols[normalized].add(key)
                self.normalized_official_gene_symbols[loose_name_key(variant)].add(key)
            for variant in identity_name_variants(official_name):
                normalized = name_key(variant)
                self.official_gene_names[normalized].add(key)
                self.normalized_official_gene_names[loose_name_key(variant)].add(key)
            names = {row['symbol'], row['description'], row['officialSymbol'], row['officialName'], *row['synonyms'],
                *row['otherDesignations']}
            for name in names:
                if not usable_reference_name(name): continue
                for variant in identity_name_variants(name):
                    normalized = name_key(variant)
                    self.names['gene'][normalized].add(key)
                    self.gene_names[normalized].add(key)
                    normalized_loose = loose_name_key(variant)
                    if normalized_loose:
                        self.normalized_names['gene'][normalized_loose].add(key)
                        self.normalized_gene_names[normalized_loose].add(key)

    def gene_for(self, key):
        if key.startswith('entrez:'): return key
        row = self.proteins_by_key.get(key)
        genes = row['geneIds'] if row else []
        candidates = {gene_key for gene in genes for gene_key in self.gene_keys_by_id.get(str(gene), set())
            if gene_key.split(':', 2)[1] == key.split(':', 2)[1]}
        return next(iter(candidates)) if len(candidates) == 1 else None

    def resolve(self, record):
        kind = record['kind']
        original_taxon = record['taxon']
        taxon = record.get('resolutionTaxon', original_taxon)
        output = {'status': 'unmapped', 'master': None, 'gene': None, 'method': '', 'candidates': [],
            'candidateCount': 0, 'evidence': {'originalTaxon': original_taxon, 'resolutionTaxon': taxon,
                'taxonEvidence': record.get('taxonEvidence'), 'strongIdentifiers': record['ids']}}
        resolved, incompatible, unresolved, gene_choices = set(), [], [], set()
        for namespace, identifier in record['ids']:
            namespace = {'ncbi_gene': 'entrez', 'uniprotkb': 'uniprot'}.get(namespace, namespace)
            if namespace == 'entrez':
                all_keys = set(self.gene_keys_by_id.get(str(identifier), set()))
                keys = all_keys
                if original_taxon != 'unknown':
                    keys = {key for key in keys if key.split(':', 2)[1] == original_taxon}
                    if all_keys and not keys:
                        incompatible.append('Reference species conflicts with explicit source taxon')
                        output['evidence'].setdefault('identifierTaxa', []).extend(sorted(
                            {key.split(':', 2)[1] for key in all_keys}
                        ))
                if kind == 'gene' and len(keys) == 1:
                    resolved.update(keys)
                elif keys:
                    gene_choices.update(keys)
                else:
                    retired = self.noncurrent_gene_ids.get(str(identifier))
                    if retired:
                        output['evidence']['resolvedTaxon'] = retired['taxon']
                        output['evidence']['matchedPublicReference'] = {
                            'database': 'NCBI Gene', 'taxon': retired['taxon'],
                            'organism': retired.get('organism', ''),
                            'identifierStatus': retired.get('status') or 'merged',
                            'currentId': retired.get('currentId') or None,
                        }
                    unresolved.append([namespace, identifier])
            elif namespace == 'uniprot':
                all_keys = set(self.proteins_by_accession.get(str(identifier).upper(), set()))
                keys = all_keys
                if original_taxon != 'unknown':
                    keys = {key for key in keys if key.split(':', 2)[1] == original_taxon}
                    if all_keys and not keys:
                        incompatible.append('Reference species conflicts with explicit source taxon')
                        output['evidence'].setdefault('identifierTaxa', []).extend(sorted(
                            {key.split(':', 2)[1] for key in all_keys}
                        ))
                if len(keys) == 1:
                    key = next(iter(keys))
                    if kind == 'gene':
                        gene = self.gene_for(key)
                        if gene: resolved.add(gene)
                        else:
                            row = self.proteins_by_key[key]
                            for gene_id in row['geneIds']:
                                gene_choices.update(self.gene_keys_by_id.get(str(gene_id), set()))
                    else: resolved.add(key)
                elif keys:
                    gene_choices.update(keys)
                else:
                    unresolved.append([namespace, identifier])
        if resolved and original_taxon != 'unknown':
            resolved_taxa = {self.masters[key]['taxon_key'] for key in resolved}
            if resolved_taxa != {original_taxon}:
                incompatible.append('Reference species conflicts with explicit source taxon')
        if len(resolved) > 1: incompatible.append('Explicit identifiers disagree')
        if incompatible:
            output.update(status='conflict', method='identifier_conflict')
            output['evidence']['reasons'] = incompatible
        elif len(resolved) == 1:
            key = next(iter(resolved))
            actual_taxon = self.masters[key]['taxon_key']
            assertion = record.get('taxonEvidence') or {}
            evidence = output['evidence']
            evidence['resolvedTaxon'] = actual_taxon
            evidence['matchedPublicReference'] = {
                'database': 'NCBI Gene' if key.startswith('entrez:') else 'UniProtKB',
                'taxon': actual_taxon,
                'organism': self.taxon_names.get(actual_taxon, ''),
            }
            if assertion.get('taxon') and assertion.get('taxon') != actual_taxon:
                evidence['sourceScopeConflict'] = {
                    'assertedTaxon': assertion['taxon'], 'identifierTaxon': actual_taxon,
                    'resolution': 'exact public identifier takes precedence; source scope needs review',
                }
            output.update(status='verified', master=key, gene=self.gene_for(key), method='exact_public_standard_identifier')
            output['candidates'] = [{'key': key, 'geneKey': self.gene_for(key), **self.masters[key],
                'referenceSources': sorted(self.master_sources[key])}]
            output['candidateCount'] = 1
            return output
        elif gene_choices:
            output.update(status='ambiguous', method='identifier_one_to_many', candidateCount=len(gene_choices))
            output['candidates'] = [{'key': key, 'geneKey': key, **self.masters[key]} for key in sorted(gene_choices)[:20]]
        else:
            # Human name matches are promoted only where the user confirmed the
            # project scope; explicit NCBI/UniProt IDs always override that scope.
            keys, name_method = set(), 'exact_name_candidate'
            if taxon in {'unknown', '9606'}:
                names = [record['label'], record['metadata'].get('symbol', '')]
                if any(NON_HUMAN_NAME_MARKER.search(str(name or '')) for name in names):
                    output['evidence']['sourceScopeConflict'] = {
                        'assertedTaxon': taxon, 'basis': 'explicit_nonhuman_name_marker',
                        'resolution': 'name-based human assignment suppressed pending public identifier verification',
                    }
                    taxon = 'unknown'
                # Prefer one exact NCBI canonical symbol/name over broader aliases
                # and protein-name collisions (e.g. historical aliases shared by
                # paralogs). A unique human name match is only verified when the
                # source taxon is explicit or covered by a recorded source assertion.
                for name in names:
                    if name:
                        keys.update(self.official_gene_symbols.get(name_key(name), set()))
                        for variant in identity_name_variants(name)[1:]:
                            keys.update(self.official_gene_symbols.get(name_key(variant), set()))
                if keys:
                    name_method = 'exact_ncbi_official_symbol_candidate' if any(
                        self.official_gene_symbols.get(name_key(name)) for name in names if name
                    ) else 'normalized_ncbi_official_symbol_candidate'
                else:
                    for name in names:
                        if name:
                            keys.update(self.normalized_official_gene_symbols.get(loose_name_key(name), set()))
                            for variant in identity_name_variants(name)[1:]:
                                keys.update(self.normalized_official_gene_symbols.get(loose_name_key(variant), set()))
                    if keys: name_method = 'normalized_ncbi_official_symbol_candidate'
                if not keys:
                    for name in names:
                        if name:
                            keys.update(self.official_gene_names.get(name_key(name), set()))
                            for variant in identity_name_variants(name)[1:]:
                                keys.update(self.official_gene_names.get(name_key(variant), set()))
                    if keys:
                        name_method = 'exact_ncbi_official_name_candidate' if any(
                            self.official_gene_names.get(name_key(name)) for name in names if name
                        ) else 'normalized_ncbi_official_name_candidate'
                if not keys:
                    for name in names:
                        if name:
                            keys.update(self.normalized_official_gene_names.get(loose_name_key(name), set()))
                            for variant in identity_name_variants(name)[1:]:
                                keys.update(self.normalized_official_gene_names.get(loose_name_key(variant), set()))
                    if keys: name_method = 'normalized_ncbi_official_name_candidate'
                # Some older NCBI target lists embedded a LOC GeneID in a label
                # instead of placing it in the source identifier column.
                if not keys:
                    embedded_ids = {identifier for name in names if name
                        for identifier in re.findall(r'\bLOC([1-9][0-9]*)\b', name, flags=re.I)}
                    keys = {target_key('entrez', identifier) for identifier in embedded_ids
                        if target_key('entrez', identifier) in self.masters}
                    if keys: name_method = 'embedded_ncbi_gene_id_candidate'
                if not keys:
                    for name in names:
                        if name:
                            keys.update(self.names[kind].get(name_key(name), set()))
                            for variant in identity_name_variants(name)[1:]:
                                keys.update(self.names[kind].get(name_key(variant), set()))
                    if not keys:
                        for name in names:
                            if name:
                                keys.update(self.normalized_names[kind].get(loose_name_key(name), set()))
                                for variant in identity_name_variants(name)[1:]:
                                    keys.update(self.normalized_names[kind].get(loose_name_key(variant), set()))
                        if keys: name_method = 'punctuation_normalized_name_candidate'
                # Legacy disease workbooks store protein display names, but often
                # provide a gene symbol or official NCBI name rather than a UniProt
                # protein name. Use an exact NCBI name/alias only when the protein
                # reference found no accession-level match.
                if kind == 'protein' and not keys:
                    for name in [record['label'], record['metadata'].get('symbol', '')]:
                        if name:
                            keys.update(self.gene_names.get(name_key(name), set()))
                            for variant in identity_name_variants(name)[1:]:
                                keys.update(self.gene_names.get(name_key(variant), set()))
                    if keys: name_method = 'exact_ncbi_gene_name_candidate'
                    else:
                        for name in names:
                            if name:
                                keys.update(self.normalized_gene_names.get(loose_name_key(name), set()))
                                for variant in identity_name_variants(name)[1:]:
                                    keys.update(self.normalized_gene_names.get(loose_name_key(variant), set()))
                        if keys: name_method = 'punctuation_normalized_ncbi_gene_candidate'
            # Several UniProt protein entries can represent isoforms or records
            # for the same gene. Preserve one gene-level candidate when every
            # accession points to the same Entrez GeneID; the protein accession
            # itself remains unverified.
            if taxon != 'unknown':
                keys = {key for key in keys if self.masters[key]['taxon_key'] == taxon}
            if kind == 'protein' and len(keys) > 1:
                gene_keys = {self.gene_for(key) for key in keys}
                if len(gene_keys) == 1 and None not in gene_keys:
                    keys = gene_keys
                    name_method = 'unique_gene_from_protein_candidates'
            taxon_evidence = record.get('taxonEvidence') or {}
            if len(keys) == 1 and taxon == '9606' and not record['ids'] and taxon_evidence.get('basis') in {
                    'entity_taxon_field', 'user_confirmed_project_scope_human_with_public_id_override'}:
                key = next(iter(keys))
                gene = self.gene_for(key)
                if kind == 'gene' and key.startswith('uniprot:'):
                    # A protein accession alone cannot resolve a gene record
                    # when UniProt links it to multiple genes.
                    if gene:
                        key, gene = gene, gene
                    else:
                        key = None
                if key:
                    evidence_method = 'unique_name_source_species_confirmed' if record.get('taxonEvidence', {}).get('basis') == 'user_confirmed_project_scope_human_with_public_id_override' else 'unique_name_taxon_confirmed'
                    output.update(status='verified', master=key, gene=gene or (key if key.startswith('entrez:') else None),
                        method=evidence_method, candidateCount=1)
                    output['evidence']['nameResolutionMethod'] = name_method
                    output['evidence']['identityEvidence'] = 'one unique exact human NCBI/UniProt identity matched under user-confirmed human project scope'
                    output['evidence']['unresolvedIdentifiers'] = unresolved
                    output['candidates'] = [{'key': key, 'geneKey': gene or (key if key.startswith('entrez:') else None),
                        **self.masters[key], 'referenceSources': sorted(self.master_sources[key])}]
                    return output
            output.update(status='candidate' if len(keys) == 1 else 'ambiguous' if keys else 'unmapped',
                method=name_method if keys else 'no_reference_identity', candidateCount=len(keys))
            output['evidence']['nameResolutionMethod'] = name_method if keys else 'no_reference_identity'
            output['candidates'] = [{'key': key, 'geneKey': self.gene_for(key), **self.masters[key],
                'referenceSources': sorted(self.master_sources[key])}
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
            source_slug = e['source_release__source__slug'] or (e['metadata'] or {}).get('source', 'global')
            original_taxon = e['taxon_key'] or 'unknown'
            assertion = SOURCE_SPECIES_ASSERTIONS.get(source_slug) if original_taxon == 'unknown' else None
            marker_names = [e['label'], metadata.get('symbol', '')]
            if assertion and any(NON_HUMAN_NAME_MARKER.search(str(name or '')) for name in marker_names):
                assertion = {**assertion, 'taxon': 'unknown', 'basis': 'explicit_nonhuman_name_marker'}
            taxon_evidence = ({**assertion, 'sourceSlug': source_slug, 'evidenceType': 'source_level_user_confirmation'}
                if assertion and assertion['taxon'] != 'unknown' else {'taxon': original_taxon, 'basis': assertion['basis'], 'sourceSlug': source_slug}
                if assertion else {'taxon': original_taxon, 'basis': 'entity_taxon_field', 'sourceSlug': source_slug}
                if original_taxon != 'unknown' else None)
            record = {'id': e['id'], 'kind': e['entity_type'], 'taxon': original_taxon,
                'resolutionTaxon': assertion['taxon'] if assertion else original_taxon,
                'taxonEvidence': taxon_evidence, 'label': e['label'],
                'metadata': metadata, 'sourceReleaseId': e['source_release_id'], 'ids': [],
                'source': source_slug}
            config = e['source_release__source__configuration'] or {}
            if config.get('connector') == 'uniprot-human-catalog' and metadata.get('accession'):
                # Explicit accession carried by the original reviewed UniProt entry,
                # not a gene/protein equality inferred from a name.
                record['ids'].append(['uniprot', str(metadata['accession'])])
            source_identifier = str(metadata.get('sourceIdentifier') or '').strip().upper()
            if original_taxon == 'unknown' and ACCESSION.fullmatch(source_identifier):
                record['ids'].append(['uniprot', source_identifier])
            rows[e['id']] = record
        identifier_query = {'entity_id__in': batch.order_by().values('pk'), 'namespace__in': STRONG_NAMESPACES}
        ids = CanonicalIdentifier.objects.filter(**identifier_query).filter(Q(source__isnull=True) | Q(source__enabled=True))
        aliases = EntityIdentifier.objects.filter(**identifier_query, is_active=True, source_release__source__enabled=True)
        for model_rows in [ids.values_list('entity_id', 'namespace', 'identifier'), aliases.values_list('entity_id', 'namespace', 'identifier')]:
            for pk, ns, value in model_rows: rows[pk]['ids'].append([ns, value])
        source_ids = SourceEntityMapping.objects.filter(
            entity_id__in=batch.order_by().values('pk'), namespace__in=STRONG_NAMESPACES,
        ).filter(Q(source_release__source__isnull=True) | Q(source_release__source__enabled=True))
        for pk, ns, value in source_ids.values_list('entity_id', 'namespace', 'source_entity_id'):
            rows[pk]['ids'].append([ns, value])
        if supplement_id:
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


def build_target_identities(manifest_path, *, ncbi_gene_manifest_path=None,
        ncbi_taxonomy_manifest_path=None, uniprot_taxonomy_manifest_path=None, apply=False):
    manifest, rows = load_reference(manifest_path)
    gene_manifest, gene_rows, reference_gene_count = (None, [], 0)
    taxonomy_manifest, taxonomy_rows = (None, [])
    uniprot_taxonomy_manifest, uniprot_taxonomy_rows = (None, [])
    profiles = input_profiles()
    if ncbi_gene_manifest_path:
        from .connectors.ncbi_gene_reference import load_reference as load_ncbi_gene_reference, select_matching_rows
        gene_manifest, all_gene_rows = load_ncbi_gene_reference(ncbi_gene_manifest_path)
        reference_gene_count = len(all_gene_rows)
        requested_names = {name for profile in profiles.values()
            for name in [profile['label'], profile['metadata'].get('symbol', '')] if name}
        gene_rows = select_matching_rows(all_gene_rows, requested_names)
        del all_gene_rows
    if ncbi_taxonomy_manifest_path:
        taxonomy_manifest, taxonomy_rows = load_taxonomy_reference(ncbi_taxonomy_manifest_path)
        gene_rows.extend(taxonomy_rows)
    if uniprot_taxonomy_manifest_path:
        uniprot_taxonomy_manifest, uniprot_taxonomy_rows = load_uniprot_taxonomy_reference(
            uniprot_taxonomy_manifest_path)
        rows.extend(uniprot_taxonomy_rows)
    index = ReferenceIndex(rows, gene_rows)
    fingerprint = digest([profiles[pk] for pk in sorted(profiles)])
    resolutions = {pk: index.resolve(record) for pk, record in profiles.items()}
    counts = dict(Counter(r['status'] for r in resolutions.values()))
    reference_checksums = {'uniprotReviewedHuman': manifest['sha256']}
    if gene_manifest: reference_checksums['ncbiGeneHuman'] = gene_manifest['sha256']
    if taxonomy_manifest: reference_checksums['ncbiGeneTaxonomy'] = taxonomy_manifest['sha256']
    if uniprot_taxonomy_manifest: reference_checksums['uniprotTaxonomy'] = uniprot_taxonomy_manifest['sha256']
    combined_reference_sha = digest(reference_checksums)
    reference_catalogs = {'uniprotReviewedHuman': manifest}
    if gene_manifest: reference_catalogs['ncbiGeneHuman'] = gene_manifest
    if taxonomy_manifest: reference_catalogs['ncbiGeneTaxonomy'] = taxonomy_manifest
    if uniprot_taxonomy_manifest: reference_catalogs['uniprotTaxonomy'] = uniprot_taxonomy_manifest
    ncbi_version = f"+ncbi-{gene_manifest['sha256'][:10]}" if gene_manifest else ''
    taxonomy_version = f"+tax-{taxonomy_manifest['sha256'][:10]}" if taxonomy_manifest else ''
    uniprot_version = f"+up-tax-{uniprot_taxonomy_manifest['sha256'][:10]}" if uniprot_taxonomy_manifest else ''
    source_species_assertions = {slug: SOURCE_SPECIES_ASSERTIONS[slug]
        for slug in sorted({profile['source'] for profile in profiles.values()}) if slug in SOURCE_SPECIES_ASSERTIONS}
    version = f"{manifest['version']}+{manifest['sha256'][:12]}{ncbi_version}{taxonomy_version}{uniprot_version}+{fingerprint[:12]}+v7"
    result = {'version': version, 'resolverVersion': RESOLVER_VERSION, 'referenceProteins': len(rows),
        'referenceGenes': reference_gene_count, 'indexedGeneRecords': len(gene_rows),
        'standardTargets': len(index.masters), 'inputRecords': len(profiles), 'statuses': counts,
        'referenceSha256': combined_reference_sha, 'referenceCatalogs': reference_catalogs,
        'sourceSpeciesAssertions': source_species_assertions,
        'publicTaxa': {taxon: name for taxon, name in sorted(index.taxon_names.items())},
        'inputSha256': fingerprint, 'applied': False}
    if not apply: return result
    # All inserts and the publication pointer switch commit together. Failure
    # leaves the previous reference/current result available and never merges FKs.
    with transaction.atomic():
        source, _ = DataSource.objects.get_or_create(slug=SOURCE_SLUG, defaults={'name': 'NCBI Gene / UniProtKB 跨物种靶点标准参考',
            'access_mode': 'download', 'documentation_url': 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi',
            'license_note': 'Public identifier cross-reference; NCBI Gene and UniProtKB (CC BY 4.0). Queries use identifiers only and exclude local case records.',
            'configuration': {'connector': 'target-identity-reference-multispecies'}})
        source = DataSource.objects.select_for_update().get(pk=source.pk)
        source.name = 'NCBI Gene / UniProtKB 跨物种靶点标准参考'
        source.documentation_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi'
        source.license_note = 'Public identifier cross-reference; NCBI Gene and UniProtKB (CC BY 4.0). Queries use identifiers only and exclude local case records.'
        source.configuration = {**source.configuration, 'connector': 'target-identity-reference-multispecies'}
        release, fresh = SourceRelease.objects.get_or_create(source=source, version=version, defaults={
            'checksum_sha256': combined_reference_sha, 'metadata': {'identityState': 'building', 'reference': manifest,
                'referenceCatalogs': reference_catalogs, **result}})
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
        source.last_success_at = timezone.now(); source.save(update_fields=['name', 'documentation_url', 'license_note', 'configuration', 'last_success_at'])
    return {**result, 'applied': True, 'releaseId': release.pk}
