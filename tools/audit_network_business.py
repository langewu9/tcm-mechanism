"""Read-only network statistics and graph audit against retained original rows.

Uses the independently extracted workbook sample, never current query output as
its business oracle. No identity merges, imports, external calls or task writes.
"""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import sys

from audit_knowledge_queries import IMPORT, JOB as ORIGINAL_JOB, clean, norm, sha
from postgres_acceptance import APP, environment

ROOT = Path(__file__).resolve().parents[1]
JOB = ROOT / 'python_app/var/network-business-2026-10-21'
CASES = [
    ('牛角尖粉', '肺纤维化'), ('石榴皮', '肺纤维化'), ('白茅根', '肺纤维化'),
    ('麻黄', '肺纤维化'), ('石榴皮、白茅根', '肺纤维化'),
    ('石榴皮、石榴皮', '肺纤维化'), ('NO_LOCAL_NETWORK_HERB', 'NO_LOCAL_NETWORK_DISEASE'),
]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def key_digest(keys):
    return digest(sorted(keys))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=JOB / 'original-row-audit.json')
    args = parser.parse_args()
    JOB.mkdir(mode=0o700, exist_ok=True)
    output = args.output
    if output.exists():
        raise ValueError('Refusing to replace previous audit evidence.')
    sample = json.loads((ORIGINAL_JOB / 'original-query-samples.json').read_text())
    for source in sample['sources']:
        assert sha(IMPORT / 'inputs' / source['file']) == source['sha256']
    originals = [row for row in sample['rows'] if row['accepted']]
    state = json.loads((IMPORT / 'apply-state.json').read_text())
    provider_by_source = {row['sourceId']: row['provider'] for row in state['sources']}
    environment();sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.db import connection, transaction
    from apps.core.models import SourceRelease
    from apps.core.services.network_pharmacology import build_network_pharmacology
    from apps.core.services.herb_evidence import _entity_record
    def row_key(row, kind):
        column = {'herb': 'Herb ID', 'compound': 'Compound Id', 'target': 'Target ID'}[kind]
        return row['provider'], kind, clean(row['raw'][column]) if row['provider'] == 'hit' else norm(row[kind])
    report = {'cases': [], 'databaseReadOnly': True, 'externalCalls': False, 'identityMerged': False,
              'originalSampleSha256': sha(ORIGINAL_JOB / 'original-query-samples.json')}
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION READ ONLY')
            cursor.execute("SET LOCAL statement_timeout='60s'")
        providers = {pk: provider_by_source[source] for pk, source in SourceRelease.objects.filter(
            source_id__in=provider_by_source).values_list('pk', 'source_id')}
        def entity_key(entity):
            kind = 'target' if entity['entityType'] in {'gene', 'protein'} else entity['entityType']
            return providers[entity['sourceReleaseId']], kind, entity.get('sourceEntityId') or norm(entity['label'])
        for herb, disease in CASES:
            names = {norm(name) for name in herb.split('、')}
            herb_rows = [row for row in originals if norm(row['herb']) in names and row['compound']]
            disease_names = {'肺纤维化', 'pulmonary fibrosis', 'idiopathic pulmonary fibrosis', 'interstitial lung disease'} if disease == '肺纤维化' else {norm(disease)}
            disease_rows = [row for row in sample['diseaseRows'] if norm(row['raw']['疾病']) in disease_names
                and clean(row['raw']['靶点基因']) and (row['table'] == 'diseaseTarget' or clean(row['raw']['中药']))]
            direct_rows = [row for row in disease_rows if row['table'] == 'diseaseHerbTarget' and norm(row['raw']['中药']) in names]
            herb_targets = {row_key(row, 'target') for row in herb_rows if row['target']}
            disease_targets = {('disease', 'target', norm(row['raw']['靶点基因'])) for row in disease_rows}
            direct_targets = {('disease', 'target', norm(row['raw']['靶点基因'])) for row in direct_rows}
            candidates = herb_targets & disease_targets | direct_targets
            compounds = {row_key(row, 'compound') for row in herb_rows}
            expected_summary = {'herbTargetCount': len(herb_targets), 'diseaseTargetCount': len(disease_targets),
                'strictIntersectionCount': len(herb_targets & disease_targets), 'directAssociationTargetCount': len(direct_targets),
                'candidateTargetCount': len(candidates), 'componentCount': len(compounds), 'pathwayCount': 0}
            expected_evidence = {(row['provider'], row['row'], 'contains') for row in herb_rows}
            expected_evidence.update((row['provider'], row['row'], 'targets') for row in herb_rows if row['target'])
            expected_evidence.update(('disease', row['row'], 'disease_target' if row['table'] == 'diseaseTarget' else 'disease_herb_target') for row in disease_rows)
            expected_raw = {'herbLinks': {(row['provider'], row['row']) for row in herb_rows if row['target']},
                'diseaseTargets': {('disease', row['row']) for row in disease_rows if row['table'] == 'diseaseTarget'},
                'diseaseHerbLinks': {('disease', row['row']) for row in disease_rows if row['table'] == 'diseaseHerbTarget'},
                'directDiseaseHerbLinks': {('disease', row['row']) for row in direct_rows}}
            expected_endpoints = {}
            for row in herb_rows:
                expected_endpoints[(row['provider'], row['row'], 'contains')] = (row_key(row, 'herb'), row_key(row, 'compound'))
                if row['target']:
                    expected_endpoints[(row['provider'], row['row'], 'targets')] = (row_key(row, 'compound'), row_key(row, 'target'))
            for row in disease_rows:
                kind = 'disease_target' if row['table'] == 'diseaseTarget' else 'disease_herb_target'
                expected_endpoints[('disease', row['row'], kind)] = (('disease', 'disease', norm(row['raw']['疾病'])), ('disease', 'target', norm(row['raw']['靶点基因'])))
            captured, entities, graph_endpoints = {}, {}, {}
            def capture_entities(rows):
                entities.update((row.pk, _entity_record(row)) for row in rows)
            def capture(stage, rows):
                for row in rows:
                    key = providers[row.source_release_id], int(row.source_record_id.split(':')[1]), row.relation_type
                    captured[row.pk] = key
                    assert (entity_key(_entity_record(row.subject)), entity_key(_entity_record(row.object))) == expected_endpoints[key]
                    graph_endpoints[(row.source_release.source.slug, row.source_record_id, row.relation_type)] = (row.subject.stable_id, row.object.stable_id)
                    capture_entities((row.subject, row.object))
            data = build_network_pharmacology(user=None, herb_query=herb, disease_query=disease, row_limit=50000,
                complete=True, persist=False, capture_relations=capture, capture_entities=capture_entities)
            assert set(captured.values()) == expected_evidence and len(captured) == len(expected_evidence), herb
            assert {key: data['summary'][key] for key in expected_summary} == expected_summary, herb
            assert not any(data['rawLimits']['inputRelationsTruncated'].values()) and not any(data['rawLimits']['tablesTruncated'].values())
            assert {entity_key(entities[target['entityId']]) for target in data['targets']} == candidates
            disease_counts = Counter(norm(row['raw']['靶点基因']) for row in disease_rows)
            direct_counts = Counter(norm(row['raw']['靶点基因']) for row in direct_rows)
            for target in data['targets']:
                key = entity_key(entities[target['entityId']])
                assert target['herbEvidenceCount'] == 0 and target['components'] == [] and target['pathways'] == []
                assert target['matchType'] == '疾病—中药直接关联'
                assert target['diseaseEvidenceCount'] == disease_counts[key[2]] and target['directEvidenceCount'] == direct_counts[key[2]]
                expected_sources = {('disease', row['row'], 'disease_target' if row['table'] == 'diseaseTarget' else 'disease_herb_target')
                    for row in disease_rows if norm(row['raw']['靶点基因']) == key[2]}
                actual_sources = {(providers[row['sourceReleaseId']], int(row['sourceRecordId'].split(':')[1]), row['relationType']) for row in target['sources']}
                assert actual_sources == expected_sources and len(target['sources']) == len(expected_sources)
            for table, keys in expected_raw.items():
                rows = data['raw'][table]
                actual = {(providers[row['sourceReleaseId']], int(row['sourceRecordId'].split(':')[1])) for row in rows}
                assert actual == keys and len(rows) == len(keys), (herb, table)
                if table == 'herbLinks':
                    assert all(row['herbSourceReleaseId'] == row['sourceReleaseId'] and row['herbSourceRecordId'].split(':')[1] == row['sourceRecordId'].split(':')[1] for row in rows)
            expected_charts = {'overlap': [{'name': label, 'value': expected_summary[key]} for label, key in
                [('中药靶点', 'herbTargetCount'), ('疾病靶点', 'diseaseTargetCount'), ('严格交集', 'strictIntersectionCount'), ('直接关联', 'directAssociationTargetCount')]],
                'components': [], 'pathways': []}
            assert data['charts'] == expected_charts
            graph = data['network'];ids = {node['id'] for node in graph['nodes']}
            assert len(ids) == len(graph['nodes']) <= 2000 and len(graph['links']) <= 4000
            assert all(edge['source'] in ids and edge['target'] in ids for edge in graph['links'])
            assert all((edge['source'], edge['target']) == graph_endpoints[(edge['sourceSlug'], edge['sourceRecordId'], edge['relation'])] for edge in graph['links'])
            assert graph['totalLinkCount'] == len(expected_evidence)
            assert graph['totalNodeCount'] == len(entities)
            assert data['limits']['nodesTruncated'] == (len(ids) < len(entities))
            assert data['limits']['linksTruncated'] == (len(graph['links']) < len(expected_evidence))
            item = {'herb': herb, 'disease': disease, 'summary': expected_summary, 'charts': expected_charts,
                'evidenceCount': len(expected_evidence), 'evidenceKeySha256': key_digest(expected_evidence),
                'rawCounts': {key: len(value) for key, value in expected_raw.items()},
                'rawKeySha256': {key: key_digest(value) for key, value in expected_raw.items()},
                'targetIdentitySha256': key_digest(candidates), 'graph': {'nodes': len(ids), 'links': len(graph['links']),
                    'totalNodes': graph['totalNodeCount'], 'totalLinks': graph['totalLinkCount'], 'noDanglingLinks': True,
                    'originalEndpointIdentitiesMatch': True},
                'inputTruncated': False, 'graphTruncated': data['limits']['nodesTruncated'] or data['limits']['linksTruncated']}
            report['cases'].append(item);print(json.dumps(item, ensure_ascii=False), flush=True)
    for source in sample['sources']:
        assert sha(IMPORT / 'inputs' / source['file']) == source['sha256']
    report.update(passed=True, originalFilesUnchanged=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2));output.chmod(0o600)
    print(json.dumps({'passed': True, 'cases': len(report['cases'])}))


if __name__ == '__main__':
    main()
