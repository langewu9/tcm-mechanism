"""Verify two retained real network analyses and local R artifacts end to end.

Localhost only. Uses an explicit journal for two new analyses and two renders;
never modifies prior research, knowledge identities, or external services.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

from audit_network_business import JOB, canonical, digest, key_digest
from postgres_acceptance import APP, VAR, environment
from smoke_local_workspace import LocalClient, wait_task


def main():
    parser = argparse.ArgumentParser(description=__doc__);parser.add_argument('--resume', action='store_true');args = parser.parse_args()
    output, journal = JOB / 'http-verified.json', JOB / 'http-state.json'
    if output.exists():
        raise ValueError('Completed proof exists; do not repeat real task submissions.')
    audit = json.loads((JOB / 'original-row-audit.json').read_text());assert audit['passed']
    environment();sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.conf import settings
    from django.core.files.storage import default_storage
    from django.core.serializers.json import DjangoJSONEncoder
    from django.db.models import Max
    from apps.core.models import AnalysisTask, ResearchDataset, MedicalCase, VisualizationArtifact, DataSource, SourceRelease, KnowledgeEntity, EvidenceRelation, EntityIdentifier
    from apps.core.services.visualization import build_chart_payload, VisualizationInputError
    from audit_knowledge_queries import IMPORT, norm
    assert urlparse(settings.R_VIZ_BASE_URL).hostname == '127.0.0.1' and settings.R_VIZ_API_TOKEN, 'Existing local R only.'
    def row_hashes(model):
        return {str(row['id']): digest(json.loads(json.dumps(row, cls=DjangoJSONEncoder))) for row in model.objects.order_by('pk').values()}
    def catalogue():
        checksum = hashlib.sha256();count = 0
        for row in KnowledgeEntity.objects.order_by('pk').values().iterator(chunk_size=500):
            checksum.update((json.dumps(row, cls=DjangoJSONEncoder, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode());count += 1
        return {'entities': count, 'entityContentSha256': checksum.hexdigest(), 'relations': EvidenceRelation.objects.count(),
            'lastRelationId': EvidenceRelation.objects.aggregate(value=Max('pk'))['value'], 'identifiers': EntityIdentifier.objects.count()}
    models = (AnalysisTask, ResearchDataset, MedicalCase, VisualizationArtifact, DataSource, SourceRelease)
    if journal.exists():
        if not args.resume:
            raise ValueError('Inspect the journal, then explicitly --resume.')
        state = json.loads(journal.read_text())
    else:
        state = {'before': {model._meta.label: row_hashes(model) for model in models}, 'catalogueBefore': catalogue(), 'tasks': {}, 'renders': {}}
    def save_state():
        temporary = journal.with_suffix('.partial');temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2));temporary.chmod(0o600);temporary.replace(journal)
    save_state()
    accounts = json.loads((VAR / 'accounts.json').read_text())
    owner = LocalClient(accounts['a'], base_url='http://127.0.0.1:5174', csrf_cookie_name='tcm_pg_csrf')
    other = LocalClient(accounts['b'], base_url='http://127.0.0.1:5174', csrf_cookie_name='tcm_pg_csrf')
    imported = json.loads((IMPORT / 'apply-state.json').read_text())
    providers = {row['sourceId']: row['provider'] for row in imported['sources']}
    releases = {pk: providers[source] for pk, source in SourceRelease.objects.filter(source_id__in=providers).values_list('pk', 'source_id')}
    def evidence_key(row):
        return releases[int(row['sourceReleaseId'])], int(row['sourceRecordId'].split(':')[1]), row['relationType']
    report = {'tasks': [], 'renders': [], 'externalCalls': False, 'identityMerged': False}
    for herb in ['牛角尖粉', '石榴皮、白茅根']:
        expected = next(case for case in audit['cases'] if case['herb'] == herb)
        if herb not in state['tasks']:
            _, queued = owner.request('/api/v1/analysis/network-pharmacology/', method='POST', expected=202,
                data={'herb': herb, 'disease': expected['disease'], 'complete': True})
            state['tasks'][herb] = queued['id'];save_state()
        task = wait_task(owner, state['tasks'][herb]);base = f'/api/v1/research/analysis-tasks/{task["id"]}'
        result = task['result'];manifest = result['snapshot'];assert manifest['complete']
        assert {key: result['summary'][key] for key in expected['summary']} == expected['summary']
        assert result['charts'] == expected['charts']
        graph = result['network'];ids = {node['id'] for node in graph['nodes']}
        assert graph['projectionVersion'] == 'endpoint-safe-1'
        assert len(ids) == expected['graph']['nodes'] and len(graph['links']) == expected['graph']['links']
        assert all(edge['source'] in ids and edge['target'] in ids for edge in graph['links'])
        _, data = owner.request(base + '/snapshot-export/?file_format=jsonl')
        lines = [json.loads(line) for line in data.decode().splitlines()]
        header = lines[0];claimed = header['snapshot'].pop('sha256')
        assert claimed == manifest['sha256'] == digest({'parameters': header['parameters'], 'result': header['result'], 'manifest': header['snapshot']})
        tables = {}
        for line in lines[1:]:
            tables.setdefault(line['table'], []).append(line['payload'])
        for table, info in manifest['tables'].items():
            rows = tables.get(table, [])
            assert len(rows) == info['count']
            assert hashlib.sha256(''.join(canonical(row) + '\n' for row in rows).encode()).hexdigest() == info['sha256']
        assert len(tables['evidenceRecords']) == expected['evidenceCount']
        assert key_digest({evidence_key(row) for row in tables['evidenceRecords']}) == expected['evidenceKeySha256']
        for table, count in expected['rawCounts'].items():
            rows = tables.get(table, [])
            assert len(rows) == count
            assert key_digest({(releases[row['sourceReleaseId']], int(row['sourceRecordId'].split(':')[1])) for row in rows}) == expected['rawKeySha256'][table]
        entities = {row['id']: row for row in tables['entities']}
        targets = tables.get('targets', [])
        target_keys = {(releases[entities[row['entityId']]['sourceReleaseId']], 'target', entities[row['entityId']].get('sourceEntityId') or norm(row['target'])) for row in targets}
        assert key_digest(target_keys) == expected['targetIdentitySha256']
        for table in ['evidenceRecords', 'herbLinks', 'directDiseaseHerbLinks', 'targets', 'targetSources']:
            _, csv_bytes = owner.request(base + f'/snapshot-export/?file_format=csv&table={table}')
            csv_rows = list(csv.DictReader(io.StringIO(csv_bytes.decode('utf-8-sig'))))
            assert len(csv_rows) == manifest['tables'][table]['count']
            if table == 'evidenceRecords':
                assert key_digest({evidence_key(row) for row in csv_rows}) == expected['evidenceKeySha256']
        for table in ['evidenceRecords', 'herbLinks']:
            total = manifest['tables'][table]['count']
            for page in {1, (total + 19) // 20}:
                _, response = owner.request(base + f'/snapshot-rows/?table={table}&page={page}&page_size=20')
                assert response['count'] == total and response['snapshotSha256'] == claimed
        _, restored = owner.request(base + '/')
        assert restored['result'] == result and restored['input_parameters'] == task['input_parameters']
        for path in [base + '/', base + '/snapshot-export/', base + '/snapshot-rows/']:
            other.request(path, expected=404)
        parent = AnalysisTask.objects.get(pk=task['id'])
        for key in ['components', 'pathways']:
            try:
                build_chart_payload(parent, key)
            except VisualizationInputError:
                pass
            else:
                raise AssertionError('Do not manufacture candidate component/pathway charts for this source sample.')
        report['tasks'].append({'id': task['id'], 'herb': herb, 'summary': expected['summary'],
            'snapshotSha256': claimed, 'tableCounts': {key: info['count'] for key, info in manifest['tables'].items()},
            'allTableHashesMatch': True, 'originalRowKeysMatch': True, 'graphHasNoDanglingLinks': True,
            'csvAndPaginationMatch': True, 'getRecoveryUnchanged': True, 'otherOwnerDenied': True})
        if herb == '牛角尖粉':
            for key in ['overlap', 'evidence_network']:
                payload = build_chart_payload(parent, key)
                if key == 'overlap':
                    assert payload['data'] == [{'label': row['name'], 'value': row['value']} for row in expected['charts']['overlap']]
                else:
                    assert '原任务网络已裁剪' in payload['subtitle']
                    shown = {node['id'] for node in payload['data']}
                    assert all(edge['source'] in shown and edge['target'] in shown for edge in payload['edges'])
                if key not in state['renders']:
                    _, queued = owner.request(base + '/visualizations/', method='POST', expected=202, data={'chartKey': key})
                    state['renders'][key] = queued['id'];save_state()
                rendered = wait_task(owner, state['renders'][key])
                assert rendered['parent_task'] == parent.pk and rendered['result']['inputSha256'] == payload['inputSha256']
                artifacts = rendered['result']['artifacts'];assert {row['format'] for row in artifacts} == {'svg', 'pdf', 'png', 'html'}
                for artifact in artifacts:
                    _, content = owner.request(artifact['downloadUrl'])
                    assert hashlib.sha256(content).hexdigest() == artifact['sha256']
                    other.request(artifact['downloadUrl'], expected=404)
                _, reused = owner.request(base + '/visualizations/', method='POST', data={'chartKey': key})
                assert reused['id'] == rendered['id']
                png = VisualizationArtifact.objects.get(render_task_id=rendered['id'], file_format='png')
                report['renders'].append({'id': rendered['id'], 'parentTask': parent.pk, 'chartKey': key,
                    'inputSha256': payload['inputSha256'], 'pngPath': default_storage.path(png.storage_key),
                    'rendererVersion': rendered['result']['rendererVersion'], 'formats': sorted(row['format'] for row in artifacts),
                    'artifactHashesMatch': True, 'reuseSameTask': True, 'otherOwnerDenied': True})
        print(json.dumps(report['tasks'][-1], ensure_ascii=False), flush=True)
    for model in models:
        after = row_hashes(model)
        assert all(after.get(pk) == value for pk, value in state['before'][model._meta.label].items()), model._meta.label
    assert catalogue() == state['catalogueBefore']
    report.update(passed=True, previousTasks=len(state['before']['core.AnalysisTask']), previousResearchUnchanged=True, catalogueUnchanged=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2));output.chmod(0o600)
    state['complete'] = True;save_state()
    print(json.dumps({'passed': True, 'taskIds': state['tasks'], 'renderIds': state['renders'], 'oldRecordsUnchanged': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
