"""Fetch a small, public-only STRING snapshot and render it with R.

No user uploads, application DB, model, or INPUT site data are accessed.
Run with --refresh to explicitly replace the frozen source snapshot.
"""
import argparse
import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import urllib.parse
import urllib.request

API = 'https://version-12-5.string-db.org/api'
GENES = 'TP53 MDM2 CDKN1A BAX BCL2 BCL2L1 CASP3 CASP8 CASP9 CASP1 AKT1 MAPK1 MAPK3 MAPK8 MAPK14 JUN FOS RELA NFKB1 NFKBIA IKBKB TNF TNFRSF1A TNFRSF1B IL1B IL1A IL1R1 IL1RN IL6 IL6R IL6ST IL10 IL4 IL13 IL2 IFNG CXCL8 CCL2 CCL5 CXCL10 CXCL2 CXCR4 CCR2 MYD88 TLR4 TLR2 IRAK1 TRAF6 EGFR VEGFA TGFB1 STAT1 STAT3 JAK1 JAK2 NFE2L2 KEAP1 HMOX1 NQO1 SOD1 SOD2 CAT CYBA CYBB'.split()
ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'r_viz/public_data/string_inflammation_v12_5.json'
DISCLAIMER = 'STRING 公开数据示例 · 人类预选基因集 · 非用户实验结果 · 不代表中药疗效或因果结论'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def query(method, parameters):
    data = urllib.parse.urlencode({**parameters, 'caller_identity': 'tcm-mechanism-public-gallery'}).encode()
    request = urllib.request.Request(f'{API}/json/{method}', data=data, headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(request, timeout=90) as response:
        raw = response.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError('Public API response exceeds snapshot limit')
    value = json.loads(raw)
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f'Invalid STRING {method} response')
    return value


def fetch_snapshot():
    mapping = query('get_string_ids', {'identifiers': '\r'.join(GENES), 'species': 9606, 'limit': 1, 'echo_query': 1})
    assert mapping and all(row.get('ncbiTaxonId') == 9606 for row in mapping)
    identifiers = sorted({row['stringId'] for row in mapping})
    network = query('network', {'identifiers': '\r'.join(identifiers), 'species': 9606, 'network_type': 'physical', 'required_score': 400, 'add_nodes': 0})
    enrichment = query('enrichment', {'identifiers': '\r'.join(identifiers), 'species': 9606})
    snapshot = {'schemaVersion': 1, 'source': 'STRING', 'sourceVersion': '12.5', 'license': 'CC BY 4.0',
        'sourceUrl': 'https://string-db.org/', 'licenseUrl': 'https://string-db.org/cgi/access', 'apiBaseUrl': API,
        'retrievedAt': datetime.now(timezone.utc).isoformat(), 'queryGenes': GENES, 'species': 9606,
        'networkType': 'physical', 'requiredScore': 400, 'background': 'STRING default human genome background (no custom background supplied)',
        'mapping': mapping, 'network': network, 'enrichment': enrichment}
    snapshot['contentSha256'] = digest(snapshot)
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
    return snapshot


def public_fixtures(snapshot):
    snapshot_copy = {key: value for key, value in snapshot.items() if key != 'contentSha256'}
    assert digest(snapshot_copy) == snapshot['contentSha256']
    assert snapshot['source'] == 'STRING' and snapshot['networkType'] == 'physical' and snapshot['species'] == 9606
    mapping = {row['stringId']: row['preferredName'] for row in snapshot['mapping']}
    links = {}
    for row in snapshot['network']:
        left, right = row['stringId_A'], row['stringId_B']
        score = float(row['score'])
        assert left in mapping and right in mapping and 0 <= score <= 1
        if left != right and score >= snapshot['requiredScore'] / 1000:
            pair = tuple(sorted((left, right)))
            links[pair] = max(score, links.get(pair, 0))
    edges = [{'source': a, 'target': b, 'score': score} for (a, b), score in sorted(links.items(), key=lambda item: (-item[1], item[0]))[:500]]
    ids = sorted({end for edge in edges for end in (edge['source'], edge['target'])})
    adjacency = {identifier: set() for identifier in ids}
    for edge in edges:
        adjacency[edge['source']].add(edge['target'])
        adjacency[edge['target']].add(edge['source'])
    nodes = [{'id': identifier, 'label': mapping[identifier], 'type': 'protein', 'degree': len(adjacency[identifier])} for identifier in ids]
    assert 2 <= len(nodes) <= 80 and edges
    provenance = {key: snapshot[key] for key in ('source', 'sourceVersion', 'license', 'sourceUrl', 'licenseUrl', 'retrievedAt', 'contentSha256', 'species', 'networkType', 'requiredScore', 'background')}
    provenance.update(queryGeneCount=len(snapshot['queryGenes']), mappedGeneCount=len(mapping), returnedUniqueEdgeCount=len(links), displayedEdgeCount=len(edges), displayedNodeCount=len(nodes),
        transformations='Mapped identifiers, undirected duplicate removal (maximum score), sorted by score then ID; at most 500 edges. Degrees recalculated on displayed subgraph. Enrichment selected by reported FDR, no p-values recomputed.')
    charts = []

    def add(key, label, payload):
        payload.update(title='公开数据示例：' + label, subtitle=DISCLAIMER)
        payload['inputSha256'] = digest(payload)
        charts.append({'key': key, 'label': label, 'synthetic': False, 'publicExample': True, 'provenance': provenance, 'payload': payload})

    add('ppi_network', 'STRING 人类炎症与应激物理互作网络', {'chartType': 'network', 'layout': 'circular', 'data': nodes, 'edges': edges})
    add('ppi_degree', 'STRING 展示子图连接度', {'chartType': 'bar', 'yLabel': '展示子图唯一邻居数（非因果排名）', 'data': [{'label': node['label'], 'value': node['degree']} for node in sorted(nodes, key=lambda node: (-node['degree'], node['label']))]})
    sources = {'Process': 'GO:BP', 'Function': 'GO:MF', 'Component': 'GO:CC', 'KEGG': 'KEGG', 'RCTM': 'Reactome'}
    terms = []
    for category, source in sources.items():
        rows = sorted((row for row in snapshot['enrichment'] if row.get('category') == category and 0 < float(row.get('fdr', 1)) <= 0.05), key=lambda row: (float(row['fdr']), row['term']))[:5]
        for row in rows:
            hits = int(row['number_of_genes'])
            assert 0 < hits <= len(mapping)
            terms.append({'label': row['description'], 'source': source, 'termId': row['term'], 'geneRatio': hits / len(mapping),
                'adjustedPValue': float(row['fdr']), 'intersectionSize': hits, 'inputGenes': row.get('inputGenes', []), 'preferredNames': row.get('preferredNames', [])})
    go_terms = [{key: value for key, value in row.items() if key not in {'inputGenes', 'preferredNames', 'termId'}} for row in terms if row['source'] != 'Reactome']
    reactome = [{key: value for key, value in row.items() if key not in {'inputGenes', 'preferredNames', 'termId'}} for row in terms if row['source'] == 'Reactome']
    if go_terms:
        add('proteomics_go_kegg_enrichment', 'STRING GO / KEGG 富集', {'chartType': 'enrichment_bubble', 'xLabel': '命中数 / 已映射预选基因数', 'data': go_terms})
        import math
        add('proteomics_go_kegg_bar', 'STRING GO / KEGG 富集显著性点图', {'chartType': 'bar', 'yLabel': '−log10(STRING 报告 FDR)', 'data': [{'label': row['source'] + ' · ' + row['label'], 'value': -math.log10(row['adjustedPValue'])} for row in go_terms]})
    if reactome:
        add('reactome_enrichment', 'STRING 报告的 Reactome 富集', {'chartType': 'enrichment_bubble', 'xLabel': '命中数 / 已映射预选基因数', 'data': reactome})
    pathway_terms = [row for row in terms if row['source'] in ('KEGG', 'Reactome')][:8]
    pathway_edges = []
    pathway_nodes = []
    for row in pathway_terms:
        hit_ids = sorted(set(row['inputGenes']) & mapping.keys())
        if not hit_ids:
            reverse = {name: identifier for identifier, name in mapping.items()}
            hit_ids = sorted({reverse[name] for name in row['preferredNames'] if name in reverse})
        if not hit_ids:
            continue
        pathway_id = row['source'] + ':' + row['termId']
        pathway_nodes.append({'id': pathway_id, 'label': row['label'], 'type': 'pathway', 'degree': len(hit_ids)})
        pathway_edges.extend({'source': identifier, 'target': pathway_id, 'score': 1.0} for identifier in hit_ids)
    gene_ids = sorted({edge['source'] for edge in pathway_edges})
    gene_nodes = [{'id': identifier, 'label': mapping[identifier], 'type': 'protein', 'degree': len({edge['target'] for edge in pathway_edges if edge['source'] == identifier})} for identifier in gene_ids]
    if pathway_edges and len(gene_nodes) + len(pathway_nodes) <= 80 and len(pathway_edges) <= 500:
        add('gene_pathway_network', 'STRING 命中基因—通路弦图', {'chartType': 'network', 'layout': 'circular', 'data': gene_nodes + pathway_nodes, 'edges': pathway_edges})
        add('gene_pathway_distribution', 'STRING 通路命中基因数', {'chartType': 'bar', 'yLabel': '预选基因集中实际通路命中数（非显著性）', 'data': [{'label': node['label'], 'value': node['degree']} for node in pathway_nodes]})
    return charts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--fetch-only', action='store_true')
    args = parser.parse_args()
    snapshot = fetch_snapshot() if args.refresh or not SNAPSHOT.exists() else json.loads(SNAPSHOT.read_text(encoding='utf-8'))
    charts = public_fixtures(snapshot)
    print('Public snapshot:', len(snapshot['mapping']), 'mapped genes;', len(snapshot['network']), 'raw edges;', len(snapshot['enrichment']), 'reported terms;', len(charts), 'chart keys', flush=True)
    if args.fetch_only:
        return
    output = ROOT / 'public/r-public-demo'
    output.mkdir(parents=True, exist_ok=True)
    url = os.environ['R_VIZ_BASE_URL'].rstrip('/') + '/render'
    token = os.environ['R_VIZ_API_TOKEN']
    manifest = {'synthetic': False, 'publicExample': True, 'disclaimer': DISCLAIMER, 'provenance': charts[0]['provenance'], 'charts': []}
    for chart in charts:
        request = urllib.request.Request(url, data=json.dumps(chart['payload'], ensure_ascii=False).encode(), headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.load(response)
        assert result['inputSha256'] == chart['payload']['inputSha256']
        artifacts = {row['format']: row for row in result['artifacts']}
        assert set(artifacts) == {'svg', 'pdf', 'png', 'html'}
        hashes = {}
        for extension, artifact in artifacts.items():
            content = base64.b64decode(artifact['bytesBase64'], validate=True)
            (output / f"{chart['key']}.{extension}").write_bytes(content)
            hashes[extension] = hashlib.sha256(content).hexdigest()
        (output / f"{chart['key']}.json").write_text(json.dumps(chart, ensure_ascii=False, indent=2), encoding='utf-8')
        manifest['charts'].append({'key': chart['key'], 'label': chart['label'], 'inputSha256': chart['payload']['inputSha256'], 'rendererVersion': result['rendererVersion'], 'artifacts': hashes})
        print('PASS public example:', chart['key'], flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
