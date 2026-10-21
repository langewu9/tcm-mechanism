"""Read-only inventory of preserved compound identifiers and alias evidence.

Scans the immutable, provenance-bearing imported rows and verifies original file
checksums. No punctuation is interpreted as a chemical identity or alias rule.
"""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
IMPORT = ROOT / 'python_app/var/knowledge-import-2026-10-21'
JOB = ROOT / 'python_app/var/compound-lookup-2026-10-21'


def clean(value):
    return '' if value is None else str(value).strip()


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    JOB.mkdir(mode=0o700, exist_ok=True)
    output = JOB / 'identifier-alias-inventory.json'
    if output.exists():
        raise ValueError('Do not replace earlier inventory evidence.')
    manifest = json.loads((IMPORT / 'prepared.json').read_text())
    result = {'sources': [], 'punctuationIsIdentityEvidence': False, 'externalCalls': False}
    for entry in manifest['sources']:
        if entry['provider'] == 'disease':
            continue
        provider = entry['provider']
        workbook = entry['workbooks'][0]
        assert sha(IMPORT / 'inputs' / workbook['file']) == workbook['sha256']
        path = ROOT / 'python_app/var/postgres-acceptance/source-databases' / entry['databaseFile']
        assert sha(path) == entry['sqliteSha256']
        names, comma, ids, cids = set(), {}, defaultdict(set), defaultdict(set)
        names_to_ids, names_to_cids = defaultdict(set), defaultdict(set)
        missing, references, rows = Counter(), Counter(), 0
        cid_field = 'Pubchem ID' if provider == 'hit' else 'CID' if provider == 'batman' else None
        source_id_field = 'Compound Id' if provider == 'hit' else None
        with sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            for rowid, name, encoded in db.execute('SELECT rowid,component,extra FROM herb_component_target'):
                rows += 1
                data = json.loads(encoded);raw = data['rawFields'];name = clean(name)
                if not name:
                    missing['compoundName'] += 1
                    continue
                names.add(name)
                if ',' in name or '，' in name:
                    comma.setdefault(name, {'name': name, 'sourceRow': rowid, 'workbookSha256': workbook['sha256']})
                if source_id_field:
                    identifier = clean(raw.get(source_id_field))
                    if identifier:
                        ids[identifier].add(name);names_to_ids[name].add(identifier)
                    else:
                        missing['sourceCompoundId'] += 1
                if cid_field:
                    value = clean(raw.get(cid_field))
                    if not value:
                        missing['reportedPubchem'] += 1
                    elif re.fullmatch(r'(?:CID:)?[1-9][0-9]*', value, re.IGNORECASE):
                        number = value.split(':')[-1]
                        cids[number].add(name);names_to_cids[name].add(number);references['singleCidRows'] += 1
                    else:
                        references['nonSingleCidRows'] += 1
        source = {'provider': provider, 'file': workbook['file'], 'headers': workbook['headers'], 'acceptedRowsScanned': rows,
                  'sourceCompoundIdField': source_id_field, 'reportedPubchemField': cid_field, 'explicitAliasField': None,
                  'compoundLabels': len(names), 'sourceCompoundIds': len(ids), 'singleReportedPubchemIds': len(cids),
                  'sourceIdMultipleLabels': sum(len(values) > 1 for values in ids.values()),
                  'labelMultipleSourceIds': sum(len(values) > 1 for values in names_to_ids.values()),
                  'cidMultipleLabels': sum(len(values) > 1 for values in cids.values()),
                  'labelMultipleCids': sum(len(values) > 1 for values in names_to_cids.values()),
                  'missing': dict(missing), 'referenceRows': dict(references),
                  'commaLabels': len(comma), 'commaExamples': list(comma.values())[:5],
                  'conflictingCidExamples': [{'label': key, 'reportedCids': sorted(values)} for key, values in names_to_cids.items() if len(values) > 1][:5],
                  'originalWorkbookUnchanged': True}
        if provider == 'hit':
            source['C0671'] = {'labels': sorted(ids.get('C0671', set())), 'explicitAliasField': None,
                               'aliasStatus': 'not_registered_without_explicit_alias_evidence'}
        assert sha(path) == entry['sqliteSha256']
        assert sha(IMPORT / 'inputs' / workbook['file']) == workbook['sha256']
        result['sources'].append(source)
        print(json.dumps({key: value for key, value in source.items() if key not in {'headers', 'commaExamples', 'conflictingCidExamples'}}, ensure_ascii=False), flush=True)
    alias_file = ROOT / 'python_app/apps/core/data/component_aliases.json'
    aliases = json.loads(alias_file.read_text());exact, families = [], []
    owners = defaultdict(set)
    for index, record in enumerate(aliases['records']):
        (families if record.get('fuzzy') else exact).append(index)
        if not record.get('fuzzy'):
            for label in record['aliases']:
                owners[label.strip().casefold()].add(index)
    result['existingAliasTable'] = {'source': aliases['source'], 'sourceCommit': aliases['sourceCommit'], 'sha256': sha(alias_file),
        'profiles': len(aliases['records']), 'explicitProfiles': len(exact), 'familyProfilesExcludedFromExact': len(families),
        'explicitTerms': len(owners), 'overlappingTerms': {key: sorted(values) for key, values in owners.items() if len(values) > 1},
        'evidenceScope': 'explicit old-main query configuration, not authority-confirmed molecular equivalence'}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2));output.chmod(0o600)
    print(json.dumps(result['existingAliasTable'], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
