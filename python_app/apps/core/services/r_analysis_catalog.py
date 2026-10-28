"""INPUT-inspired charts over persisted evidence; never invent interaction edges."""
import hashlib
import json
import math

NEW_CHART_KEYS = {
    'ppi_network', 'ppi_degree', 'evidence_network', 'gene_pathway_network',
    'gene_pathway_distribution', 'proteomics_go_kegg_bar', 'reactome_enrichment',
    'catalog_summary', 'catalog_degree',
}


def number(value, low=0, high=float('inf')):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high


def text(value, limit=120):
    return ''.join(c for c in value if c.isprintable()).strip()[:limit] if isinstance(value, str) else ''


def evidence_graph(network, *, physical=False, required_score=0):
    if not isinstance(network, dict):
        raise ValueError('没有可绘制的网络结果。')
    raw_nodes = network.get('nodes') or []
    raw_edges = network.get('edges' if physical else 'links') or []
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list) or len(raw_nodes) > 5000 or len(raw_edges) > 25000:
        raise ValueError('网络输入格式无效或超过安全上限。')
    nodes = {}
    for node in raw_nodes:
        if not isinstance(node, dict):
            continue
        key = node.get('id')
        if not isinstance(key, str) or not key or len(key) > 200 or key in nodes:
            continue
        label = text(node.get('label'))
        if label:
            nodes[key] = {'id': key, 'label': label, 'type': text(node.get('type'), 40) or 'target'}
    edges = {}
    for edge in raw_edges:
        if not isinstance(edge, dict):
            continue
        left, right = edge.get('source'), edge.get('target')
        if not isinstance(left, str) or not isinstance(right, str) or left not in nodes or right not in nodes or left == right:
            continue
        score = edge.get('score') if physical else 1.0
        if not number(score, 0, 1) or (physical and score * 1000 + 1e-9 < required_score):
            continue
        pair = tuple(sorted((left, right)))
        if pair not in edges or score > edges[pair]['score']:
            edges[pair] = {'source': pair[0], 'target': pair[1], 'score': float(score)}
        if not physical:
            # Preserve evidence direction and provenance despite display-pair deduplication.
            provenance = {key: text(edge.get(key), 160) for key in ('relation', 'sourceSlug', 'sourceVersion', 'sourceRecordId', 'evidenceType')}
            provenance.update(source=left, target=right)
            items = edges[pair].setdefault('evidence', [])
            if provenance not in items and len(items) < 5: items.append(provenance)
    if not edges:
        raise ValueError('没有有效证据关系，不能生成网络或分布图。')
    return nodes, list(edges.values())


def neighbors(nodes, edges):
    adjacent = {key: set() for key in nodes}
    for edge in edges:
        adjacent[edge['source']].add(edge['target'])
        adjacent[edge['target']].add(edge['source'])
    return adjacent


def build_catalog_payload(task, chart_key):
    result = task.result or {}
    def finish(payload):
        if payload.get('chartType') == 'bar':
            labels = [row['label'] for row in payload['data']]
            if len(labels) != len(set(labels)):
                for index, row in enumerate(payload['data'], 1):
                    row['label'] = f"#{index} {row['label']}"[:120]
        payload['sourceVersions'] = list(task.source_releases.order_by('pk').values('source__slug', 'version')[:50])
        return seal(payload)
    if chart_key in {'catalog_summary', 'catalog_degree'}:
        if task.task_type != 'network' or result.get('analysisKind') != 'catalog_evidence':
            raise ValueError('当前任务不是已保存的目录检索快照。')
        if chart_key == 'catalog_summary':
            data = result.get('catalogSummary') or []
            title, axis = '检索实体与证据概览', '按本地主键去重的实体 / 关系数量'
            if result.get('queryType') == 'comparison': title, axis = '名称对照数量概览', '规范化名称数量（非化学鉴定）'
        elif result.get('queryType') == 'pathway':
            data = result.get('catalogCoverage') or []
            title, axis = '本地通路靶点注释分布', '唯一靶点数（非统计富集）'
        else:
            nodes, edges = evidence_graph(result.get('network'))
            adjacent = neighbors(nodes, edges)
            ranked = sorted(nodes, key=lambda key: (-len(adjacent[key]), key))[:30]
            data = [{'label': f"{nodes[key]['label']} [{key}]"[:120], 'value': len(adjacent[key])} for key in ranked]
            title, axis = '检索网络实体连接度', '完整查询网络的唯一邻居数（非因果排名）'
        data = [row for row in data if isinstance(row, dict) and text(row.get('label')) and number(row.get('value'))]
        if not data: raise ValueError('本次检索没有可绘制的统计条目。')
        data = sorted(data, key=lambda row: -row['value'])[:30] if chart_key == 'catalog_degree' else data[:30]
        subtitle = f"本次检索快照 · 来源版本数 {task.source_releases.count()} · 非疗效或富集结论"
        if result.get('queryType') == 'comparison':
            subtitle = '名称对照快照 · 别名源版本 '+text((result.get('queryResult') or {}).get('aliasSourceCommit'))+' · 同家族候选不计入精确交集'
        return finish({'chartType': 'bar', 'title': title, 'yLabel': axis, 'subtitle': subtitle, 'data': data})
    if chart_key.startswith('ppi_'):
        source = result.get('externalString') if task.task_type == 'proteomics' else result
        if not isinstance(source, dict) or source.get('networkType') != 'physical' or source.get('source') != 'STRING' or source.get('status', 'succeeded') != 'succeeded' or (task.task_type == 'proteomics' and source.get('status') != 'succeeded'):
            raise ValueError('请先单独同意并完成 STRING 物理互作查询。')
        if task.task_type != 'proteomics' and source.get('analysisKind') != 'string_ppi':
            raise ValueError('当前任务不是已完成的 STRING 物理互作分析。')
        required_score = source.get('requiredScore')
        if not number(required_score, 0, 1000):
            raise ValueError('STRING 置信度参数无效。')
        nodes, edges = evidence_graph(source, physical=True, required_score=required_score)
        title = 'STRING 物理互作网络' if chart_key == 'ppi_network' else 'PPI 连接度排行（返回图）'
        subtitle = f"STRING {text(source.get('sourceVersion')) or '版本未知'} · Homo sapiens · score ≥ {required_score:g}/1000"
    elif chart_key in {'evidence_network', 'gene_pathway_network', 'gene_pathway_distribution'}:
        if task.task_type not in {'network', 'proteomics'}:
            raise ValueError('当前任务不支持证据关系图。')
        nodes, edges = evidence_graph(result.get('network'))
        if chart_key != 'evidence_network':
            target_types = {'target', 'gene', 'protein'}
            edges = [edge for edge in edges if
                     (nodes[edge['source']]['type'] == 'pathway' and nodes[edge['target']]['type'] in target_types) or
                     (nodes[edge['target']]['type'] == 'pathway' and nodes[edge['source']]['type'] in target_types)]
            if not edges:
                raise ValueError('当前没有来源可追溯的基因—通路关系。')
            used = {endpoint for edge in edges for endpoint in (edge['source'], edge['target'])}
            nodes = {key: value for key, value in nodes.items() if key in used}
        title = {'evidence_network': '中药—成分—靶点—疾病证据网络', 'gene_pathway_network': '基因—通路证据网络', 'gene_pathway_distribution': '通路关联基因分布（非富集检验）'}[chart_key]
        subtitle = f'本地登记关系 · 来源版本数 {task.source_releases.count()} · 不推测缺失关系'
        if result.get('analysisKind') == 'catalog_evidence' and chart_key == 'evidence_network':
            title = '中药—成分—靶点目录关系图'
            subtitle = f'旧表登记关系 · 来源版本数 {task.source_releases.count()} · 非实验验证，靶点名称未必已标准化'
    elif chart_key in {'proteomics_go_kegg_bar', 'reactome_enrichment'}:
        if chart_key == 'proteomics_go_kegg_bar':
            source = result.get('externalGProfiler') or {}
            rows = source.get('terms') or []
            source_name = 'g:Profiler'
        else:
            source = (result.get('externalReactome') or {}) if task.task_type == 'proteomics' else result
            if task.task_type != 'proteomics' and source.get('analysisKind') != 'reactome_enrichment':
                raise ValueError('当前任务不是 Reactome 富集结果。')
            rows = source.get('pathways') or []
            source_name = 'Reactome'
        if source.get('status', 'succeeded') != 'succeeded' or not isinstance(rows, list):
            raise ValueError('请先完成相应的富集分析。')
        data = []
        for row in rows[:5000]:
            if not isinstance(row, dict):
                continue
            label = text(row.get('name'), 140)
            fdr = row.get('adjustedPValue') if source_name == 'g:Profiler' else row.get('fdr')
            category = row.get('source') if source_name == 'g:Profiler' else 'Reactome'
            if not label or not number(fdr, 0, 0.05) or fdr <= 0 or category not in {'GO:BP', 'GO:CC', 'GO:MF', 'KEGG', 'Reactome'}:
                continue
            if chart_key == 'reactome_enrichment':
                hits, total = row.get('matchedEntities'), row.get('totalEntities')
                if not number(hits, 1) or not number(total, 1) or hits > total or hits != int(hits) or total != int(total):
                    continue
                data.append({'label': label, 'source': category, 'geneRatio': hits / total, 'adjustedPValue': fdr, 'intersectionSize': int(hits)})
            else:
                data.append({'label': f'{category} · {label}'[:120], 'value': -math.log10(fdr)})
        if not data:
            raise ValueError('没有 FDR≤0.05 且字段完整的富集条目。')
        data.sort(key=lambda item: -item['value'] if 'value' in item else item['adjustedPValue'])
        return finish({'chartType': 'bar' if chart_key == 'proteomics_go_kegg_bar' else 'enrichment_bubble', 'title': f'{source_name} 通路富集', 'subtitle': f"{source_name} {text(source.get('sourceVersion')) or '版本未知'} · FDR ≤ 0.05 · 展示前 {min(len(data), 30)} 条", 'yLabel': '−log10(FDR)', 'xLabel': '命中实体 / 通路实体', 'sizeLabel': '命中实体数', 'data': data[:30]})
    else:
        raise ValueError('未知 R 分析图表。')

    adjacent = neighbors(nodes, edges)
    if chart_key == 'ppi_degree':
        ranked = sorted(nodes, key=lambda key: (-len(adjacent[key]), key))
        data = [{'label': nodes[key]['label'], 'value': len(adjacent[key])} for key in ranked if adjacent[key]][:30]
        return finish({'chartType': 'bar', 'title': title, 'subtitle': subtitle + ' · 完整有效返回图的唯一邻居数；不证明因果', 'yLabel': 'Degree', 'data': data})
    if chart_key == 'gene_pathway_distribution':
        data = [{'label': node['label'], 'value': len(adjacent[key])} for key, node in nodes.items() if node['type'] == 'pathway']
        data.sort(key=lambda item: (-item['value'], item['label']))
        return finish({'chartType': 'bar', 'title': title, 'subtitle': subtitle, 'yLabel': '唯一关联基因数', 'data': data[:30]})

    ranked = sorted(nodes, key=lambda key: (-len(adjacent[key]), key))
    shown = set(ranked[:80])
    selected = sorted((edge for edge in edges if edge['source'] in shown and edge['target'] in shown), key=lambda edge: (-edge['score'], edge['source'], edge['target']))[:500]
    if not selected:
        raise ValueError('受绘图上限限制，展示子图没有有效边。')
    active = {endpoint for edge in selected for endpoint in (edge['source'], edge['target'])}
    displayed = neighbors(nodes, selected)
    data = [{**nodes[key], 'degree': len(displayed[key])} for key in ranked if key in active]
    return finish({'chartType': 'network', 'title': title, 'subtitle': f'{subtitle} · 展示 {len(data)}/{len(nodes)} 节点、{len(selected)}/{len(edges)} 边；节点大小为展示子图 degree', 'layout': 'circular' if chart_key == 'ppi_network' else 'layered', 'data': data, 'edges': selected})


def seal(payload):
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    payload = {**payload, 'inputSha256': hashlib.sha256(canonical.encode('utf-8')).hexdigest()}
    if len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')) > 1024 * 1024:
        raise ValueError('图表摘要超过 1 MiB 请求上限。')
    return payload
