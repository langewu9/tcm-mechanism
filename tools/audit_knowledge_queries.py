"""Reconcile selected full-workbook rows with the actual local catalogue.

extract runs with bundled Python/openpyxl/pandas; compare uses the Django venv.
Workbooks, catalogue and existing research are read-only. No provider/model calls.
The derived import files select samples only; expected rows come from originals.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
JOB = ROOT / 'python_app/var/herb-business-2026-10-21'
IMPORT = ROOT / 'python_app/var/knowledge-import-2026-10-21'
REFERENCE = '078d374852d82ad398e98ff8e97d11f7eb2e3a62'


def clean(value):
    return '' if value is None else str(value).strip()


def norm(value):
    return re.sub(r'\s+', ' ', clean(value).casefold())


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    if path.exists() or not path.resolve().is_relative_to(JOB.resolve()):
        raise ValueError('Choose a new private report; do not replace evidence.')
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')))
    path.chmod(0o600)


def extract(args):
    import openpyxl
    import pandas as pd
    sys.path.insert(0, str(ROOT))
    from backend import data_service as main
    frozen = subprocess.check_output(['git', 'show', f'{REFERENCE}:backend/data_service.py'], cwd=ROOT)
    assert frozen == (ROOT / 'backend/data_service.py').read_bytes()
    selection = json.loads((JOB / 'selection.json').read_text())
    cases = {}
    for source in selection:
        for pick in source['picks']:
            key = (pick['kind'], pick['query'])
            case = cases.setdefault(key, {'queryType': key[0], 'query': key[1], 'selection': []})
            case['selection'].append({'provider': source['provider'], 'stratum': pick['stratum'], 'sourceRows': pick['sourceRows']})
    for kind, query in [('herb', '石榴皮'), ('herb', '当归'), ('herb', '当归干浸膏'),
                        ('compound', 'cinnamic acid'), ('herb', 'NO_LOCAL_MATCH_20261021'),
                        ('compound', 'NO_LOCAL_MATCH_20261021')]:
        cases.setdefault((kind, query), {'queryType': kind, 'query': query, 'selection': []})
    queries = {kind: {case['query'] for case in cases.values() if case['queryType'] == kind} for kind in ('herb', 'compound')}
    keys = {kind: {norm(query) for query in values} for kind, values in queries.items()}
    manifest = json.loads((IMPORT / 'prepared.json').read_text())
    report = {'referenceCommit': REFERENCE, 'referenceSha256': hashlib.sha256(frozen).hexdigest(),
              'cases': list(cases.values()), 'sources': [], 'rows': [], 'diseaseRows': [], 'externalCalls': False}
    frames, cached = {}, []
    disease_terms = {'pulmonary fibrosis', 'idiopathic pulmonary fibrosis', 'interstitial lung disease'}
    for entry in manifest['sources']:
        provider = entry['provider']
        quarantine = {json.loads(line)['row'] for line in (IMPORT / entry['quarantineFile']).read_text().splitlines()}
        retained = []
        for workbook in entry['workbooks']:
            path = IMPORT / 'inputs' / workbook['file']
            assert sha(path) == workbook['sha256']
            book = openpyxl.load_workbook(path, read_only=True, data_only=False)
            sheet = book.active
            headers = [clean(value) for value in next(sheet.iter_rows(values_only=True))]
            positions = {key: headers.index(column) for key, column in main.SOURCE_FILES[provider].items()
                         if key in {'herb', 'component', 'target'}} if provider != 'disease' else {}
            read = 0
            for number, cells in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
                if not any(value is not None for value in cells):
                    continue
                read += 1
                if provider == 'disease':
                    disease = clean(cells[headers.index('疾病')])
                    if disease.casefold() not in disease_terms:
                        continue
                    raw = dict(zip(headers, cells))
                    report['diseaseRows'].append({'table': workbook['kind'], 'row': number, 'raw': raw,
                                                 'workbookSha256': workbook['sha256'], 'sheet': sheet.title})
                    continue
                herb, compound, target = [clean(cells[positions[key]]) for key in ('herb', 'component', 'target')]
                exact = norm(herb) in keys['herb'] or norm(compound) in keys['compound']
                fuzzy = any(query.casefold() in herb.casefold() for query in queries['herb']) or any(
                    query.casefold() in compound.casefold() for query in queries['compound'])
                if not (exact or fuzzy):
                    continue
                raw = dict(zip(headers, cells))
                row = {'provider': provider, 'row': number, 'herb': herb, 'compound': compound, 'target': target,
                       'accepted': number not in quarantine, 'raw': raw, 'workbookSha256': workbook['sha256'], 'sheet': sheet.title}
                report['rows'].append(row)
                retained.append(raw)
                cached.append((provider, herb, compound, target))
            book.close()
            assert read == workbook['dataRows'] and sha(path) == workbook['sha256']
            report['sources'].append({'provider': provider, 'file': workbook['file'], 'sha256': workbook['sha256'],
                                      'dataRowsScanned': read, 'originalUnchanged': True})
            print(json.dumps({'provider': provider, 'rowsScanned': read, 'retained': len(retained)}, ensure_ascii=False), flush=True)
        if provider != 'disease':
            frames[provider] = pd.DataFrame(retained, columns=headers)
    split = lambda value: [part.strip() for part in re.split(r'[;,，；/|]', value) if part.strip()]
    with sqlite3.connect(':memory:') as db:
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE herb_component_target(source,herb,component,target)')
        db.executemany('INSERT INTO herb_component_target VALUES(?,?,?,?)', cached)
        for case in report['cases']:
            kind, query = case['queryType'], case['query']
            function = main.search_herb if kind == 'herb' else main.search_component
            fuzzy = [row for row in report['rows'] if query.casefold() in row[kind].casefold()]
            with patch.object(main, '_cache', return_value=None), patch.object(main, 'load_source', side_effect=lambda provider: frames[provider]):
                excel = function(query, limit=300000)
            with patch.object(main, '_cache', return_value=db):
                cache = function(query, limit=300000)
            expected_excel = Counter((row['provider'], row['herb'], row['compound'], tuple(split(row['target'])[:20]))
                                     for row in fuzzy if kind != 'herb' or row['compound'])
            expected_cache = Counter((row['provider'], row['herb'], row['compound'], tuple(split(row['target']))) for row in fuzzy)
            def signatures(result):
                return Counter((row['source'], row['herb'], row['component'], tuple(row['targets'])) for row in result['links'])
            assert signatures(excel) == expected_excel, ('old Excel row projection', query)
            assert signatures(cache) == expected_cache, ('old SQLite row projection', query)
            case['legacy'] = {'fuzzySourceRows': len(fuzzy), 'excel': excel['counts'], 'cache': cache['counts'],
                              'excelTargets': excel['targets'], 'cacheTargets': cache['targets'], 'bothOriginalRowProjectionsMatch': True}
    save(args.output, report)
    print(json.dumps({'cases': len(report['cases']), 'retainedRows': len(report['rows']), 'diseaseRows': len(report['diseaseRows'])}), flush=True)


def compare(args):
    from postgres_acceptance import APP, environment
    environment(); sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.db import connection, transaction
    from apps.core.models import SourceRelease
    from apps.core.services.herb_evidence import batch_herb_component_evidence
    from apps.core.services.network_pharmacology import build_network_pharmacology
    sample = json.loads(args.sample.read_text())
    state = json.loads((IMPORT / 'apply-state.json').read_text())
    source_ids = {item['provider']: item['sourceId'] for item in state['sources']}
    provider_by_id = {value: key for key, value in source_ids.items()}
    rows = [row for row in sample['rows'] if row['accepted']]
    def row_key(row, kind):
        column = {'herb': 'Herb ID', 'compound': 'Compound Id', 'target': 'Target ID'}[kind]
        return (row['provider'], kind, clean(row['raw'][column]) if row['provider'] == 'hit' else norm(row[kind]))
    rows_by_key = {kind: defaultdict(list) for kind in ('herb', 'compound')}
    for row in rows:
        for kind in rows_by_key:
            rows_by_key[kind][norm(row[kind])].append(row)
    report = {'referenceCommit': sample['referenceCommit'], 'cases': [], 'intersections': [], 'issues': [],
              'catalogueTransactionReadOnly': True, 'externalCalls': False, 'originalWorkbooksUnchanged': True}
    for source in sample['sources']:
        assert sha(IMPORT / 'inputs' / source['file']) == source['sha256']
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION READ ONLY')
            cursor.execute("SET LOCAL statement_timeout='60s'")
        def entity_key(entity):
            source_id = entity['sourceReleaseId']
            provider = release_providers[source_id]
            kind = 'target' if entity.get('entityType') in ('gene', 'protein') else entity.get('entityType')
            return (provider, kind, entity.get('sourceEntityId') or norm(entity['label']))
        release_providers = {release: provider_by_id[source] for release, source in
                             SourceRelease.objects.filter(source_id__in=source_ids.values()).values_list('pk', 'source_id')}
        for case in sample['cases']:
            kind, query = case['queryType'], case['query']
            selected = rows_by_key[kind].get(norm(query), [])
            expected = {}
            expected_targets, expected_compounds, expected_herbs = set(), set(), set()
            for row in selected:
                if row['herb'] and row['compound']:
                    expected[(row['provider'], row['row'], 'contains')] = row
                    expected_herbs.add(row_key(row, 'herb'));expected_compounds.add(row_key(row, 'compound'))
                if row['compound'] and row['target']:
                    expected[(row['provider'], row['row'], 'targets')] = row
                    expected_targets.add(row_key(row, 'target'))
            # A herb query cannot use an orphan compound-target row.
            if kind == 'herb':
                expected = {key: row for key, row in expected.items() if row['herb'] and row['compound']}
                expected_targets = {row_key(row, 'target') for key, row in expected.items() if key[2] == 'targets'}
            snapshots = {}
            for mode, limit, matches in [('preview', 1200, 10), ('complete', 50000, 1000)]:
                data = batch_herb_component_evidence(query_type=kind, queries=[query], relation_limit=limit, match_limit=matches)['results'][0]
                entities = {entity['id']: entity_key(entity) for group in ('herbs', 'compounds', 'targets') for entity in data[group]}
                actual = {}
                for record in data['relations']:
                    provider = release_providers[record['sourceReleaseId']]
                    key = (provider, record['sourceRowId'], record['relationType'])
                    actual[key] = record
                    original = expected.get(key)
                    if original is None:
                        report['issues'].append({'query': query, 'mode': mode, 'kind': 'unexpected_source_row', 'record': key})
                        continue
                    origin = {'workbookSha256': original['workbookSha256'], 'sheet': original['sheet'], 'sourceRow': original['row']}
                    if record['sourceOrigin'] != origin:
                        report['issues'].append({'query': query, 'mode': mode, 'kind': 'origin_mismatch', 'record': key})
                    left, right = ('herb', 'compound') if key[2] == 'contains' else ('compound', 'target')
                    if norm(record['subject']) != norm(original[left]) or norm(record['object']) != norm(original[right]):
                        report['issues'].append({'query': query, 'mode': mode, 'kind': 'row_endpoints_differ', 'record': key})
                    if entities.get(record['subjectId']) != row_key(original, left) or entities.get(record['objectId']) != row_key(original, right):
                        report['issues'].append({'query': query, 'mode': mode, 'kind': 'row_endpoint_identities_differ', 'record': key})
                    identity = record.get('sourceIdentity') or {}
                    if original['provider'] == 'hit':
                        if any(identity.get(name) != clean(original['raw'][column]) for name, column in
                               [('herbId', 'Herb ID'), ('compoundId', 'Compound Id'), ('targetId', 'Target ID')]):
                            report['issues'].append({'query': query, 'mode': mode, 'kind': 'source_identity_mismatch', 'record': key})
                    elif identity:
                        report['issues'].append({'query': query, 'mode': mode, 'kind': 'unreviewed_identity_promoted', 'record': key})
                actual_targets = {entity_key(entity) for entity in data['targets']}
                wanted_compounds = expected_compounds if kind == 'herb' else {row_key(row, 'compound') for row in selected if row['compound']}
                wanted_herbs = expected_herbs if kind == 'compound' else {row_key(row, 'herb') for row in selected if row['herb']}
                actual_compounds = {entity_key(entity) for entity in data['compounds']}
                actual_herbs = {entity_key(entity) for entity in data['herbs']}
                # Disease books legitimately contribute a same-name herb entity
                # with no compound edges. It cannot claim a five-source target.
                disease_herbs = {key for key in actual_herbs if kind == 'herb' and key == ('disease', 'herb', norm(query))}
                actual_herbs -= disease_herbs
                if not actual_compounds <= wanted_compounds or not actual_herbs <= wanted_herbs:
                    report['issues'].append({'query': query, 'mode': mode, 'kind': 'unexpected_herb_or_compound_identity'})
                if not actual_targets <= expected_targets:
                    report['issues'].append({'query': query, 'mode': mode, 'kind': 'unexpected_target_identity'})
                exact = (set(actual) == set(expected) and actual_targets == expected_targets
                         and actual_compounds == wanted_compounds and actual_herbs == wanted_herbs)
                if mode == 'complete' and (not exact or data['truncated']):
                    report['issues'].append({'query': query, 'mode': mode, 'kind': 'incomplete_full_query',
                                             'expectedRelations': len(expected), 'actualRelations': len(actual), 'truncated': data['truncated']})
                if not data['truncated'] and not exact:
                    report['issues'].append({'query': query, 'mode': mode, 'kind': 'partial_without_marker'})
                snapshots[mode] = {'sourceRelations': len(actual), 'targets': len(actual_targets),
                                   'herbs': len(actual_herbs) + len(disease_herbs), 'compounds': len(actual_compounds), 'matches': len(data['matches']),
                                   'truncated': data['truncated'], 'completeOriginalSetsMatch': exact}
            report['cases'].append({'queryType': kind, 'query': query, 'selection': case['selection'],
                                    'expectedRows': len(selected), 'expectedRelations': len(expected), 'expectedTargets': len(expected_targets),
                                    'sources': dict(Counter(row['provider'] for row in selected)), 'legacy': case['legacy'], **snapshots})
            print(json.dumps({'queryType': kind, 'query': query, 'complete': snapshots['complete'], 'issues': len(report['issues'])}, ensure_ascii=False), flush=True)
        for herb, disease in [('石榴皮', 'Pulmonary fibrosis'), ('石榴皮', '肺纤维化'), ('白茅根', '肺纤维化')]:
            data = build_network_pharmacology(user=None, herb_query=herb, disease_query=disease, row_limit=50000, persist=False, complete=True)
            herb_rows = [row for row in rows if norm(row['herb']) == norm(herb) and row['compound']]
            disease_names = {disease.casefold()} if disease == 'Pulmonary fibrosis' else {
                '肺纤维化', 'pulmonary fibrosis', 'idiopathic pulmonary fibrosis', 'interstitial lung disease'}
            disease_rows = [row for row in sample['diseaseRows'] if clean(row['raw']['疾病']).casefold() in disease_names]
            disease_targets = {norm(row['raw']['靶点基因']) for row in disease_rows if clean(row['raw']['靶点基因'])
                               and (row['table'] == 'diseaseTarget' or clean(row['raw']['中药']))}
            direct_rows = [row for row in disease_rows if row['table'] == 'diseaseHerbTarget'
                           and norm(row['raw']['中药']) == norm(herb) and clean(row['raw']['靶点基因'])]
            # These original releases have separate, unverified molecular IDs.
            # Name overlap is recorded separately, never used as identity proof.
            expected_summary = {'herbTargetCount': len({row_key(row, 'target') for row in herb_rows if row['target']}),
                'diseaseTargetCount': len(disease_targets), 'strictIntersectionCount': 0,
                'directAssociationTargetCount': len({norm(row['raw']['靶点基因']) for row in direct_rows}),
                'candidateTargetCount': len({norm(row['raw']['靶点基因']) for row in direct_rows}),
                'componentCount': len({row_key(row, 'compound') for row in herb_rows})}
            for key, value in expected_summary.items():
                if data['summary'][key] != value:
                    report['issues'].append({'kind': 'intersection_original_mismatch', 'herb': herb, 'disease': disease,
                                             'metric': key, 'expected': value, 'actual': data['summary'][key]})
            if not data['summary']['matchedDiseases'] or any(data['rawLimits']['inputRelationsTruncated'].values()):
                report['issues'].append({'kind': 'intersection_matching_or_limit', 'herb': herb, 'disease': disease})
            expected_raw = {
                'herbLinks': {(row['provider'], row['row']) for row in herb_rows if row['target']},
                'diseaseTargets': {row['row'] for row in disease_rows if row['table'] == 'diseaseTarget' and clean(row['raw']['靶点基因'])},
                'diseaseHerbLinks': {row['row'] for row in disease_rows if row['table'] == 'diseaseHerbTarget' and clean(row['raw']['中药']) and clean(row['raw']['靶点基因'])},
                'directDiseaseHerbLinks': {row['row'] for row in direct_rows},
            }
            for table, expected_ids in expected_raw.items():
                if table == 'herbLinks':
                    actual_ids = {(release_providers[row['sourceReleaseId']], int(row['sourceRecordId'].split(':')[1])) for row in data['raw'][table]}
                    if any(row['herbSourceReleaseId'] != row['sourceReleaseId'] or row['herbSourceRecordId'].split(':')[1] != row['sourceRecordId'].split(':')[1] for row in data['raw'][table]):
                        report['issues'].append({'kind': 'intersection_herb_source_leakage', 'herb': herb})
                else:
                    actual_ids = {int(row['sourceRecordId'].split(':')[1]) for row in data['raw'][table]}
                if actual_ids != expected_ids or len(data['raw'][table]) != len(expected_ids):
                    report['issues'].append({'kind': 'intersection_source_rows_mismatch', 'table': table, 'herb': herb,
                                             'expected': len(expected_ids), 'actual': len(actual_ids)})
            report['intersections'].append({'herb': herb, 'disease': disease, 'summary': data['summary'],
                                             'expectedSummaryFromOriginalRows': expected_summary,
                                             'unverifiedNameOverlap': len({norm(row['target']) for row in herb_rows if row['target']} & disease_targets),
                                             'inputTruncation': data['rawLimits']['inputRelationsTruncated'],
                                             'rawCounts': {key: len(value) for key, value in data['raw'].items()}})
    report['passed'] = not report['issues']
    save(args.output, report)
    print(json.dumps({'passed': report['passed'], 'cases': len(report['cases']), 'issues': report['issues'], 'intersections': report['intersections']}, ensure_ascii=False), flush=True)
    if not report['passed']:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    one = sub.add_parser('extract');one.add_argument('--output', type=Path, required=True)
    two = sub.add_parser('compare');two.add_argument('sample', type=Path);two.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new report path.')
    extract(args) if args.action == 'extract' else compare(args)


if __name__ == '__main__':
    main()
