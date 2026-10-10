"""Generate public synthetic R demos only; never use uploaded files or the DB.

Run: python r_viz/prepare_demo_gallery.py (R service URL/token from environment).
Outputs are reproducible build artifacts and ignored by Git.
"""
import base64
import json
import os
from pathlib import Path
import urllib.request
from demo_fixtures import DISCLAIMER, fixtures


def main():
    output = Path(__file__).resolve().parents[1] / 'public' / 'r-demo'
    output.mkdir(parents=True, exist_ok=True)
    url = os.environ.get('R_VIZ_BASE_URL', 'http://127.0.0.1:8001').rstrip('/') + '/render'
    token = os.environ['R_VIZ_API_TOKEN']
    manifest = {'synthetic': True, 'disclaimer': DISCLAIMER, 'charts': []}
    for chart in fixtures():
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
        (output / f"{chart['key']}.json").write_text(json.dumps(chart, ensure_ascii=False, indent=2), encoding='utf-8')
        manifest['charts'].append({'key': chart['key'], 'label': chart['label'], 'inputSha256': payload['inputSha256'], 'rendererVersion': result['rendererVersion']})
        print('PASS synthetic demo:', chart['key'], flush=True)
    # Publish the catalog only after all 14 renders succeed.
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Ready: {len(manifest['charts'])} charts / {output}")


if __name__ == '__main__':
    main()
