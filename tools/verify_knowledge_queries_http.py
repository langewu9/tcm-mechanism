"""Actual localhost query, queue, frozen export and private-access verification.

Retains three real source-data analyses. A journal prevents duplicate submission
on resume. Existing research and catalogue records must remain unchanged.
"""
import argparse
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import sys

from audit_knowledge_queries import JOB, IMPORT, norm
from postgres_acceptance import APP, VAR, environment
from smoke_local_workspace import LocalClient, wait_task


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    environment(); sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.core.serializers.json import DjangoJSONEncoder
    from apps.core.models import AnalysisTask, ResearchDataset, MedicalCase, VisualizationArtifact, DataSource, SourceRelease
    state_path = JOB / 'http-state.json'
    output = JOB / 'http-verified.json'
    if output.exists():
        raise ValueError('Completed proof exists; do not repeat submissions.')
    comparisons = json.loads((JOB / 'query-comparison-first.json').read_text())
    assert comparisons['passed']
    sample = json.loads((JOB / 'original-query-samples.json').read_text())
    import_state = json.loads((IMPORT / 'apply-state.json').read_text())
    providers = {entry['sourceId']: entry['provider'] for entry in import_state['sources']}
    releases = dict(SourceRelease.objects.filter(source_id__in=providers).values_list('pk', 'source_id'))
    def row_hashes(model):
        return {str(row['id']): digest(json.loads(json.dumps(row, cls=DjangoJSONEncoder))) for row in model.objects.order_by('pk').values()}
    models = (AnalysisTask, ResearchDataset, MedicalCase, VisualizationArtifact, DataSource)
    if state_path.exists():
        if not args.resume:
            raise ValueError('Inspect journal and use --resume explicitly.')
        state = json.loads(state_path.read_text())
    else:
        state = {'before': {model._meta.label: row_hashes(model) for model in models}, 'tasks': {}, 'complete': False}
    def save_state():
        temporary = state_path.with_suffix('.partial')
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2));temporary.chmod(0o600);temporary.replace(state_path)
    save_state()
    def old_rows_unchanged():
        for model in models:
            current = row_hashes(model)
            assert all(current.get(pk) == value for pk, value in state['before'][model._meta.label].items()), model._meta.label
    old_rows_unchanged()
    accounts = json.loads((VAR / 'accounts.json').read_text())
    client = LocalClient(accounts['a'], base_url='http://127.0.0.1:5174', csrf_cookie_name='tcm_pg_csrf')
    other = LocalClient(accounts['b'], base_url='http://127.0.0.1:5174', csrf_cookie_name='tcm_pg_csrf')
    originals = [row for row in sample['rows'] if row['accepted']]
    def source_keys(records):
        return {(providers[releases[int(row['sourceReleaseId'])]], int(row['sourceRowId']), row['relationType']) for row in records}
    def expected_keys(kind, query):
        selected = [row for row in originals if norm(row[kind]) == norm(query)]
        keys = set()
        for row in selected:
            if row['herb'] and row['compound']:
                keys.add((row['provider'], row['row'], 'contains'))
            if row['compound'] and row['target'] and (kind != 'herb' or row['herb']):
                keys.add((row['provider'], row['row'], 'targets'))
        return keys
    report = {'previewQueries': [], 'retainedTasks': [], 'externalCalls': False}
    # Read all representative inputs through the same HTTP proxy as the UI.
    for case in comparisons['cases']:
        kind, query = case['queryType'], case['query']
        _, response = client.request('/api/v1/catalog/herb-evidence/batch/', method='POST', data={'queryType': kind, 'queries': [query]})
        item = response['results'][0]
        assert item['truncated'] == case['preview']['truncated']
        assert len(item['relations']) == case['preview']['sourceRelations']
        actual = source_keys(item['relations']); expected = expected_keys(kind, query)
        assert len(actual) == len(item['relations']) and actual <= expected
        if not item['truncated']:
            assert actual == expected
        assert all(row.get('sourceOrigin', {}).get('sourceRow') == row['sourceRowId'] for row in item['relations'])
        report['previewQueries'].append({'queryType': kind, 'query': query, 'relations': len(actual), 'truncated': item['truncated'], 'originalRowSubsetVerified': True})
    long_query = next(case['query'] for case in comparisons['cases'] if case['queryType'] == 'compound' and any(
        entry['provider'] == 'tcmsp' and entry['stratum'] == 'over120' for entry in case['selection']))
    plans = [('herb', '麻黄'), ('compound', long_query), ('intersection', '石榴皮')]
    for kind, query in plans:
        key = kind + ':' + query
        if key not in state['tasks']:
            if kind == 'intersection':
                path = '/api/v1/analysis/network-pharmacology/'
                parameters = {'herb': query, 'disease': '肺纤维化', 'complete': True}
            else:
                _, preview = client.request('/api/v1/catalog/herb-evidence/batch/', method='POST', data={'queryType': kind, 'queries': [query]})
                path = '/api/v1/catalog/herb-evidence/analyses/'
                parameters = {'queryType': kind, 'queries': [query], 'expectedResultSha256': preview['resultSha256'], 'complete': True}
            _, queued = client.request(path, method='POST', data=parameters, expected=202)
            state['tasks'][key] = queued['id'];save_state()
        task = wait_task(client, state['tasks'][key])
        manifest = task['result']['snapshot'];assert manifest['complete']
        base = f'/api/v1/research/analysis-tasks/{task["id"]}'
        _, exported = client.request(base + '/snapshot-export/?file_format=jsonl')
        lines = [json.loads(line) for line in exported.decode().splitlines()]
        header = lines[0]
        checksum = header['snapshot'].pop('sha256')
        assert checksum == manifest['sha256'] == digest({'parameters': header['parameters'], 'result': header['result'], 'manifest': header['snapshot']})
        tables = {}
        for row in lines[1:]:
            tables.setdefault(row['table'], []).append(row['payload'])
        for table, info in manifest['tables'].items():
            rows = tables.get(table, [])
            assert len(rows) == info['count']
            assert hashlib.sha256(''.join(canonical(row) + '\n' for row in rows).encode()).hexdigest() == info['sha256']
        _, csv_bytes = client.request(base + '/snapshot-export/?table=evidenceRecords&file_format=csv')
        csv_rows = list(csv.DictReader(io.StringIO(csv_bytes.decode('utf-8-sig'))))
        assert len(csv_rows) == len(tables['evidenceRecords']) and source_keys(csv_rows) == source_keys(tables['evidenceRecords'])
        if kind != 'intersection':
            expected = expected_keys(kind, query)
            assert source_keys(tables['evidenceRecords']) == expected and len(tables['evidenceRecords']) == len(expected)
        else:
            expected = next(case for case in comparisons['intersections'] if case['herb'] == query and case['disease'] == '肺纤维化')
            for metric, value in expected['expectedSummaryFromOriginalRows'].items():
                assert task['result']['summary'][metric] == value
            assert task['result']['summary']['expandedDiseaseQueries'][1] == 'Pulmonary fibrosis'
            for table, count in expected['rawCounts'].items():
                assert len(tables.get(table, [])) == count
        other.request(base + '/', expected=404);other.request(base + '/snapshot-export/', expected=404)
        report['retainedTasks'].append({'kind': kind, 'query': query, 'id': task['id'], 'csvRows': len(csv_rows),
            'snapshotSha256': manifest['sha256'], 'tableCounts': {name: info['count'] for name, info in manifest['tables'].items()},
            'allFrozenHashesMatch': True, 'otherOwnerDenied': True})
        print(json.dumps(report['retainedTasks'][-1], ensure_ascii=False), flush=True)
    old_rows_unchanged()
    state['complete'] = True;save_state()
    report.update(passed=True, oldResearchAndSourcesUnchanged=True, previousTaskCount=len(state['before']['core.AnalysisTask']))
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2));output.chmod(0o600)
    print(json.dumps({'passed': True, 'previewQueries': len(report['previewQueries']), 'retainedTaskIds': state['tasks'], 'previousRecordsUnchanged': True}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
