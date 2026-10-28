"""Deterministic synthetic gallery fixtures; never experimental or database evidence."""
import hashlib
import json
import math
import random

DISCLAIMER = '合成演示数据 · 非真实实验 · 不代表数据库证据或生物学结论'
DATASET_VERSION = 'dense-20261027'


def fixtures():
    charts = []

    def add(key, label, payload):
        payload = {**payload, 'title': '合成演示：' + label, 'subtitle': DISCLAIMER}
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        payload['inputSha256'] = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        charts.append({'key': key, 'label': label, 'synthetic': True, 'payload': payload})

    def bars(key, label, rows, axis='数量'):
        add(key, label, {'chartType': 'bar', 'yLabel': axis, 'data': [{'label': name, 'value': value} for name, value in rows]})

    def graph(key, label, nodes, edges, layout):
        adjacency = {node['id']: set() for node in nodes}
        unique = sorted({tuple(sorted((left, right))) for left, right in edges if left != right})
        links = []
        for index, (left, right) in enumerate(unique):
            adjacency[left].add(right)
            adjacency[right].add(left)
            links.append({'source': left, 'target': right, 'score': round(0.72 + (index % 7) * 0.035, 3)})
        add(key, label, {'chartType': 'network', 'layout': layout, 'data': [{**node, 'degree': len(adjacency[node['id']])} for node in nodes], 'edges': links})
        return adjacency

    proteins = [{'id': f'g{i}', 'label': f'DEMO_GENE_{i:02}', 'type': 'protein'} for i in range(1, 73)]
    pairs = [(f'g{i+1}', f'g{(i+offset) % 72+1}') for i in range(72) for offset in (1, 2, 5, 11, 18)]
    adjacency = graph('ppi_network', 'PPI 网络图', proteins, pairs, 'circular')
    bars('ppi_degree', 'PPI 连接度排行', [(node['label'], len(adjacency[node['id']])) for node in proteins], '唯一邻居数')
    herbs = [{'id': f'h{i}', 'label': f'演示中药{i}', 'type': 'herb'} for i in range(1, 5)]
    compounds = [{'id': f'c{i}', 'label': f'演示成分{i}', 'type': 'compound'} for i in range(1, 11)]
    pathways = [{'id': f'p{i}', 'label': f'演示通路{i:02}', 'type': 'pathway'} for i in range(1, 19)]
    diseases = [{'id': f'd{i}', 'label': f'演示疾病{i}', 'type': 'disease'} for i in range(1, 3)]
    evidence_pathways = [(f'p{i}', f'g{(i*3+j) % 40+1}') for i in range(1, 19) for j in range(12)]
    evidence_edges = [(f'h{(i-1) % 4+1}', f'c{i}') for i in range(1, 11)]
    evidence_edges += [(f'c{i}', f'g{(i*3+j) % 40+1}') for i in range(1, 11) for j in range(8)]
    evidence_edges += [(f'g{i}', f'd{(i-1) % 2+1}') for i in range(1, 41)] + evidence_pathways
    evidence_nodes = herbs + compounds + proteins[:40] + pathways + diseases
    graph('evidence_network', '中药—成分—靶点—疾病网络', evidence_nodes, evidence_edges, 'circular')
    pathway_edges = [(f'p{i}', f'g{(i*3+j) % 56+1}') for i in range(1, 19) for j in range(15)]
    graph('gene_pathway_network', '基因—通路网络', proteins[:56] + pathways, pathway_edges, 'circular')
    bars('gene_pathway_distribution', '通路关联基因分布', [(node['label'], 15) for node in pathways], '唯一关联基因数（非富集检验）')
    terms = [{'label': f'演示功能条目 {source} {i:02}', 'source': source, 'geneRatio': (3+i)/72, 'adjustedPValue': 10 ** (-2-i*0.25), 'intersectionSize': 3+i} for source in ('GO:BP', 'GO:CC', 'GO:MF', 'KEGG') for i in range(1, 13)]
    bars('proteomics_go_kegg_bar', 'GO / KEGG 富集显著性点图', [(row['source'] + ' · ' + row['label'], -math.log10(row['adjustedPValue'])) for row in terms], '−log10(模拟 FDR)')
    add('proteomics_go_kegg_enrichment', 'GO / KEGG 富集气泡图', {'chartType': 'enrichment_bubble', 'xLabel': '模拟 GeneRatio', 'data': terms})
    reactome = [{'label': f'演示 Reactome 条目 {i:02}', 'source': 'Reactome', 'geneRatio': (i+2)/(i*12+20), 'intersectionSize': i+2, 'adjustedPValue': 10 ** (-2-i*0.15)} for i in range(1, 21)]
    add('reactome_enrichment', 'Reactome 通路气泡图', {'chartType': 'enrichment_bubble', 'xLabel': '模拟命中实体 / 通路实体', 'sizeLabel': '模拟命中实体数', 'data': reactome})
    bars('proteomics_summary', '蛋白组学分析概览', [('筛选行', 360), ('标准化', 352), ('本地映射', 300), ('未映射', 52), ('候选交集', 126), ('通路', 18)])
    bars('proteomics_top_nodes', '本地通路网络连接度', [(f'DEMO_GENE_{i:02}', 2 + i % 12) for i in range(1, 41)], '模拟 Degree')
    bars('overlap', '中药—疾病靶点交集', [('中药靶点', 480), ('疾病靶点', 356), ('交集靶点', 126)])
    bars('components', '关联成分靶点数', [(f'演示成分{i:02}', 8 + (i*7) % 40) for i in range(1, 25)])
    bars('pathways', '关联通路靶点数', [(f'演示通路{i:02}', 6 + (i*3) % 32) for i in range(1, 25)])
    bars('catalog_summary', '检索实体与证据概览', [('演示中药实体', len(herbs)), ('演示成分实体', len(compounds)), ('演示靶点实体', 40), ('演示通路实体', len(pathways)), ('演示疾病实体', len(diseases)), ('演示去重关系', len(evidence_edges))], '模拟实体 / 关系数量')
    bars('catalog_degree', '检索实体连接度', [(f'DEMO_ENTITY_{i:02}', 2+(72-i)//3) for i in range(1, 61)], '模拟唯一邻居数（非因果排名）')
    rng = random.Random(20261010)
    points = []
    for i in range(1200):
        effect = 0 if i < 800 else (1.8 if i < 1000 else -1.8)
        fc = round(rng.gauss(effect, 0.45 if effect == 0 else 0.65), 4)
        p = round(rng.uniform(0.01, 1) if effect == 0 else 10 ** (-rng.uniform(1.1, 7)), 9)
        points.append({'label': f'DEMO_PROTEIN_{i+1:04}', 'log2FoldChange': fc, 'pValue': p, 'fdr': 1.0, 'selected': abs(fc) >= 1 and p <= 0.05})
    rank = sorted(range(len(points)), key=lambda index: points[index]['pValue'])
    adjusted = 1.0
    for position in range(len(rank)-1, -1, -1):
        index = rank[position]
        adjusted = min(adjusted, points[index]['pValue'] * len(points) / (position+1))
        points[index]['fdr'] = adjusted
    add('proteomics_volcano', '差异蛋白火山图', {'chartType': 'volcano', 'thresholds': {'log2FoldChange': 1, 'pValue': 0.05}, 'data': points})
    return charts
