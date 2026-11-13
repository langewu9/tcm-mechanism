"""Live R smoke test using explicit SYNTHETIC fixtures, never stored as app evidence.

Run with the Django venv from python_app, with DJANGO_SETTINGS_MODULE configured,
and set R_VIZ_BASE_URL / R_VIZ_API_TOKEN in the environment. Optional generated
artifact output directory may be passed as the first argument.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path.cwd()))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from apps.core.services.r_analysis_catalog import build_catalog_payload


class NoSources:
    def count(self): return 0
    def order_by(self, *args): return self
    def values(self, *args): return []


nodes = [{'id': letter, 'label': f'SYNTHETIC_{letter}', 'type': 'protein'} for letter in ('A', 'B', 'C', 'D')]
ppi = {'source': 'STRING', 'sourceVersion': 'SYNTHETIC_FIXTURE_NOT_REAL', 'status': 'succeeded', 'networkType': 'physical', 'requiredScore': 700, 'nodes': nodes, 'edges': [{'source': 'A', 'target': 'B', 'score': 0.9}, {'source': 'B', 'target': 'C', 'score': 0.8}, {'source': 'C', 'target': 'D', 'score': 0.85}]}
network = {'nodes': [{'id': 'h', 'label': '合成中药', 'type': 'herb'}, {'id': 'c', 'label': '合成成分', 'type': 'compound'}, {'id': 't', 'label': 'SYNTHETIC_GENE', 'type': 'target'}, {'id': 'p', 'label': '合成通路', 'type': 'pathway'}, {'id': 'd', 'label': '合成疾病', 'type': 'disease'}], 'links': [{'source': 'h', 'target': 'c'}, {'source': 'c', 'target': 't'}, {'source': 't', 'target': 'p'}, {'source': 't', 'target': 'd'}]}
result = {'externalString': ppi, 'network': network, 'externalGProfiler': {'status': 'succeeded', 'sourceVersion': 'SYNTHETIC_FIXTURE', 'terms': [{'name': '合成测试功能条目', 'source': category, 'adjustedPValue': 0.01} for category in ('GO:BP', 'GO:CC', 'GO:MF', 'KEGG')]}, 'externalReactome': {'status': 'succeeded', 'sourceVersion': 'SYNTHETIC_FIXTURE', 'pathways': [{'name': '合成测试 Reactome 条目', 'matchedEntities': 2, 'totalEntities': 10, 'fdr': 0.01}]}}
task = SimpleNamespace(task_type='proteomics', result=result, source_releases=NoSources())
url = os.environ['R_VIZ_BASE_URL'].rstrip('/') + '/render'
token = os.environ['R_VIZ_API_TOKEN']
output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if output:
    output.mkdir(parents=True, exist_ok=True)

def request(payload, authorized=True):
    headers = {'Content-Type': 'application/json'}
    if authorized:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8'), headers=headers)
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.load(response)

keys = ('ppi_network', 'ppi_degree', 'evidence_network', 'gene_pathway_network', 'gene_pathway_distribution', 'proteomics_go_kegg_bar', 'reactome_enrichment')
for key in keys:
    payload = build_catalog_payload(task, key)
    payload['title'] = '合成接口验收（非实验）：' + payload['title']
    # Recompute canonical input hash after applying the explicit fixture label.
    from apps.core.services.r_analysis_catalog import seal
    payload.pop('inputSha256')
    payload = seal(payload)
    response = request(payload)
    assert response['inputSha256'] == payload['inputSha256']
    assert response['rendererVersion'] == 'r-viz-0.4.3'
    formats = {item['format']: item for item in response['artifacts']}
    assert set(formats) == {'svg', 'pdf', 'png', 'html'}
    for extension, artifact in formats.items():
        data = base64.b64decode(artifact['bytesBase64'], validate=True)
        assert data
        if extension == 'png': assert data.startswith(b'\x89PNG\r\n\x1a\n')
        if extension == 'pdf': assert data.startswith(b'%PDF')
        if extension == 'html': assert b'SYNTHETIC' in data or '合成'.encode() in data
        if output: (output / f'{key}.{extension}').write_bytes(data)
    print('PASS live R:', key, 'four artifacts', flush=True)

payload = build_catalog_payload(task, 'ppi_network')
for invalid, authorized, expected in [(payload, False, 401), ({**payload, 'edges': [{'source': 'A', 'target': 'missing', 'score': 0.9}]}, True, 400), ({**payload, 'data': [*payload['data'], payload['data'][0]]}, True, 400)]:
    try:
        request(invalid, authorized)
        raise AssertionError('Expected rejection')
    except urllib.error.HTTPError as error:
        assert error.code == expected, error.code
print('PASS R authentication, invalid endpoints and duplicate nodes', flush=True)
