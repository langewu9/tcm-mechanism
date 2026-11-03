"""Compare verified species-qualified identities without rewriting source evidence."""
from collections import Counter, defaultdict
from apps.core.models import TargetIdentityMapping
from apps.sources.target_identity import RESOLVER_VERSION, current_release, digest, input_profiles


def verified_target_node_identities(entity_ids, *, profiles=None):
    """Return only current, verified human target identities for graph node merging."""
    release = current_release()
    ids = sorted(set(entity_ids))
    if not release or not ids:
        return {}
    profiles = profiles if profiles is not None else input_profiles(ids)
    rows = list(TargetIdentityMapping.objects.filter(
        reference_release=release, status='verified', entity_id__in=ids,
    ).select_related('master', 'gene').order_by('entity_id'))
    current_rows = {}
    genes_by_master = defaultdict(set)
    for row in rows:
        profile = profiles.get(row.entity_id)
        if not profile or row.input_sha256 != digest(profile) or not row.master_id:
            continue
        master = row.master
        if master.taxon_key != '9606':
            continue
        current_rows[row.entity_id] = row
        if row.gene_id and row.gene.taxon_key == '9606' and row.gene.namespace == 'entrez':
            genes_by_master[row.master_id].add(row.gene)

    # Prefer a human gene key whenever the same verified master accession has
    # an unambiguous Entrez crosswalk elsewhere in this comparison set. This
    # lets an accession-only row merge with a gene-mapped row without guessing.
    unique_gene_by_master = {
        master_id: next(iter(genes)) for master_id, genes in genes_by_master.items() if len(genes) == 1
    }
    result = {}
    for entity_id, row in current_rows.items():
        master = row.master
        gene = row.gene if row.gene_id and row.gene.taxon_key == '9606' else unique_gene_by_master.get(row.master_id)
        canonical = gene or master
        if canonical.namespace not in {'entrez', 'uniprot'} or canonical.taxon_key != '9606':
            continue
        result[row.entity_id] = {
            'key': canonical.key,
            'namespace': canonical.namespace,
            'identifier': canonical.identifier,
            'label': canonical.symbol or canonical.label,
            'taxonKey': canonical.taxon_key,
            'masterKey': master.key,
            'geneKey': row.gene_id if row.gene_id and row.gene.taxon_key == '9606' else None,
            'referenceReleaseId': release.pk,
        }
    return result


def compare_target_identities(herb_ids, disease_ids, *, profiles=None):
    release = current_release()
    if not release:
        return {'available': False, 'version': RESOLVER_VERSION, 'reason': '尚未发布标准靶点映射。'}
    ids = set(herb_ids) | set(disease_ids)
    profiles = profiles if profiles is not None else input_profiles(ids)
    mappings = {}
    ordered = sorted(ids)
    for start in range(0, len(ordered), 500):
        for row in TargetIdentityMapping.objects.filter(reference_release=release,
                entity_id__in=ordered[start:start+500]).select_related('master', 'gene'):
            if row.entity_id in profiles and row.input_sha256 == digest(profiles[row.entity_id]): mappings[row.entity_id] = row

    def side(side_ids):
        genes, proteins, pending_genes = defaultdict(set), defaultdict(set), defaultdict(set)
        statuses = Counter()
        for pk in side_ids:
            row = mappings.get(pk)
            statuses[row.status if row else 'unmapped'] += 1
            if row and row.status == 'verified':
                if row.gene_id: genes[row.gene_id].add(pk)
                if row.master.namespace == 'uniprot': proteins[row.master_id].add(pk)
            elif row and row.status in {'candidate', 'ambiguous'}:
                candidate_genes = {candidate['geneKey'] for candidate in row.candidates if candidate.get('geneKey')}
                # Broad functional names can refer to many unrelated genes.
                # Only a complete, single-gene proposal is a common candidate;
                # one-to-many/truncated proposals stay in the unresolved total.
                if len(candidate_genes) == 1 and row.candidate_count == len(row.candidates):
                    pending_genes[next(iter(candidate_genes))].add(pk)
        verified_records = statuses['verified']
        pending_records = sum(count for status, count in statuses.items() if status != 'verified')
        return {'genes': genes, 'proteins': proteins, 'pending': pending_genes,
                'summary': {'records': verified_records + pending_records, 'verifiedRecords': verified_records,
                    'pendingRecords': pending_records, 'statuses': dict(statuses),
                    'geneUnresolvedRecords': sum(1 for pk in side_ids if pk in mappings and mappings[pk].status == 'verified' and not mappings[pk].gene_id),
                    'genes': len(genes), 'proteins': len(proteins)}}

    herb, disease = side(set(herb_ids)), side(set(disease_ids))
    gene_overlap = set(herb['genes']) & set(disease['genes'])
    protein_overlap = set(herb['proteins']) & set(disease['proteins'])
    pending_overlap = ((set(herb['genes']) | set(herb['pending'])) &
                       (set(disease['genes']) | set(disease['pending']))) - gene_overlap

    def record(pk):
        p, row = profiles[pk], mappings.get(pk)
        return {'entityId': pk, 'label': p['label'], 'source': p['source'], 'originalTaxon': p['taxon'],
            'taxonEvidence': row.evidence.get('taxonEvidence') if row else p.get('taxonEvidence'),
            'status': row.status if row else 'unmapped', 'method': row.match_method if row else '',
            'masterKey': row.master_id if row else None, 'geneKey': row.gene_id if row else None}

    def shared(keys, name, pending=False):
        result = []
        for key in sorted(keys)[:100]:
            a = set(herb[name].get(key, set()))
            b = set(disease[name].get(key, set()))
            if pending:
                a |= herb['pending'].get(key, set()); b |= disease['pending'].get(key, set())
            masters = [mappings[pk].gene if name == 'genes' else mappings[pk].master for pk in a|b
                       if pk in mappings and mappings[pk].status == 'verified']
            master = next((m for m in masters if m and m.key == key), None)
            label = master.symbol or master.label if master else ''
            if not label:
                label = next((c.get('symbol') or c['label'] for pk in a|b if pk in mappings
                    for c in mappings[pk].candidates if c.get('geneKey') == key), key)
            result.append({'key': key, 'label': label, 'taxon': '9606',
                'herbRecords': [record(pk) for pk in sorted(a)[:20]],
                'diseaseRecords': [record(pk) for pk in sorted(b)[:20]],
                'recordCounts': {'herb': len(a), 'disease': len(b)}})
        return result

    return {'available': True, 'version': RESOLVER_VERSION, 'releaseId': release.pk,
        'comparisonVersion': 'target-identity-comparison-v2',
        'referenceVersion': release.version, 'referenceSha256': release.checksum_sha256,
        'referenceCatalogs': release.metadata.get('referenceCatalogs', {}),
        'sourceSpeciesAssertions': release.metadata.get('sourceSpeciesAssertions', {}),
        'referenceTaxon': '9606', 'herb': herb['summary'], 'disease': disease['summary'],
        'verifiedGeneIntersectionCount': len(gene_overlap), 'verifiedProteinIntersectionCount': len(protein_overlap),
        'pendingGeneOverlapCount': len(pending_overlap),
        'geneIntersections': shared(gene_overlap, 'genes'), 'proteinIntersections': shared(protein_overlap, 'proteins'),
        'pendingCandidates': shared(pending_overlap, 'genes', pending=True),
        'pendingRowsTruncated': len(pending_overlap) > 100,
        'policy': 'Only verified standard identifiers count. Gene and protein levels are separate; unknown-species name matches remain candidates.',
    }
