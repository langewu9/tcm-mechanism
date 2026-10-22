"""Reconcile imported targets with original workbooks, without identity promotion.

extract uses bundled Python/openpyxl to scan originals. compare uses the isolated
local PostgreSQL profile in a repeatable-read, read-only transaction. Neither
action edits workbooks, applies mappings, calls providers or creates research.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
IMPORT = ROOT / 'python_app/var/knowledge-import-2026-10-21'
JOB = ROOT / 'python_app/var/target-identity-2026-10-22'
TARGET_COLUMNS = {'disease': '靶点基因', 'tcmsp': '靶点基因', 'hit': 'Symbol',
                  'batman': 'Gene Name', 'tcmip': '靶标', 'herb': 'Gene name'}
ASSERTION_COLUMNS = {'hit': {'source_target': 'Target ID', 'uniprot': 'Uniprot'},
                     'batman': {'reported_gene_id': 'Gene ID'}}
SYMBOL = re.compile(r'^[A-Z][A-Z0-9_.-]{0,63}$')


def clean(value):
    return '' if value is None else str(value).strip()


def canonical(value):
    return re.sub(r'\s+', ' ', clean(value).casefold())


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(name, value):
    JOB.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = JOB / name
    with path.open('x') as stream:
        path.chmod(0o600)
        json.dump(value, stream, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return path


def extract():
    import openpyxl
    if (JOB / 'original-targets.json').exists():
        raise ValueError('Original extraction already exists; do not replace evidence.')
    manifest = json.loads((IMPORT / 'prepared.json').read_text())
    report = {'createdAt': datetime.now(timezone.utc).isoformat(), 'sources': [],
              'externalCalls': False, 'sourceEdits': False, 'biologicalIdentityVerified': False}
    for source in manifest['sources']:
        provider = source['provider']
        quarantined = defaultdict(set)
        for line in (IMPORT / source['quarantineFile']).read_text().splitlines():
            row = json.loads(line)
            quarantined[row['file']].add(row['row'])
        targets, books = {}, []
        for entry in source['workbooks']:
            path = IMPORT / 'inputs' / entry['file']
            assert sha(path) == entry['sha256']
            book = openpyxl.load_workbook(path, read_only=True, data_only=False)
            try:
                sheet = book[entry['sheet']]
                headers = [clean(value) for value in next(sheet.iter_rows(values_only=True))]
                assert headers == entry['headers'] and len(headers) == len(set(headers))
                column = TARGET_COLUMNS[provider]
                position = headers.index(column)
                counts = Counter()
                for number, cells in enumerate(sheet.iter_rows(min_row=2), 2):
                    if not any(cell.value is not None for cell in cells):
                        continue
                    counts['nonemptyRows'] += 1
                    if number in quarantined[entry['file']]:
                        counts['quarantinedUnchanged'] += 1
                        continue
                    assert not any(cell.data_type == 'f' for cell in cells), (entry['file'], number, 'formula')
                    raw = dict(zip(headers, [cell.value for cell in cells]))
                    label = clean(raw[column])
                    if not label:
                        counts['missingTarget'] += 1
                        continue
                    counts['rowsWithTarget'] += 1
                    key = clean(raw['Target ID']) if provider == 'hit' else canonical(label)
                    assert key and len(label) <= 300
                    target = targets.setdefault(key, {'key': key, 'labels': set(), 'rowCount': 0,
                                                     'assertions': defaultdict(set), 'example': None})
                    target['labels'].add(label)
                    target['rowCount'] += 1
                    assertions = {namespace: clean(raw[field]) for namespace, field in ASSERTION_COLUMNS.get(provider, {}).items()}
                    for namespace, value in assertions.items():
                        target['assertions'][namespace].add(value)
                    if target['example'] is None:
                        fields = {column: raw[column], **{field: raw[field] for field in ASSERTION_COLUMNS.get(provider, {}).values()}}
                        if provider == 'hit':
                            fields['Protein Name'] = raw['Protein Name']
                        target['example'] = {'file': entry['file'], 'sheet': sheet.title,
                                             'sourceRow': number, 'workbookSha256': entry['sha256'], 'fields': fields}
                    if counts['nonemptyRows'] % 100000 == 0:
                        print(encoded({'provider': provider, 'file': entry['file'], 'rowsRead': counts['nonemptyRows']}), flush=True)
                assert counts['nonemptyRows'] == entry['dataRows']
                assert counts['quarantinedUnchanged'] == len(quarantined[entry['file']])
                books.append({'file': entry['file'], 'sha256': entry['sha256'], 'sheet': entry['sheet'],
                              'headers': headers, 'targetColumn': column, 'counts': dict(counts),
                              'explicitSpeciesColumnPresent': any(re.search(
                                  r'organism|species|taxon|物种', header, re.I) for header in headers)})
            finally:
                book.close()
            assert sha(path) == entry['sha256']
        rows = []
        for target in targets.values():
            rows.append({**target, 'labels': sorted(target['labels']),
                         'assertions': {key: sorted(values) for key, values in target['assertions'].items()}})
        report['sources'].append({'provider': provider, 'workbooks': books, 'targets': rows,
                                  'targetKeyMode': 'source_id_case_sensitive' if provider == 'hit' else 'existing_normalized_name_key'})
        print(encoded({'provider': provider, 'targetKeys': len(rows), 'workbooksUnchanged': True}), flush=True)
    report['complete'] = True
    save('original-targets.json', report)


def compare():
    from postgres_acceptance import APP, environment
    environment()
    sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.core.serializers.json import DjangoJSONEncoder
    from django.db import connection, transaction
    from apps.core.models import (AnalysisTask, ResearchDataset, ResearchDatasetRow, MedicalCase,
                                  VisualizationArtifact, DataSource, SourceRelease, KnowledgeEntity,
                                  EntityIdentifier, EvidenceRelation)
    from apps.proteomics.models import ProteomicsRowResult
    from apps.sources.connectors.uniprot import _ACCESSION
    original = json.loads((JOB / 'original-targets.json').read_text())
    applied = json.loads((IMPORT / 'apply-state.json').read_text())
    assert original['complete'] and applied['complete']
    assert connection.vendor == 'postgresql' and connection.settings_dict['NAME'] == 'tcm_acceptance'
    report = {'createdAt': datetime.now(timezone.utc).isoformat(), 'sources': [], 'issues': [],
              'databaseReadOnly': True, 'externalCalls': False, 'biologicalIdentityVerified': False}
    details, names, accessions = [], defaultdict(list), defaultdict(list)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        for source_original in original['sources']:
            provider = source_original['provider']
            applied_source = next(row for row in applied['sources'] if row['provider'] == provider)
            source = DataSource.objects.get(pk=applied_source['sourceId'])
            rows = list(KnowledgeEntity.objects.filter(is_active=True, source_release__source=source,
                        entity_type__in=['protein', 'gene']).order_by('pk').values())
            by_stable = {row['stable_id']: row for row in rows}
            expected_ids, source_rows = set(), []
            for target in source_original['targets']:
                suffix = hashlib.sha256(target['key'].encode()).hexdigest()
                stable_id = f'sqlite:{source.slug}:target:' + ('id:' if provider == 'hit' else '') + suffix
                expected_ids.add(stable_id)
                entity = by_stable.get(stable_id)
                if entity is None:
                    report['issues'].append({'provider': provider, 'kind': 'missing_target', 'key': target['key']})
                    continue
                metadata = entity['metadata']
                matching = canonical(entity['label']) == canonical(target['labels'][0]) and all(
                    canonical(label) == canonical(entity['label']) for label in target['labels'])
                if provider == 'hit':
                    matching = matching and metadata.get('sourceEntityId') == target['key']
                    expected_references = [{'namespace': 'uniprot', 'identifier': value, 'status': 'source_reported_unverified'}
                                           for value in target['assertions']['uniprot'] if value]
                    matching = matching and metadata.get('sourceReferences') == expected_references
                    matching = matching and metadata.get('symbol') in target['labels']
                expected_status = 'unverified_symbol' if provider == 'hit' or SYMBOL.fullmatch(entity['label']) else 'name_only'
                matching = matching and metadata.get('identifierStatus') == expected_status and not entity['organism']
                if not matching:
                    report['issues'].append({'provider': provider, 'kind': 'source_assertion_mismatch', 'entityId': entity['id']})
                item = {'provider': provider, 'entityId': entity['id'], 'stableId': stable_id, 'label': entity['label'],
                        'organism': entity['organism'], 'identifierStatus': metadata.get('identifierStatus'),
                        'sourceEntityId': metadata.get('sourceEntityId'), 'assertions': target['assertions'],
                        'originalLabels': target['labels'], 'sourceRowCount': target['rowCount'],
                        'example': target['example'], 'allOriginalAssertionsMatch': matching}
                details.append(item); source_rows.append(item); names[canonical(entity['label'])].append(item)
                for accession in target['assertions'].get('uniprot', []):
                    if accession:
                        accessions[accession].append(item)
            if set(by_stable) != expected_ids:
                report['issues'].append({'provider': provider, 'kind': 'target_key_set_mismatch',
                                         'unexpectedStableIds': sorted(set(by_stable) - expected_ids)})
            identifier_count = EntityIdentifier.objects.filter(entity_id__in=[row['id'] for row in rows]).count()
            if identifier_count:
                report['issues'].append({'provider': provider, 'kind': 'unexpected_identity_promotion', 'count': identifier_count})
            report['sources'].append({'provider': provider, 'sourceId': source.pk,
                'sourceReleaseId': applied_source['sourceReleaseId'], 'targets': len(rows),
                'unknownSpecies': sum(not row['organism'] for row in rows),
                'identifierStatuses': dict(Counter(item['identifierStatus'] for item in source_rows)),
                'registeredIdentifiers': identifier_count,
                'sourceIdCount': sum(bool(item['sourceEntityId']) for item in source_rows),
                'originalNameVariantGroups': sum(len(item['originalLabels']) > 1 for item in source_rows),
                'multipleReportedIdsWithinNameKey': sum(len([v for v in item['assertions'].get('reported_gene_id', []) if v]) > 1 for item in source_rows)})
        def short(item):
            return {key: item[key] for key in ('provider', 'entityId', 'sourceEntityId', 'label', 'assertions', 'example')}
        same_names = [{'nameKey': key, 'targets': [short(item) for item in items]}
                      for key, items in sorted(names.items()) if len(items) > 1]
        accession_groups = [{'sourceReportedAccession': key, 'syntaxValidOnly': bool(_ACCESSION.fullmatch(key)),
                             'targets': [short(item) for item in items]}
                            for key, items in sorted(accessions.items())]
        report['nameCandidateGroups'] = len(same_names)
        report['crossSourceNameCandidateGroups'] = sum(len({row['provider'] for row in group['targets']}) > 1 for group in same_names)
        report['sameNameMultipleHitIds'] = sum(sum(row['provider'] == 'hit' for row in group['targets']) > 1 for group in same_names)
        report['reportedAccessions'] = len(accession_groups)
        report['accessionSyntaxNotAccepted'] = sum(not group['syntaxValidOnly'] for group in accession_groups)
        report['reportedAccessionMultipleHitIds'] = sum(len(group['targets']) > 1 for group in accession_groups)
        # Stored research is hashed independently of the identity diagnostics.
        guards = {}
        for model in (AnalysisTask, ResearchDataset, ResearchDatasetRow, ProteomicsRowResult,
                      MedicalCase, VisualizationArtifact, DataSource, SourceRelease, KnowledgeEntity, EntityIdentifier):
            checksum, count = hashlib.sha256(), 0
            for row in model.objects.order_by('pk').values().iterator(chunk_size=500):
                plain = json.loads(json.dumps(row, cls=DjangoJSONEncoder))
                checksum.update((encoded(plain) + '\n').encode()); count += 1
            guards[model._meta.label] = {'count': count, 'sha256': checksum.hexdigest()}
        report['readOnlyState'] = guards
        report['relationCount'] = EvidenceRelation.objects.count()
    report['passed'] = not report['issues']
    save('target-details.json', details)
    save('name-candidates.json', same_names)
    save('source-accession-claims.json', accession_groups)
    save('comparison.json', report)
    print(encoded(report), flush=True)
    if report['issues']:
        raise SystemExit(1)


def verify():
    global JOB
    from postgres_acceptance import APP, environment
    environment()
    sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.core.serializers.json import DjangoJSONEncoder
    from django.db import connection, transaction
    from django.apps import apps
    from apps.core.models import AnalysisTask, ResearchDataset
    from apps.proteomics.services import _parse_rows, _build_result, resolve_mapping
    baseline = json.loads((JOB / 'comparison.json').read_text())
    assert baseline['passed']
    details = json.loads((JOB / 'target-details.json').read_text())
    plans = []
    for provider in TARGET_COLUMNS:
        target = next(item for item in details if item['provider'] == provider)
        plans.append({'input': target['stableId'], 'entityId': target['entityId'],
                      'expectedStatus': 'unverified' if target['identifierStatus'] == 'unverified_symbol' else 'unmapped'})
    composite = next(item for item in details if item['provider'] == 'hit' and item['label'] == 'HSPA1A;HSPA1B')
    plans.append({'input': composite['stableId'], 'entityId': composite['entityId'], 'expectedStatus': 'unverified'})
    for label in ['ALPL', 'Alpl', 'BCL2L1', 'EGFR', 'TRPV4', 'SMN1; SMN2']:
        plans.append({'input': label, 'entityId': None, 'expectedStatus': 'ambiguous'})
    for label in ['P28482', 'T79WXA']:
        plans.append({'input': label, 'entityId': None, 'expectedStatus': 'unverified'})
    plans.append({'input': '249', 'entityId': None, 'expectedStatus': 'unmapped'})
    comma_label = next(item['label'] for item in details if item['provider'] == 'tcmsp' and ',' in item['label'])
    plans.append({'input': comma_label})
    columns = ['Gene', 'log2FC', 'PValue', 'FDR']
    raw = [dict(zip(columns, [plan['input'], '2', '.01', '.01'])) for plan in plans]
    thresholds = {'log2FcMin': 1, 'pValueMax': .05, 'fdrMax': .05}
    report = {'syntheticMeasurements': True, 'sourceLabelsAndIdsAreReal': True,
              'databaseReadOnly': True, 'externalCalls': False, 'tasksCreated': 0}
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        mapping = resolve_mapping(columns, {})
        parsed, qc = _parse_rows(raw, mapping, thresholds)
        dataset = ResearchDataset(owner_id=2, original_filename='SYNTHETIC-identity-probes.csv',
                                  content_sha256=digest(raw), name='Unsaved synthetic identity probes')
        task = AnalysisTask(owner_id=2, dataset=dataset, task_type='proteomics', input_parameters={'thresholds': thresholds})
        result, stored, _ = _build_result(parsed, [], columns, mapping, qc, task)
        assert len(stored) == len(plans) and result['summary']['databaseMappedCount'] == 0
        checked = []
        for row, plan in zip(stored, plans):
            assert row.original_label == plan['input']
            if 'expectedStatus' in plan:
                assert row.mapping_status == plan['expectedStatus'], (plan, row.mapping_status)
                assert row.matched_entity_id == plan['entityId'], (plan, row.matched_entity_id)
            checked.append({**plan, 'actualStatus': row.mapping_status, 'actualEntityId': row.matched_entity_id,
                            'originalLabelIntact': True, 'externalIdentifiers': row.external_identifiers})
        composite_row = stored[6]
        assert any(item['namespace'] == 'source_reported_uniprot' and item['identifier'] == 'P0DMV8;P0DMV9'
                   for item in composite_row.external_identifiers)
        for label, expected in baseline['readOnlyState'].items():
            model = apps.get_model(label)
            checksum, count = hashlib.sha256(), 0
            for row in model.objects.order_by('pk').values().iterator(chunk_size=500):
                plain = json.loads(json.dumps(row, cls=DjangoJSONEncoder))
                checksum.update((encoded(plain) + '\n').encode()); count += 1
            assert {'count': count, 'sha256': checksum.hexdigest()} == expected, label
        report.update(mappingProbes=checked, confirmedMappings=0, existingRecordsUnchanged=True)
    save('business-probes.json', report)

    # A disposable extracted copy swaps two assertions while counts stay equal.
    # The actual source files, catalogue and the original extraction stay intact.
    base = JOB
    original = json.loads((JOB / 'original-targets.json').read_text())
    hit = next(source for source in original['sources'] if source['provider'] == 'hit')
    left, right = hit['targets'][:2]
    assert left['labels'] != right['labels']
    left['labels'], right['labels'] = right['labels'], left['labels']
    JOB = base / 'fault-probe'
    try:
        save('original-targets.json', {**original, 'sources': [hit], 'syntheticCorruption': True})
        try:
            compare()
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError('Swapping real source assertions was not detected.')
        failed = json.loads((JOB / 'comparison.json').read_text())
        assert not failed['passed'] and len(failed['issues']) == 2
        assert all(item['kind'] == 'source_assertion_mismatch' for item in failed['issues'])
        assert failed['readOnlyState'] == baseline['readOnlyState']
    finally:
        JOB = base
    books = json.loads((JOB / 'original-targets.json').read_text())
    for source in books['sources']:
        for book in source['workbooks']:
            assert sha(IMPORT / 'inputs' / book['file']) == book['sha256']
    outcome = {'passed': True, 'mappingProbes': len(plans), 'syntheticMeasurementsOnly': True,
               'confirmedMappings': 0, 'countPreservingFaultDetected': True,
               'faultMismatchCount': 2, 'originalWorkbooksUnchanged': 7,
               'existingRecordsUnchanged': True, 'externalCalls': False, 'tasksCreated': 0}
    save('verification.json', outcome)
    print(encoded(outcome), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['extract', 'compare', 'verify'])
    args = parser.parse_args()
    {'extract': extract, 'compare': compare, 'verify': verify}[args.action]()


if __name__ == '__main__':
    main()
