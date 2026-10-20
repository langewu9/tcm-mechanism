"""Deterministic, chart-ready synthetic data. No DB, identifiers or external evidence."""
import hashlib
import json
import math
import random

DISCLAIMER = '合成演示数据 · 非真实实验 · 不代表数据库证据或生物学结论'


def fixtures():
    charts = []

    def add(key, label, payload):
        payload = {**payload, 'title': '合成演示（非实验）：' + label, 'subtitle': DISCLAIMER}
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        payload['inputSha256'] = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        charts.append({'key': key, 'label': label, 'synthetic': True, 'payload': payload})

    def bars(key, label, rows, axis='数量'):
        add(key, label, {'chartType': 'bar', 'yLabel': axis, 'data': [{'label': name, 'value': value} for name, value in rows]})

    def graph(key, label, nodes, edges, layout):
        adjacency = {node['id']: set() for node in nodes}
        links = []
        for index, (left, right) in enumerate(edges):
            adjacency[left].add(right)
            adjacency[right].add(left)
            links.append({'source': left, 'target': right, 'score': round(0.72 + (index % 7) * 0.035, 3)})
        add(key, label, {'chartType': 'network', 'layout': layout, 'data': [{**node, 'degree': len(adjacency[node['id']])} for node in nodes], 'edges': links})
        return adjacency

    proteins = [{'id': f'g{i}', 'label': f'DEMO_GENE_{i:02}', 'type': 'protein'} for i in range(1, 13)]
    pairs = [(f'g{i}', f'g{i+1}') for i in range(1, 12)] + [('g1', f'g{i}') for i in (3, 5, 7, 9, 11)] + [('g4', 'g8'), ('g6', 'g10')]
    adjacency = graph('ppi_network', 'PPI 网络图', proteins, pairs, 'circular')
    bars('ppi_degree', 'PPI 连接度排行', [(node['label'], len(adjacency[node['id']])) for node in proteins], '唯一邻居数')
    herbs = [{'id': f'h{i}', 'label': f'演示中药{i}', 'type': 'herb'} for i in (1, 2)]
    compounds = [{'id': f'c{i}', 'label': f'演示成分{i}', 'type': 'compound'} for i in range(1, 5)]
    pathways = [{'id': f'p{i}', 'label': f'演示通路{i}', 'type': 'pathway'} for i in range(1, 5)]
    disease = [{'id': 'd1', 'label': '演示疾病（虚构）', 'type': 'disease'}]
    pathway_edges = [(f'p{i}', f'g{j}') for i in range(1, 5) for j in range(i, i + 4)]
    evidence_edges = [('h1', 'c1'), ('h1', 'c2'), ('h2', 'c3'), ('h2', 'c4')] + [(f'c{i}', f'g{j}') for i in range(1, 5) for j in (i, i+4)] + [(f'g{i}', 'd1') for i in range(1, 9)] + pathway_edges
    graph('evidence_network', '中药—成分—靶点—疾病网络', herbs + compounds + proteins[:8] + pathways + disease, evidence_edges, 'layered')
    graph('gene_pathway_network', '基因—通路网络', proteins[:7] + pathways, pathway_edges, 'layered')
    bars('gene_pathway_distribution', '通路关联基因分布', [(node['label'], 4) for node in pathways], '唯一关联基因数（非富集检验）')
    terms = [{'label': f'演示功能条目 {source} {i}', 'source': source, 'geneRatio': (3+i)/20, 'adjustedPValue': 10 ** (-2-i*0.5), 'intersectionSize': 3+i} for source in ('GO:BP', 'GO:CC', 'GO:MF', 'KEGG') for i in (1, 2, 3)]
    bars('proteomics_go_kegg_bar', 'GO / KEGG 富集条形图', [(row['label'], -math.log10(row['adjustedPValue'])) for row in terms], '−log10(模拟 FDR)')
    add('proteomics_go_kegg_enrichment', 'GO / KEGG 富集气泡图', {'chartType': 'enrichment_bubble', 'xLabel': '模拟 GeneRatio', 'data': terms})
    reactome = [{'label': f'演示 Reactome 条目 {i}', 'source': 'Reactome', 'geneRatio': (i+2)/(i*12+20), 'intersectionSize': i+2, 'adjustedPValue': 10 ** (-2-i*0.3)} for i in range(1, 7)]
    add('reactome_enrichment', 'Reactome 通路气泡图', {'chartType': 'enrichment_bubble', 'xLabel': '模拟命中实体 / 通路实体', 'sizeLabel': '模拟命中实体数', 'data': reactome})
    bars('proteomics_summary', '蛋白组学分析概览', [('筛选行', 42), ('标准化', 42), ('本地映射', 30), ('未映射', 12), ('候选交集', 8), ('通路', 4)])
    bars('proteomics_top_nodes', '本地通路网络连接度', [(f'DEMO_GENE_{i:02}', 1 + i % 4) for i in range(1, 13)], '模拟 Degree')
    bars('overlap', '中药—疾病靶点交集', [('中药靶点', 30), ('疾病靶点', 24), ('交集靶点', 8)])
    bars('components', '关联成分靶点数', [(f'演示成分{i}', i+2) for i in range(1, 7)])
    bars('pathways', '关联通路靶点数', [(f'演示通路{i}', 8-i) for i in range(1, 7)])
    rng = random.Random(20261010)
    points = []
    for i in range(180):
        fc = round(rng.gauss(0, 1.55), 4)
        p = round(10 ** (-rng.uniform(0.1, 5)), 7)
        points.append({'label': f'DEMO_PROTEIN_{i+1:03}', 'log2FoldChange': fc, 'pValue': p, 'fdr': min(1, p*3), 'selected': abs(fc) >= 1 and p <= 0.05})
    add('proteomics_volcano', '差异蛋白火山图', {'chartType': 'volcano', 'thresholds': {'log2FoldChange': 1, 'pValue': 0.05}, 'data': points})
    return charts
