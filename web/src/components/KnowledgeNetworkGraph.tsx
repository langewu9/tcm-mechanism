import { useMemo, useState } from "react";
import type { NetworkPharmacologyResult } from "../api/network";

type GraphNode = NetworkPharmacologyResult["network"]["nodes"][number] & {
  kind: string;
  x: number;
  y: number;
};
type GraphLink = NetworkPharmacologyResult["network"]["links"][number];

const ORDER = ["disease", "syndrome", "formula", "herb", "compound", "target", "pathway"];
const LABELS: Record<string, string> = {
  disease: "疾病", syndrome: "证候", formula: "方剂", herb: "中药", compound: "成分", target: "靶点", pathway: "通路", other: "其他",
};
const COLORS: Record<string, string> = {
  disease: "#9c2b22", syndrome: "#9c2b22", formula: "#7a3326", herb: "#c89b3c",
  compound: "#b7682f", target: "#8b5a2b", pathway: "#e0bd67", other: "#66736a",
};
const MAX_NODES_PER_KIND = 12;
const MAX_LINKS = 160;
const WIDTH = 1200;
const HEIGHT = 640;

function kindOf(type: string) {
  if (["gene", "protein", "target"].includes(type)) return "target";
  return ORDER.includes(type) ? type : "other";
}

function trimLabel(value: string, max = 10) {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

export function KnowledgeNetworkGraph({ network, knownTruncated = false, synthetic = false }: {
  network: NetworkPharmacologyResult["network"];
  knownTruncated?: boolean;
  synthetic?: boolean;
}) {
  const [visibleKinds, setVisibleKinds] = useState<Record<string, boolean>>(
    () => Object.fromEntries([...ORDER, "other"].map((kind) => [kind, true])),
  );
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedLink, setSelectedLink] = useState<GraphLink | null>(null);
  const [zoom, setZoom] = useState(1);

  const allNodes = useMemo(() => network.nodes.map((node) => ({ ...node, kind: kindOf(node.type) })), [network.nodes]);
  const { nodes, allKindCounts } = useMemo(() => {
    const grouped = new Map<string, typeof allNodes>();
    for (const node of allNodes) grouped.set(node.kind, [...(grouped.get(node.kind) ?? []), node]);
    const counts = Object.fromEntries([...ORDER, "other"].map((kind) => [kind, grouped.get(kind)?.length ?? 0]));
    const displayed = [...ORDER, "other"].flatMap((kind) =>
      visibleKinds[kind] ? (grouped.get(kind) ?? []).slice(0, MAX_NODES_PER_KIND) : [],
    );
    const positioned: GraphNode[] = displayed.map((node) => {
      const typeIndex = Math.max([...ORDER, "other"].indexOf(node.kind), 0);
      const siblings = displayed.filter((sibling) => sibling.kind === node.kind);
      const siblingIndex = siblings.findIndex((sibling) => sibling.id === node.id);
      const stageWidth = (WIDTH - 120) / Math.max(ORDER.length, 1);
      return { ...node, x: 60 + typeIndex * stageWidth, y: (HEIGHT / (siblings.length + 1)) * (siblingIndex + 1) };
    });
    return { nodes: positioned, allKindCounts: counts };
  }, [allNodes, visibleKinds]);

  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const visibleLinks = useMemo(() => network.links.filter((link) => nodeById.has(link.source) && nodeById.has(link.target)), [network.links, nodeById]);
  const displayedLinks = visibleLinks.slice(0, MAX_LINKS);
  const selectedNode = selectedNodeId ? nodeById.get(selectedNodeId) : null;
  const nodeRelations = selectedNode ? visibleLinks.filter((link) => link.source === selectedNode.id || link.target === selectedNode.id).slice(0, 30) : [];
  const nodeWasCapped = [...ORDER, "other"].some((kind) => visibleKinds[kind] && allKindCounts[kind] > MAX_NODES_PER_KIND);
  const resultTruncated = knownTruncated || nodeWasCapped || visibleLinks.length > MAX_LINKS;
  const zoomTransform = `translate(${WIDTH * (1 - zoom) / 2} ${HEIGHT * (1 - zoom) / 2}) scale(${zoom})`;

  function selectNode(id: string) {
    setSelectedNodeId(id);
    setSelectedLink(null);
  }

  return <section className="panel network-graph-panel" aria-labelledby="network-graph-title">
    <div className="case-list-heading"><div><p className="page-kicker">Interactive evidence network</p><h3 id="network-graph-title" className="section-title-sm">药理证据链路图</h3></div><span>{nodes.length}/{allNodes.length} 个节点 · {displayedLinks.length}/{visibleLinks.length} 条边</span></div>
    <p className="section-help">{synthetic ? "图中全部节点与连线为合成演示，不来自知识库，不代表真实关系。" : "图中节点和连线来自本次分析的本地知识目录。"}点击节点或连线查看标签及来源记录；图形不代表因果关系。</p>
    <div className="network-graph-toolbar" aria-label="网络图筛选和缩放">
      <div className="network-graph-filters">{[...ORDER, "other"].filter((kind) => allKindCounts[kind] > 0).map((kind) => <label key={kind}>
        <input type="checkbox" checked={visibleKinds[kind] ?? true} onChange={(event) => {
          setVisibleKinds((current) => ({ ...current, [kind]: event.target.checked }));
          setSelectedNodeId(null);
          setSelectedLink(null);
        }} />
        <span style={{ backgroundColor: COLORS[kind] }} />{LABELS[kind] ?? kind} {allKindCounts[kind]}
      </label>)}</div>
      <div className="network-graph-zoom"><button type="button" className="btn btn-secondary" onClick={() => setZoom((value) => Math.max(0.7, Math.round((value - 0.15) * 100) / 100))} aria-label="缩小网络图">−</button><span>{Math.round(zoom * 100)}%</span><button type="button" className="btn btn-secondary" onClick={() => setZoom((value) => Math.min(1.6, Math.round((value + 0.15) * 100) / 100))} aria-label="放大网络图">+</button><button type="button" className="btn btn-secondary" onClick={() => setZoom(1)}>重置</button></div>
    </div>
    {resultTruncated && <p className="notice-info">为保持图形可读，图中限制了每类节点和可见连线数量；下方的靶点证据表保留本次结果详情。</p>}
    {nodes.length ? <div className="network-graph-canvas">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="可筛选的中药—成分—靶点—通路—疾病关系网络">
        <rect width={WIDTH} height={HEIGHT} rx="12" fill="rgba(255,253,248,0.76)" />
        <g transform={zoomTransform}>
          {[...ORDER, "other"].filter((kind) => visibleKinds[kind] && (allKindCounts[kind] ?? 0) > 0).map((kind) => {
            const index = [...ORDER, "other"].indexOf(kind);
            const stageWidth = (WIDTH - 120) / Math.max(ORDER.length, 1);
            const x = 60 + index * stageWidth;
            return <g key={kind}><line x1={x} y1={44} x2={x} y2={HEIGHT - 28} stroke="#ded3c2" strokeDasharray="4 7" /><text x={x} y={25} textAnchor="middle" fill="#6d5b4c" fontSize="15" fontWeight="700">{LABELS[kind] ?? kind}</text></g>;
          })}
          {displayedLinks.map((link, index) => {
            const source = nodeById.get(link.source);
            const target = nodeById.get(link.target);
            if (!source || !target) return null;
            const middle = (source.x + target.x) / 2;
            const selected = selectedLink === link;
            return <path key={`${link.source}-${link.target}-${link.sourceRecordId}-${index}`} d={`M ${source.x} ${source.y} C ${middle} ${source.y}, ${middle} ${target.y}, ${target.x} ${target.y}`} fill="none" stroke={selected ? "#9c2b22" : "#788478"} strokeOpacity={selected ? 0.9 : 0.35} strokeWidth={selected ? 3 : 1.4} tabIndex={0} role="button" aria-label={`${source.label} ${link.relation} ${target.label}`} onClick={() => { setSelectedLink(link); setSelectedNodeId(null); }} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedLink(link); setSelectedNodeId(null); } }}>
              <title>{`${source.label} —${link.relation}→ ${target.label} · ${link.sourceSlug} · ${link.sourceRecordId}`}</title>
            </path>;
          })}
          {nodes.map((node) => <g key={node.id} transform={`translate(${node.x} ${node.y})`} className="network-graph-node" role="button" tabIndex={0} aria-pressed={selectedNodeId === node.id} aria-label={`${LABELS[node.kind] ?? node.kind}: ${node.label}`} onClick={() => selectNode(node.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectNode(node.id); } }}>
            <circle r={selectedNodeId === node.id ? 29 : 22} fill={COLORS[node.kind] ?? COLORS.other} stroke={selectedNodeId === node.id ? "#2b1711" : "white"} strokeWidth={selectedNodeId === node.id ? 3 : 1.5} opacity="0.96" />
            <text y="4" textAnchor="middle" fontSize="10.5" fill={node.kind === "pathway" ? "#2b1711" : "white"} fontWeight="800">{trimLabel(node.label)}</text>
            <title>{`${LABELS[node.kind] ?? node.kind}: ${node.label} (${node.id})`}</title>
          </g>)}
        </g>
      </svg>
    </div> : <div className="panel empty-state"><strong>当前没有可显示的网络关系</strong><p>请缩小查询范围或确认本地来源目录是否已导入关系证据。</p></div>}
    {selectedNode && <div className="network-graph-selection"><strong>{LABELS[selectedNode.kind] ?? selectedNode.kind}：{selectedNode.label}</strong><small>{selectedNode.id} · {nodeRelations.length} 条可见邻接关系</small>
      {nodeRelations.length > 0 && <ul className="proteomics-pathways">{nodeRelations.map((link, index) => <li key={`${link.source}-${link.target}-${link.sourceRecordId}-${index}`}><strong>{nodeById.get(link.source)?.label} —{link.relation}→ {nodeById.get(link.target)?.label}</strong><span>{link.sourceSlug} · 记录 {link.sourceRecordId}</span></li>)}</ul>}
    </div>}
    {selectedLink && <div className="network-graph-selection"><strong>{nodeById.get(selectedLink.source)?.label} —{selectedLink.relation}→ {nodeById.get(selectedLink.target)?.label}</strong><small>{selectedLink.sourceSlug} · 来源记录 {selectedLink.sourceRecordId}</small></div>}
  </section>;
}
