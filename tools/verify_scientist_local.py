"""Actual localhost assistant report proof; retains two explicitly named tasks.

Uses previously independently checked original-row expectations. Does not import
catalogues, upload experiments, call models/providers or rewrite old research.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys

from postgres_acceptance import APP, ROOT, VAR, environment
from smoke_local_workspace import LocalClient, wait_task

JOB = ROOT / 'python_app/var/scientist-local-2026-10-22'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def save(name, value):
    path = JOB / name
    temporary = path.with_suffix('.partial')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)); temporary.chmod(0o600)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--resume', action='store_true'); args = parser.parse_args()
    if (JOB / 'http-verified.json').exists():
        raise ValueError('Completed proof exists; do not create duplicate tasks.')
    environment(); sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.apps import apps
    from django.core.serializers.json import DjangoJSONEncoder
    from django.db import connection, transaction
    from django.db.models import Max
    from apps.core.models import EvidenceRelation
    models = ['core.AnalysisTask', 'core.AnalysisSnapshotRow', 'core.ResearchDataset', 'core.ResearchDatasetRow',
              'proteomics.ProteomicsRowResult', 'core.MedicalCase', 'core.VisualizationArtifact',
              'core.DataSource', 'core.SourceRelease', 'core.KnowledgeEntity', 'core.EntityIdentifier']
    def fingerprint(before=None):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            output = {}
            for label in models:
                model = apps.get_model(label)
                upper = before[label]['upper'] if before else model.objects.aggregate(value=Max('pk'))['value'] or 0
                checksum, count = hashlib.sha256(), 0
                for row in model.objects.filter(pk__lte=upper).order_by('pk').values().iterator(chunk_size=500):
                    plain = json.loads(json.dumps(row, cls=DjangoJSONEncoder))
                    checksum.update((canonical(plain) + '\n').encode()); count += 1
                output[label] = {'upper': upper, 'count': count, 'sha256': checksum.hexdigest()}
            output['relations'] = {'count': EvidenceRelation.objects.count(), 'upper': EvidenceRelation.objects.aggregate(value=Max('pk'))['value']}
            return output
    journal = JOB / 'http-state.json'
    if journal.exists():
        if not args.resume: raise ValueError('Existing journal requires explicit --resume.')
        state = json.loads(journal.read_text())
    else:
        state = {'before': fingerprint(), 'tasks': {}}
        save(journal.name, state)
    expected = json.loads((ROOT / 'python_app/var/target-identity-2026-10-22/network-recheck.json').read_text())
    case = next(item for item in expected['cases'] if item['herb'] == '石榴皮、白茅根')
    provider_by_release = {item['sourceReleaseId']: item['provider'] for item in json.loads(
        (ROOT / 'python_app/var/knowledge-import-2026-10-21/apply-state.json').read_text())['sources']}
    accounts = json.loads((VAR / 'accounts.json').read_text())
    clients = [LocalClient(accounts[key], base_url='http://127.0.0.1:5174', csrf_cookie_name='tcm_pg_csrf') for key in ['a', 'b', 'admin']]
    owner, other, admin = clients
    proofs = []
    try:
        for name, disease, formula in [('real-source', '肺纤维化', '石榴皮、白茅根'),
                                       ('empty-source', 'NO_SCIENTIST_DISEASE_20261022', 'NO_SCIENTIST_HERB_20261022')]:
            if name not in state['tasks']:
                _, task = owner.request('/api/v1/research/assistant/', method='POST', expected=202, data={
                    'mode': 'scientist_hypothesis', 'question': f'本地报告验收 {name}：仅核对目录，不代表实验结论',
                    'disease': disease, 'formula': formula, 'focus': '原行一致性与报告边界验证',
                    'useModel': False, 'confirmModelSharing': False})
                state['tasks'][name] = task['id']; save(journal.name, state)
            task = wait_task(owner, state['tasks'][name]); result = task['result']
            assert result['analysisKind'] == 'scientist_hypothesis' and not result['externalCalls'] and result['model'] is None
            assert not task['input_parameters']['useModel'] and not task['input_parameters']['modelConsentRecorded']
            base = f'/api/v1/research/analysis-tasks/{task["id"]}'
            _, body = owner.request(base + '/snapshot-export/')
            (JOB / f'task-{task["id"]}.jsonl').write_bytes(body)
            (JOB / f'task-{task["id"]}.jsonl').chmod(0o600)
            lines = [json.loads(line) for line in body.decode().splitlines()]
            manifest = lines[0]; checksum = manifest['snapshot'].pop('sha256')
            assert checksum == digest({'parameters': manifest['parameters'], 'result': manifest['result'], 'manifest': manifest['snapshot']})
            for table, info in result['snapshot']['tables'].items():
                records = [row['payload'] for row in lines[1:] if row['table'] == table]
                assert len(records) == info['count']
                assert hashlib.sha256(''.join(canonical(row) + '\n' for row in records).encode()).hexdigest() == info['sha256']
            evidence = [row['payload'] for row in lines[1:] if row['table'] == 'evidenceRecords']
            if name == 'real-source':
                keys = {(provider_by_release[row['sourceReleaseId']], row['sourceRowId'], row['relationType']) for row in evidence}
                assert len(evidence) == case['evidenceCount'] and digest(sorted(keys)) == case['evidenceKeySha256']
                for metric, network_metric in [('disease_target_count', 'diseaseTargetCount'), ('formula_target_count', 'herbTargetCount'),
                        ('intersection_count', 'strictIntersectionCount'), ('direct_association_count', 'directAssociationTargetCount'), ('component_count', 'componentCount')]:
                    assert result['results'][metric] == case['summary'][network_metric]
                assert result['results']['intersection_count'] == 0 and not result['results']['top_intersection_targets']
            else:
                assert not evidence and not result['references'] and result['results']['formula_target_count'] == 0
            _, csv_bytes = owner.request(base + '/snapshot-export/?table=reportSections&file_format=csv')
            (JOB / f'task-{task["id"]}-report.csv').write_bytes(csv_bytes)
            (JOB / f'task-{task["id"]}-report.csv').chmod(0o600)
            rows = list(csv.DictReader(io.StringIO(csv_bytes.decode('utf-8-sig')))); assert len(rows) == 12
            _, restored = owner.request(base + '/'); assert digest(restored['result']) == digest(result)
            for suffix in ['/', '/snapshot-export/', '/snapshot-rows/?table=reportSections']:
                other.request(base + suffix, expected=404)
            _, admin_read = admin.request(base + '/'); assert admin_read['owner_id'] == accounts['a']['id']
            proofs.append({'name': name, 'taskId': task['id'], 'counts': result['results'],
                           'evidenceRows': len(evidence), 'sourceVersions': len(result['references']),
                           'snapshotHashesMatch': True, 'otherOwnerDenied': True, 'restorationUnchanged': True})
            print(json.dumps(proofs[-1], ensure_ascii=False), flush=True)
        _, monitor = admin.request('/api/v1/admin/integrations/test/', method='POST', data={'target': 'scientist'})
        assert monitor['result']['ok'] and not monitor['result']['data']['externalCalls'] and not monitor['result']['data']['taskCreated']
        after = fingerprint(state['before']); assert after == state['before'], 'Existing research or catalogue changed.'
        output = {'passed': True, 'tasks': proofs, 'previousRecordsUnchanged': True,
                  'newTasks': len(state['tasks']), 'externalCalls': False, 'measurementsUploaded': False,
                  'monitorReadOnly': True, 'previousTaskCount': state['before']['core.AnalysisTask']['count']}
        save('http-verified.json', output)
    finally:
        for client in clients:
            client.request('/api/v1/auth/session/', method='DELETE', expected=204)


if __name__ == '__main__':
    main()
