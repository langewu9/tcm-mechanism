"""Generate public synthetic R demos only; never use uploaded files or the DB.

Run: python r_viz/prepare_demo_gallery.py (R service URL/token from environment).
Outputs are reproducible build artifacts and ignored by Git.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import urllib.request
from demo_fixtures import DISCLAIMER, DATASET_VERSION, fixtures


def main():
    output = Path(os.environ.get('R_DEMO_OUTPUT_DIR', str(Path(__file__).resolve().parents[1] / 'public' / 'r-demo')))
    output.mkdir(parents=True, exist_ok=True)
    url = os.environ.get('R_VIZ_BASE_URL', 'http://127.0.0.1:8001').rstrip('/') + '/render'
    token = os.environ['R_VIZ_API_TOKEN']
    manifest = {'synthetic': True, 'datasetVersion': DATASET_VERSION, 'disclaimer': DISCLAIMER, 'charts': []}
    for chart in fixtures():
        artifact_hashes = {}
        payload = chart['payload']
        request = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(), headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.load(response)
        assert result['inputSha256'] == payload['inputSha256']
        artifacts = {item['format']: item for item in result['artifacts']}
        assert set(artifacts) == {'svg', 'png', 'pdf', 'html'}
        for extension, item in artifacts.items():
            content = base64.b64decode(item['bytesBase64'], validate=True)
            assert content
            if extension == 'png':
                assert content.startswith(b'\x89PNG\r\n\x1a\n')
            if extension == 'pdf':
                assert content.startswith(b'%PDF')
            if extension == 'html':
                assert '合成演示'.encode() in content
            (output / f"{chart['key']}.{extension}").write_bytes(content)
            artifact_hashes[extension] = hashlib.sha256(content).hexdigest()
        (output / f"{chart['key']}.json").write_text(json.dumps(chart, ensure_ascii=False, indent=2), encoding='utf-8')
        manifest['charts'].append({'key': chart['key'], 'label': chart['label'], 'inputSha256': payload['inputSha256'], 'rendererVersion': result['rendererVersion'], 'artifacts': artifact_hashes,
                                  'rowCount': len(payload['data']), 'nodeCount': len(payload['data']) if payload['chartType'] == 'network' else 0, 'edgeCount': len(payload.get('edges', []))})
        print('PASS synthetic demo:', chart['key'], flush=True)
    # Publish the catalog only after every render succeeds.
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Ready: {len(manifest['charts'])} charts / {output}")


if __name__ == '__main__':
    main()
