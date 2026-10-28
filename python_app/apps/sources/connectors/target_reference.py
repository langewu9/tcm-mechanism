"""Download an immutable, public, reviewed-human UniProt identity crosswalk.

This module sends only a fixed catalogue query, never local target names or IDs.
It is also runnable without Django to prepare a versioned offline input file.
"""
import csv
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

QUERY = 'reviewed:true AND organism_id:9606'
FIELDS = 'accession,organism_id,gene_primary,xref_geneid,protein_name'
ROOT = 'https://rest.uniprot.org/uniprotkb/'
ACCESSION = re.compile(r'(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})')
HEADER = ['Entry', 'Organism (ID)', 'Gene Names (primary)', 'GeneID', 'Protein names']
MAX_BYTES = 24 * 1024 * 1024


def parse_reference(raw):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), delimiter='\t')
    if reader.fieldnames != HEADER:
        raise ValueError('Unexpected UniProt reference fields.')
    rows, accessions = [], set()
    for row in reader:
        accession = row['Entry'].strip()
        if not ACCESSION.fullmatch(accession) or accession in accessions or row['Organism (ID)'] != '9606':
            raise ValueError('Duplicate accession, malformed ID or species outside the reference scope.')
        genes = sorted(set(value.strip() for value in row['GeneID'].split(';') if value.strip()))
        if any(not re.fullmatch(r'[1-9][0-9]*', gene) for gene in genes):
            raise ValueError('Invalid NCBI Gene cross-reference.')
        name = row['Protein names'].strip()
        if not name: raise ValueError('Missing reference protein name.')
        rows.append({'accession': accession, 'taxon': '9606', 'symbol': row['Gene Names (primary)'].strip(),
                     'geneIds': genes, 'proteinName': name})
        accessions.add(accession)
    if not rows: raise ValueError('Empty target reference.')
    return rows


def _get(url, max_bytes):
    with urlopen(Request(url, headers={'User-Agent': 'TCM-Target-Identity/1.0', 'Accept': 'text/tab-separated-values'}), timeout=45) as response:
        if not response.url.startswith(ROOT): raise ValueError('Reference redirected outside UniProt.')
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes: raise ValueError('Target reference exceeds size limit.')
        return body, {k.lower(): v for k, v in response.headers.items()}


def download_reference(directory):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    params = {'query': QUERY, 'fields': FIELDS, 'format': 'tsv'}
    _, count_headers = _get(ROOT + 'search?' + urlencode({**params, 'size': 1}), 1024 * 1024)
    total = int(count_headers['x-total-results'])
    url = ROOT + 'stream?' + urlencode(params)
    raw, headers = _get(url, MAX_BYTES)
    version = headers.get('x-uniprot-release')
    if not version or version != count_headers.get('x-uniprot-release'):
        raise ValueError('UniProt version changed during download.')
    rows = parse_reference(raw)
    if not 10000 <= total <= 50000 or len(rows) != total:
        raise ValueError('Incomplete reviewed-human reference; record count differs from server total.')
    digest = hashlib.sha256(raw).hexdigest()
    name = f'uniprot-human-{version}-{digest[:12]}.tsv'
    path = directory / name
    if path.exists() and path.read_bytes() != raw: raise ValueError('Refusing to overwrite a versioned reference.')
    path.write_bytes(raw)
    manifest = {'schemaVersion': 'target-reference-v1', 'version': version, 'sha256': digest,
                'recordCount': total, 'url': url, 'query': QUERY, 'fields': FIELDS, 'file': name,
                'releaseDate': headers.get('x-uniprot-release-date'),
                'retrievedAt': datetime.now(timezone.utc).isoformat()}
    manifest_path = path.with_suffix('.manifest.json')
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest_path


def load_reference(manifest_path):
    path = Path(manifest_path).resolve(strict=True)
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if (manifest.get('schemaVersion') != 'target-reference-v1' or manifest.get('query') != QUERY
            or manifest.get('fields') != FIELDS or not str(manifest.get('url', '')).startswith(ROOT)):
        raise ValueError('Unsupported target reference provenance.')
    file = (path.parent / manifest['file']).resolve(strict=True)
    if file.parent != path.parent: raise ValueError('Reference file must stay beside its manifest.')
    if file.stat().st_size > MAX_BYTES: raise ValueError('Reference file exceeds size limit.')
    raw = file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest['sha256']: raise ValueError('Target reference checksum mismatch.')
    rows = parse_reference(raw)
    if len(rows) != manifest['recordCount']: raise ValueError('Target reference count mismatch.')
    return manifest, rows


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument('directory')
    args = parser.parse_args()
    print(download_reference(args.directory), flush=True)
