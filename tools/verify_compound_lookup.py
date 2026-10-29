"""Verify real compound lookup keys without rewriting catalogue identity.

Uses localhost only. Retains one complete C0671 source query and a private
journal; no comma-derived alias, chemical merge, source sync or external call.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys

from postgres_acceptance import APP, VAR, environment
from smoke_local_workspace import LocalClient, wait_task

ROOT = Path(__file__).resolve().parents[1]
JOB = ROOT / 'python_app/var/compound-lookup-2026-10-21'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__);parser.add_argument('--resume', action='store_true');args = parser.parse_args()
    output = JOB / 'http-verified.json';journal = JOB / 'http-state.json'
    if output.exists():
        raise ValueError('Completed proof exists; do not create duplicate research tasks.')
    environment();sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.conf import settings
    from django.core.serializers.json import DjangoJSONEncoder
    from django.db.models import Max
    from apps.core.models import KnowledgeEntity, EntityIdentifier, EvidenceRelation, AnalysisTask, ResearchDataset, MedicalCase, VisualizationArtifact, DataSource, SourceRelease
    from apps.core.services.component_names import ALIAS_DATA
    def row_hashes(model):
        return {str(row['id']): digest(json.loads(json.dumps(row, cls=DjangoJSONEncoder))) for row in model.objects.order_by('pk').values()}
    def catalogue():
        checksum = hashlib.sha256();count = 0
        for row in KnowledgeEntity.objects.order_by('pk').values().iterator(chunk_size=500):
            checksum.update((json.dumps(row, cls=DjangoJSONEncoder, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode());count += 1
        return {'entities': count, 'entityContentSha256': checksum.hexdigest(), 'relations': EvidenceRelation.objects.count(),
                'lastRelationId': EvidenceRelation.objects.aggregate(value=Max('pk'))['value'], 'registeredIdentifiers': EntityIdentifier.objects.count()}
    models = (AnalysisTask, ResearchDataset, MedicalCase, VisualizationArtifact, DataSource, SourceRelease)
    if journal.exists():
        if not args.resume:
            raise ValueError('Inspect the journal, then explicitly --resume.')
        state = json.loads(journal.read_text())
    else:
        state = {'before': {model._meta.label: row_hashes(model) for model in models}, 'catalogueBefore': catalogue()}
    def save_state():
        temporary = journal.with_suffix('.partial');temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2));temporary.chmod(0o600);temporary.replace(journal)
    save_state()
    accounts = json.loads((VAR / 'accounts.json').read_text())
    client = LocalClient(accounts['a'], base_url='http://127.0.0.1:5174', csrf_cookie_name='tcm_pg_csrf')
    other = LocalClient(accounts['b'], base_url='http://127.0.0.1:5174', csrf_cookie_name='tcm_pg_csrf')
    source = DataSource.objects.get(slug=settings.COMPOUND_SOURCE_ALIASES['HIT'][0], enabled=True)
    compound = KnowledgeEntity.objects.get(entity_type='compound', source_release__source=source, is_active=True, metadata__sourceEntityId='C0671')
    sample = json.loads((ROOT / 'python_app/var/herb-business-2026-10-21/original-query-samples.json').read_text())
    original_rows = [row for row in sample['rows'] if row['provider'] == 'hit' and row['raw'].get('Compound Id') == 'C0671' and row['accepted']]
    assert len(original_rows) == 9 and {row['compound'] for row in original_rows} == {compound.label}
    expected = {(row['row'], kind) for row in original_rows for kind in ('contains', 'targets')}
    def search(query):
        _, response = client.request('/api/v1/catalog/herb-evidence/batch/', method='POST', data={'queryType': 'compound', 'queries': [query]})
        item = response['results'][0]
        assert item['resolution']['identityMerged'] is False and item['resolution']['authorityIdentityVerified'] is False
        return response, item
    report = {'queries': [], 'externalCalls': False, 'commaDerivedAliasesRegistered': False, 'identityMerged': False}
    for query in ['HIT:C0671', source.slug + ':C0671', f'entity:{compound.pk}', compound.stable_id, 'pubchem:167691', compound.label]:
        response, item = search(query)
        assert {row['id'] for row in item['matches']} == {compound.pk} and not item['truncated']
        actual = {(row['sourceRowId'], row['relationType']) for row in item['relations']}
        assert actual == expected and len(item['relations']) == len(expected)
        assert all(row['sourceReleaseId'] == compound.source_release_id for row in item['relations'])
        original_by_row = {row['row']: row for row in original_rows}
        for row in item['relations']:
            raw = original_by_row[row['sourceRowId']]
            assert row['sourceOrigin'] == {'workbookSha256': raw['workbookSha256'], 'sheet': raw['sheet'], 'sourceRow': raw['row']}
        report['queries'].append({'query': query, 'entityIds': [compound.pk], 'sourceRows': len(original_rows), 'relations': len(item['relations']), 'resolution': item['resolution']})
    for query in ['Peiminine', 'Simperialine', 'Peiminine, Simperialine', 'UnknownCompoundA,UnknownCompoundB']:
        _, item = search(query)
        assert compound.pk not in {row['id'] for row in item['matches']}
        report['queries'].append({'query': query, 'entityIds': [row['id'] for row in item['matches']], 'unprovenC0671AliasNotCreated': True, 'resolution': item['resolution']})
    alias_ids = None
    for query in ['槲皮素', 'Quercetin', 'Quercetinum']:
        _, item = search(query)
        ids = [row['id'] for row in item['matches']]
        assert ids and (alias_ids is None or ids == alias_ids)
        alias_ids = ids
        assert item['resolution']['strategy'] == 'explicit_main_alias'
        assert item['resolution']['aliasSourceCommit'] == ALIAS_DATA['sourceCommit']
        assert len(ids) == len(set(ids))
        report['queries'].append({'query': query, 'entityIds': ids, 'truncated': item['truncated'], 'resolution': item['resolution']})
    preview_response, preview = search('HIT:C0671')
    if 'taskId' not in state:
        _, queued = client.request('/api/v1/catalog/herb-evidence/analyses/', method='POST', expected=202,
            data={'queryType': 'compound', 'queries': ['HIT:C0671'], 'expectedResultSha256': preview_response['resultSha256'], 'complete': True})
        state['taskId'] = queued['id'];save_state()
    task = wait_task(client, state['taskId']);base = f'/api/v1/research/analysis-tasks/{task["id"]}'
    _, exported = client.request(base + '/snapshot-export/?file_format=jsonl')
    lines = [json.loads(line) for line in exported.decode().splitlines()]
    header = lines[0];claimed = header['snapshot'].pop('sha256')
    assert claimed == digest({'parameters': header['parameters'], 'result': header['result'], 'manifest': header['snapshot']})
    tables = {}
    for line in lines[1:]:
        tables.setdefault(line['table'], []).append(line['payload'])
    assert tables['queries'][0]['resolution'] == preview['resolution']
    assert {(row['sourceRowId'], row['relationType']) for row in tables['evidenceRecords']} == expected
    for table, info in header['snapshot']['tables'].items():
        assert len(tables[table]) == info['count']
        assert hashlib.sha256(''.join(canonical(row) + '\n' for row in tables[table]).encode()).hexdigest() == info['sha256']
    _, csv_bytes = client.request(base + '/snapshot-export/?file_format=csv&table=queries')
    csv_rows = list(csv.DictReader(io.StringIO(csv_bytes.decode('utf-8-sig'))))
    assert len(csv_rows) == 1 and json.loads(csv_rows[0]['resolution']) == preview['resolution']
    other.request(base + '/', expected=404);other.request(base + '/snapshot-export/', expected=404)
    for model in models:
        after = row_hashes(model)
        assert all(after.get(pk) == value for pk, value in state['before'][model._meta.label].items()), model._meta.label
    assert catalogue() == state['catalogueBefore']
    report.update(passed=True, retainedTaskId=task['id'], evidenceRows=len(tables['evidenceRecords']), snapshotSha256=claimed,
        frozenLookupBasisVerified=True, crossOwnerDenied=True, catalogueUnchanged=True, oldResearchUnchanged=True,
        previousTasks=len(state['before']['core.AnalysisTask']))
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2));output.chmod(0o600)
    state['complete'] = True;save_state()
    print(json.dumps({key: value for key, value in report.items() if key != 'queries'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
