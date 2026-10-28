"""Compare verified species-qualified identities without rewriting source evidence."""
from collections import Counter, defaultdict
from apps.core.models import TargetIdentityMapping
from apps.sources.target_identity import RESOLVER_VERSION, current_release, digest, input_profiles


def compare_target_identities(herb_ids, disease_ids):
    release = current_release()
    if not release:
        return {'available': False, 'version': RESOLVER_VERSION, 'reason': '尚未发布标准靶点映射。'}
    ids = set(herb_ids) | set(disease_ids)
    profiles = input_profiles(ids)
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
        return {'genes': genes, 'proteins': proteins, 'pending': pending_genes,
                'summary': {'records': len(side_ids), 'verifiedRecords': statuses['verified'],
                    'pendingRecords': len(side_ids)-statuses['verified'], 'statuses': dict(statuses),
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
        'referenceTaxon': '9606', 'herb': herb['summary'], 'disease': disease['summary'],
        'verifiedGeneIntersectionCount': len(gene_overlap), 'verifiedProteinIntersectionCount': len(protein_overlap),
        'pendingGeneOverlapCount': len(pending_overlap),
        'geneIntersections': shared(gene_overlap, 'genes'), 'proteinIntersections': shared(protein_overlap, 'proteins'),
        'pendingCandidates': shared(pending_overlap, 'genes', pending=True),
        'pendingRowsTruncated': len(pending_overlap) > 100,
        'policy': 'Only verified standard identifiers count. Gene and protein levels are separate; unknown-species name matches remain candidates.',
    }
