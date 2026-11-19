import { useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type WheelEvent as ReactWheelEvent } from "react";
import { Download, LocateFixed, Maximize2, Minus, Plus, RotateCcw } from "lucide-react";
import type { CaseGraphEdge, CaseGraphNode, CaseKnowledgeGraph } from "../api/caseStatistics";
import { downloadText, encodeCsv } from "../utils/downloads";

type GraphView = "case" | "entity";
type PositionedNode = CaseGraphNode & { x: number; y: number };
type GraphPoint = { x: number; y: number };
type GraphPointer = {
  pointerId: number;
  mode: "pan" | "node";
  nodeId?: string;
  startClient: GraphPoint;
  startPoint: GraphPoint;
  startNode?: GraphPoint;
  startPan: GraphPoint;
  moved: boolean;
};
type NodeClick = { id: string; at: number };

const ORDER: Record<string, number> = { case: 0, visit: 1, western_diagnosis: 2, tcm_diagnosis: 2, syndrome: 2, treatment: 2, tongue: 2, pulse: 2, prescription: 3, formula: 4, herb: 4 };
const CANVAS_WIDTH = 1500;
const CANVAS_HEIGHT = 1100;
const NODE_RADIUS = 50;
const COLOR: Record<string, string> = {
  case: "#9b4b37", visit: "#bd8146", western_diagnosis: "#72859a", tcm_diagnosis: "#77855c",
  syndrome: "#9b8651", treatment: "#a16e55", tongue: "#6f9690", pulse: "#708b9b",
  prescription: "#9d7957", formula: "#8f7692", herb: "#bd7652",
};

function valueText(value: string | number) { return String(value); }
function captionLines(value: string) {
  const characters = Array.from(value.replace(/\s+/g, " ").replace(/[，,。；;、\s]+$/u, "").trim());
  const visible = characters.length > 8 ? [...characters.slice(0, 7), "…"] : characters;
  return visible.length > 4 ? [visible.slice(0, 4).join(""), visible.slice(4).join("")] : [visible.join("")];
}
function esc(value: unknown) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function limitView(nodes: CaseGraphNode[], edges: CaseGraphEdge[], maxNodes: number, maxEdges: number, anchorId: string) {
  const orderedEdges = [...edges].sort((a, b) =>
    Number(b.source === anchorId || b.target === anchorId) - Number(a.source === anchorId || a.target === anchorId),
  );
  const allowed = new Set<string>(nodes.some(node => node.id === anchorId) ? [anchorId] : []);
  const visibleEdges: CaseGraphEdge[] = [];
  for (const edge of orderedEdges) {
    if (visibleEdges.length >= maxEdges) break;
    const additions = Number(!allowed.has(edge.source)) + Number(!allowed.has(edge.target));
    if (allowed.size + additions > maxNodes) continue;
    allowed.add(edge.source);
    allowed.add(edge.target);
    visibleEdges.push(edge);
  }
  const connected = new Set(visibleEdges.flatMap(edge => [edge.source, edge.target]));
  const visibleNodes = nodes.filter(node => allowed.has(node.id) && (connected.has(node.id) || node.id === anchorId)).slice(0, maxNodes);
  return {
    nodes: visibleNodes,
    edges: visibleEdges,
    omittedNodes: Math.max(0, nodes.length - visibleNodes.length),
    omittedEdges: Math.max(0, edges.length - visibleEdges.length),
  };
}

function caseNeighborhood(graph: CaseKnowledgeGraph, caseId: string) {
  const visits = graph.edges.filter(edge => edge.type === "has_visit" && edge.source === caseId).map(edge => edge.target);
  const visitSet = new Set(visits);
  const prescriptionIds = new Set(graph.edges.filter(edge => edge.type === "has_prescription" && visitSet.has(edge.source)).map(edge => edge.target));
  const edges = graph.edges.filter(edge =>
    (edge.type === "has_visit" && edge.source === caseId) ||
    (visitSet.has(edge.source) && edge.type !== "has_visit") ||
    (prescriptionIds.has(edge.source) && (edge.type === "mentions_formula" || edge.type === "contains_herb"))
  );
  const ids = new Set([caseId, ...visits, ...edges.flatMap(edge => [edge.source, edge.target])]);
  return limitView(graph.nodes.filter(node => ids.has(node.id)), edges, 110, 220, caseId);
}

function entityNeighborhood(graph: CaseKnowledgeGraph, entityId: string) {
  const edges = graph.edges.filter(edge => edge.source === entityId || edge.target === entityId);
  const ids = new Set([entityId, ...edges.flatMap(edge => [edge.source, edge.target])]);
  return limitView(graph.nodes.filter(node => ids.has(node.id)), edges, 110, 220, entityId);
}

function layoutGraph(nodes: CaseGraphNode[], edges: CaseGraphEdge[], anchorId: string) {
  const anchor = nodes.find(node => node.id === anchorId) ?? nodes[0];
  const neighbors = new Map<string, Set<string>>();
  for (const node of nodes) neighbors.set(node.id, new Set());
  for (const edge of edges) {
    neighbors.get(edge.source)?.add(edge.target);
    neighbors.get(edge.target)?.add(edge.source);
  }
  const depth = new Map<string, number>();
  if (anchor) {
    depth.set(anchor.id, 0);
    const queue = [anchor.id];
    while (queue.length) {
      const current = queue.shift()!;
      for (const neighbor of neighbors.get(current) ?? []) {
        if (depth.has(neighbor)) continue;
        depth.set(neighbor, (depth.get(current) ?? 0) + 1);
        queue.push(neighbor);
      }
    }
  }
  const grouped = new Map<number, CaseGraphNode[]>();
  for (const node of nodes) {
    const level = depth.get(node.id) ?? 1;
    grouped.set(level, [...(grouped.get(level) ?? []), node]);
  }
  const positioned: PositionedNode[] = [];
  const center = { x: CANVAS_WIDTH / 2, y: CANVAS_HEIGHT / 2 };
  for (const [level, group] of grouped) {
    group.sort((a, b) => (ORDER[a.type] ?? 3) - (ORDER[b.type] ?? 3) || a.label.localeCompare(b.label, "zh"));
    if (level === 0) {
      group.forEach(node => positioned.push({ ...node, ...center }));
      continue;
    }
    const radius = Math.min(500, 160 + level * 120);
    const phase = (level % 2) * Math.PI / Math.max(group.length, 1);
    group.forEach((node, index) => {
      const angle = phase + (index / Math.max(group.length, 1)) * Math.PI * 2;
      positioned.push({
        ...node,
        x: center.x + Math.cos(angle) * radius,
        y: center.y + Math.sin(angle) * radius,
      });
    });
  }
  // Keep enough room for names and a compact property caption inside each node.
  const preferred = new Map(positioned.map(node => [node.id, { x: node.x, y: node.y }]));
  for (let iteration = 0; iteration < 120; iteration++) {
    for (let first = 0; first < positioned.length; first++) {
      const a = positioned[first];
      for (let second = first + 1; second < positioned.length; second++) {
        const b = positioned[second];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const distance = Math.hypot(dx, dy);
        if (distance >= 118) continue;
        const angle = (first + second) * 2.39996;
        const ux = distance > 0.01 ? dx / distance : Math.cos(angle);
        const uy = distance > 0.01 ? dy / distance : Math.sin(angle);
        const push = (118 - distance) * 0.5;
        if (a.id !== anchor?.id) { a.x -= ux * push; a.y -= uy * push; }
        if (b.id !== anchor?.id) { b.x += ux * push; b.y += uy * push; }
      }
    }
    for (const node of positioned) {
      if (node.id === anchor?.id) continue;
      const origin = preferred.get(node.id)!;
      node.x = Math.max(66, Math.min(CANVAS_WIDTH - 66, node.x + (origin.x - node.x) * 0.005));
      node.y = Math.max(66, Math.min(CANVAS_HEIGHT - 66, node.y + (origin.y - node.y) * 0.005));
    }
  }
  const positions = new Map(positioned.map(node => [node.id, node]));
  return { nodes: positioned, edges: edges.filter(edge => positions.has(edge.source) && positions.has(edge.target)) };
}

export function CaseKnowledgeGraphView({ graph, taskId }: { graph: CaseKnowledgeGraph; taskId: number }) {
  const cases = useMemo(() => graph.nodes.filter(node => node.type === "case"), [graph]);
  const caseLabels = useMemo(() => new Map(cases.map((node, index) => [node.id, `病例${index + 1}`])), [cases]);
  const searchable = useMemo(() => graph.nodes.filter(node => node.type !== "case"), [graph]);
  const [view, setView] = useState<GraphView>("case");
  const [caseId, setCaseId] = useState(cases[0]?.id ?? "");
  const [focusId, setFocusId] = useState(searchable[0]?.id ?? "");
  const [query, setQuery] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [selectedEdgeId, setSelectedEdgeId] = useState("");
  const [table, setTable] = useState<"entities" | "relationships" | "sources">("entities");
  const [expanded, setExpanded] = useState(false);
  const [nodePositions, setNodePositions] = useState<Record<string, GraphPoint>>({});
  const [pan, setPan] = useState<GraphPoint>({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [draggingNodeId, setDraggingNodeId] = useState("");
  const svgRef = useRef<SVGSVGElement>(null);
  const pointerRef = useRef<GraphPointer | null>(null);
  const nodeClickRef = useRef<NodeClick | null>(null);

  const filteredEntities = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    const matches = searchable.filter(node => !needle || `${node.typeLabel} ${node.label}`.toLocaleLowerCase().includes(needle));
    const visible = matches.slice(0, 60);
    const focused = searchable.find(node => node.id === focusId);
    if (focused && !visible.some(node => node.id === focused.id)) visible.push(focused);
    return visible;
  }, [searchable, query, focusId]);
  const displayed = useMemo(() => view === "case" ? caseNeighborhood(graph, caseId) : entityNeighborhood(graph, focusId), [graph, view, caseId, focusId]);
  const anchorId = view === "case" ? caseId : focusId;
  const layout = useMemo(() => layoutGraph(displayed.nodes, displayed.edges, anchorId), [displayed, anchorId]);
  const positionedNodes = layout.nodes.map(node => ({ ...node, ...(nodePositions[node.id] ?? {}) }));
  const positionById = new Map(positionedNodes.map(node => [node.id, node]));
  const selectedNode = displayed.nodes.find(node => node.id === selectedNodeId) ?? displayed.nodes.find(node => node.id === anchorId) ?? displayed.nodes[0];
  const selectedEdge = graph.edges.find(edge => edge.id === selectedEdgeId);
  const sourceRows = displayed.edges.flatMap(edge => edge.evidence.map(evidence => ({ edge, evidence })));
  const selectedHerbRelations = selectedNode?.type === "herb"
    ? graph.edges.filter(edge => edge.type === "contains_herb" && edge.target === selectedNode.id)
    : [];
  const herbDoseCounts = new Map<string, number>();
  const herbPreparationCounts = new Map<string, number>();
  for (const edge of selectedHerbRelations) {
    const dose = edge.properties.dose;
    const preparation = edge.properties.preparation;
    if (dose) herbDoseCounts.set(String(dose), (herbDoseCounts.get(String(dose)) ?? 0) + 1);
    if (preparation) herbPreparationCounts.set(String(preparation), (herbPreparationCounts.get(String(preparation)) ?? 0) + 1);
  }
  const commonHerbDoses = [...herbDoseCounts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh")).slice(0, 3);
  const commonHerbPreparations = [...herbPreparationCounts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh")).slice(0, 3);
  const canvasWidth = CANVAS_WIDTH;
  const canvasHeight = CANVAS_HEIGHT;

  function nodeCaption(node: CaseGraphNode) {
    if (node.type === "case") return caseLabels.get(node.id) ?? "病例";
    if (node.type === "visit") return `第${node.properties["诊次序号"] ?? "?"}诊`;
    if (node.type === "prescription") {
      const visitId = graph.edges.find(edge => edge.type === "has_prescription" && edge.target === node.id)?.source;
      const visit = graph.nodes.find(item => item.id === visitId);
      const row = node.evidence[0]?.row;
      const visitNumber = visit?.properties["诊次序号"];
      return visitNumber ? `第${visitNumber}诊·行${row ?? "?"}` : node.label;
    }
    return node.label;
  }

  function selectNode(node: CaseGraphNode) {
    setSelectedNodeId(node.id);
    setSelectedEdgeId("");
  }
  function selectOrExpandNode(node: CaseGraphNode) {
    const now = Date.now();
    const previous = nodeClickRef.current;
    if (previous?.id === node.id && now - previous.at < 360) {
      nodeClickRef.current = null;
      expandNode(node);
      return;
    }
    nodeClickRef.current = { id: node.id, at: now };
    selectNode(node);
  }
  function pointInSvg(clientX: number, clientY: number) {
    const svg = svgRef.current;
    const matrix = svg?.getScreenCTM();
    if (!svg || !matrix) return { x: 0, y: 0 };
    const point = svg.createSVGPoint();
    point.x = clientX;
    point.y = clientY;
    return point.matrixTransform(matrix.inverse());
  }
  function beginPan(event: ReactPointerEvent<SVGSVGElement>) {
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest("[data-graph-node], [data-graph-edge]")) return;
    const point = pointInSvg(event.clientX, event.clientY);
    pointerRef.current = {
      pointerId: event.pointerId, mode: "pan",
      startClient: { x: event.clientX, y: event.clientY },
      startPoint: point, startPan: pan, moved: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function beginNodeDrag(node: PositionedNode, event: ReactPointerEvent<SVGGElement>) {
    event.preventDefault();
    event.stopPropagation();
    const point = pointInSvg(event.clientX, event.clientY);
    pointerRef.current = {
      pointerId: event.pointerId, mode: "node", nodeId: node.id,
      startClient: { x: event.clientX, y: event.clientY },
      startPoint: point, startNode: { x: node.x, y: node.y },
      startPan: pan, moved: false,
    };
    setDraggingNodeId(node.id);
    svgRef.current?.setPointerCapture(event.pointerId);
  }
  function movePointer(event: ReactPointerEvent<SVGSVGElement>) {
    const pointer = pointerRef.current;
    if (!pointer || pointer.pointerId !== event.pointerId) return;
    const point = pointInSvg(event.clientX, event.clientY);
    const dx = point.x - pointer.startPoint.x;
    const dy = point.y - pointer.startPoint.y;
    if (!pointer.moved && Math.hypot(event.clientX - pointer.startClient.x, event.clientY - pointer.startClient.y) >= 4) pointer.moved = true;
    if (pointer.mode === "pan") {
      if (pointer.moved) setPan({ x: pointer.startPan.x + dx, y: pointer.startPan.y + dy });
      return;
    }
    if (!pointer.nodeId || !pointer.startNode || !pointer.moved) return;
    setNodePositions(current => ({
      ...current,
      [pointer.nodeId!]: {
        x: pointer.startNode!.x + dx / zoom,
        y: pointer.startNode!.y + dy / zoom,
      },
    }));
  }
  function finishPointer(event: ReactPointerEvent<SVGSVGElement>) {
    const pointer = pointerRef.current;
    if (!pointer || pointer.pointerId !== event.pointerId) return;
    if (pointer.mode === "node" && pointer.nodeId && !pointer.moved) {
      const node = displayed.nodes.find(item => item.id === pointer.nodeId);
      if (node) selectOrExpandNode(node);
    }
    pointerRef.current = null;
    setDraggingNodeId("");
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }
  function zoomAround(nextZoom: number, point: GraphPoint) {
    const bounded = Math.min(2.5, Math.max(0.45, nextZoom));
    const world = { x: (point.x - pan.x) / zoom, y: (point.y - pan.y) / zoom };
    setPan({ x: point.x - world.x * bounded, y: point.y - world.y * bounded });
    setZoom(bounded);
  }
  function zoomBy(amount: number) {
    zoomAround(zoom + amount, { x: canvasWidth / 2, y: canvasHeight / 2 });
  }
  function handleWheel(event: ReactWheelEvent<SVGSVGElement>) {
    event.preventDefault();
    const point = pointInSvg(event.clientX, event.clientY);
    zoomAround(zoom * (event.deltaY < 0 ? 1.12 : 0.89), point);
  }
  function expandNode(node: CaseGraphNode) {
    if (node.type === "case") {
      setView("case");
      setCaseId(node.id);
    } else {
      setView("entity");
      setFocusId(node.id);
    }
    setSelectedNodeId(node.id);
    setSelectedEdgeId("");
    setNodePositions({});
    setPan({ x: 0, y: 0 });
    setZoom(1);
  }
  function resetGraphView() {
    setNodePositions({});
    setPan({ x: 0, y: 0 });
    setZoom(1);
  }
  function exportGraph() {
    const data = { scope: view === "case" ? "single_case" : "entity_neighborhood", nodes: displayed.nodes.map(({ id, type, typeLabel, label, properties, evidence }) => ({ id, type, typeLabel, label, properties, evidence })), edges: displayed.edges };
    downloadText(`case-${taskId}-knowledge-graph.json`, JSON.stringify(data, null, 2), "application/json;charset=utf-8");
  }
  function exportEntities() {
    downloadText(`case-${taskId}-knowledge-entities.csv`, encodeCsv(["实体类型", "名称", "属性", "来源"], displayed.nodes.map(node => [node.typeLabel, node.label, JSON.stringify(node.properties), node.evidence.map(item => `${item.sheet}!${item.row}行 ${item.field}`).join("；")])), "text/csv;charset=utf-8");
  }
  function exportRelationships() {
    downloadText(`case-${taskId}-knowledge-relationships.csv`, encodeCsv(["起点", "关系", "终点", "关系属性", "来源"], displayed.edges.map(edge => [graph.nodes.find(node => node.id === edge.source)?.label ?? edge.source, edge.label, graph.nodes.find(node => node.id === edge.target)?.label ?? edge.target, JSON.stringify(edge.properties), edge.evidence.map(item => `${item.sheet}!${item.row}行 ${item.field}`).join("；")])), "text/csv;charset=utf-8");
  }
  function exportSvg() {
    if (!svgRef.current) return;
    const source = new XMLSerializer().serializeToString(svgRef.current);
    downloadText(`case-${taskId}-knowledge-graph.svg`, `<?xml version="1.0" encoding="UTF-8"?>\n${source}`, "image/svg+xml;charset=utf-8");
  }
  function exportHtml() {
    if (!svgRef.current) return;
    const svg = new XMLSerializer().serializeToString(svgRef.current);
    const entityRows = displayed.nodes.map(node => `<tr><td>${esc(node.typeLabel)}</td><td>${esc(node.label)}</td><td>${esc(JSON.stringify(node.properties))}</td><td>${esc(node.evidence.map(item => `${item.sheet} 第 ${item.row} 行 · ${item.field}`).join("；"))}</td></tr>`).join("");
    const edgeRows = displayed.edges.map(edge => `<tr><td>${esc(graph.nodes.find(node => node.id === edge.source)?.label ?? edge.source)}</td><td>${esc(edge.label)}</td><td>${esc(graph.nodes.find(node => node.id === edge.target)?.label ?? edge.target)}</td><td>${esc(JSON.stringify(edge.properties))}</td><td>${esc(edge.evidence.map(item => `${item.sheet} 第 ${item.row} 行 · ${item.field}${item.value ? ` · ${item.value}` : ""}`).join("；"))}</td></tr>`).join("");
    const title = view === "case" ? cases.find(node => node.id === caseId)?.label ?? "医案知识图谱" : searchable.find(node => node.id === focusId)?.label ?? "实体关系";
    const html = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>${esc(title)} · 医案知识图谱</title><style>body{font:16px/1.65 system-ui,"Noto Sans CJK SC",sans-serif;color:#37271e;background:#f7f1e8;margin:0;padding:28px}main{max-width:1300px;margin:auto;background:#fffdfa;padding:24px;border:1px solid #c9a77e}h1{font-size:24px}.note{color:#6c5a49}.graph{overflow:auto;background:white;border:1px solid #dfcdb6;padding:12px}.graph svg{min-width:900px;width:100%;height:auto}table{border-collapse:collapse;width:100%;margin:16px 0;background:white}th,td{border:1px solid #e5ddd4;text-align:left;padding:8px;overflow-wrap:anywhere}th{background:#a87752;color:white}h2{margin-top:30px}</style><main><h1>${esc(title)} · 医案知识图谱</h1><p class="note">实体和关系根据工作簿中明确填写的结构化字段生成；来源定位到工作表行号。该图表示记录关系，不表示因果或疗效。</p><div class="graph">${svg}</div><h2>实体与属性</h2><table><thead><tr><th>类型</th><th>实体</th><th>属性</th><th>来源</th></tr></thead><tbody>${entityRows}</tbody></table><h2>关系与来源</h2><table><thead><tr><th>起点</th><th>关系</th><th>终点</th><th>属性</th><th>来源</th></tr></thead><tbody>${edgeRows}</tbody></table></main></html>`;
    downloadText(`case-${taskId}-knowledge-graph.html`, html, "text/html;charset=utf-8");
  }

  if (!graph.nodes.length || !cases.length) return <div className="case-visualization-empty"><strong>当前数据没有可展示的图谱实体</strong><p>需要病例编号和结构化诊次字段。</p></div>;

  return <section className={`case-knowledge-graph${expanded ? " is-expanded" : ""}`} aria-label="医案知识图谱">
    <header className="case-knowledge-heading"><div><h4>医案知识图谱</h4><p>按原表结构展示实体、关系、属性和来源行。每条边都可回到表格中的具体记录。</p></div><div className="case-knowledge-counts"><span>{graph.caseCount} 个病例</span><span>{graph.includedVisitCount}/{graph.sourceVisitCount} 条诊次</span><span>{graph.entityCount} 个实体</span><span>{graph.relationshipCount} 条关系</span></div></header>
    <div className="case-knowledge-tools">
      <div className="case-knowledge-switch" role="group" aria-label="图谱范围"><button type="button" aria-pressed={view === "case"} onClick={() => { setView("case"); setSelectedEdgeId(""); }}>单个病例</button><button type="button" aria-pressed={view === "entity"} onClick={() => { setView("entity"); setSelectedEdgeId(""); }}>实体关系</button></div>
      {view === "case" ? <label className="form-label">选择病例<select className="field" value={caseId} onChange={event => { setCaseId(event.target.value); setSelectedNodeId(""); setSelectedEdgeId(""); }}>{cases.map(node => <option key={node.id} value={node.id}>{caseLabels.get(node.id) ?? "病例"}</option>)}</select></label> : <div className="case-knowledge-entity-search"><label className="form-label">查找实体<input className="field" value={query} onChange={event => setQuery(event.target.value)} placeholder="输入病名、证型、治法或药物" /></label><label className="form-label">选择实体<select className="field" value={focusId} onChange={event => { setFocusId(event.target.value); setSelectedNodeId(event.target.value); setSelectedEdgeId(""); }}>{filteredEntities.map(node => <option key={node.id} value={node.id}>{node.typeLabel} · {node.label}</option>)}</select></label></div>}
      <div className="case-knowledge-downloads"><button className="btn btn-secondary" type="button" onClick={exportSvg}><Download size={15}/>SVG</button><button className="btn btn-secondary" type="button" onClick={exportGraph}><Download size={15}/>JSON</button><button className="btn btn-secondary" type="button" onClick={exportEntities}><Download size={15}/>实体 CSV</button><button className="btn btn-secondary" type="button" onClick={exportRelationships}><Download size={15}/>关系 CSV</button><button className="btn btn-secondary" type="button" onClick={exportHtml}><Download size={15}/>HTML 报告</button></div>
    </div>
    <p className="case-knowledge-coverage">知识图谱包含本工作簿的全部诊次；统计图选择“首诊病例组”只影响统计图。本图只把原表显式记录的关系连起来，不从共现推断治疗或因果关系。{graph.omittedVisitCount > 0 && ` 图谱达到安全上限，另有 ${graph.omittedVisitCount} 条诊次未纳入。`}</p>
    <div className="case-knowledge-legend" aria-label="实体类型图例">{Object.entries(ENTITY_LABELS_FOR_UI).map(([type, label]) => <span key={type}><i style={{ background: COLOR[type] ?? "#9d7957" }}/>{label}</span>)}</div>
    <p className="case-knowledge-interaction-hint">节点显示名称或关键属性，长内容以省略号收起；单击查看完整属性及相邻关系，双击展开。可拖动节点、平移画布和滚轮缩放。</p>
    <div className="case-knowledge-workbench">
      <div className="case-knowledge-canvas-shell">
        <div className="case-knowledge-canvas-actions" role="toolbar" aria-label="图谱缩放和定位">
          <button type="button" className="btn btn-secondary" onClick={() => zoomBy(-0.15)} aria-label="缩小图谱"><Minus size={15}/></button>
          <span>{Math.round(zoom * 100)}%</span>
          <button type="button" className="btn btn-secondary" onClick={() => zoomBy(0.15)} aria-label="放大图谱"><Plus size={15}/></button>
          <button type="button" className="btn btn-secondary" onClick={resetGraphView} aria-label="重置图谱位置"><LocateFixed size={15}/>复位</button>
        </div>
        <div className="case-knowledge-canvas-scroll">
          <svg ref={svgRef} className="case-knowledge-canvas" viewBox={"0 0 " + canvasWidth + " " + canvasHeight} role="img" aria-label={view === "case" ? "单个病例的诊次和结构化实体关系图" : "所选实体的一跳关系网络"} onPointerDown={beginPan} onPointerMove={movePointer} onPointerUp={finishPointer} onPointerCancel={finishPointer} onWheel={handleWheel}>
            <defs>
              <marker id="case-graph-arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#b8a99a"/></marker>
              <pattern id="case-graph-dots" width="18" height="18" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="0.7" fill="#cfbaa3"/></pattern>
            </defs>
            <rect className="case-knowledge-background" width={canvasWidth} height={canvasHeight} fill="url(#case-graph-dots)"/>
            <g transform={"translate(" + pan.x + " " + pan.y + ") scale(" + zoom + ")"}>
              {layout.edges.map(edge => {
                const from = positionById.get(edge.source);
                const to = positionById.get(edge.target);
                if (!from || !to) return null;
                const selected = selectedEdgeId === edge.id;
                const muted = selectedNodeId && edge.source !== selectedNodeId && edge.target !== selectedNodeId;
                const focusIdForLabels = selectedNodeId || anchorId;
                const focusedEdges = layout.edges.filter(item => item.source === focusIdForLabels || item.target === focusIdForLabels);
                const showLabel = selected || (focusedEdges.length <= 12 && (edge.source === focusIdForLabels || edge.target === focusIdForLabels));
                const distance = Math.hypot(to.x - from.x, to.y - from.y) || 1;
                const ux = (to.x - from.x) / distance;
                const uy = (to.y - from.y) / distance;
                const inset = Math.min(NODE_RADIUS + 5, distance / 2);
                return <g key={edge.id} data-graph-edge className={selected ? "case-knowledge-edge is-selected" : "case-knowledge-edge"} role="button" tabIndex={0} aria-label={from.label + "，" + edge.label + "，" + to.label} onClick={() => { setSelectedEdgeId(edge.id); setSelectedNodeId(""); }} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedEdgeId(edge.id); setSelectedNodeId(""); } }}>
                  <title>{from.label + " — " + edge.label + " → " + to.label}</title>
                  <line x1={from.x + ux * inset} y1={from.y + uy * inset} x2={to.x - ux * inset} y2={to.y - uy * inset} markerEnd="url(#case-graph-arrow)" style={{ opacity: muted ? 0.12 : undefined }}/>
                  <line className="case-knowledge-edge-hit" x1={from.x} y1={from.y} x2={to.x} y2={to.y}/>
                  {showLabel && <text className="case-knowledge-edge-label" x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 6} textAnchor="middle">{edge.label}</text>}
                </g>;
              })}
              {positionedNodes.map(node => {
                const selected = selectedNodeId === node.id || (!selectedNodeId && !selectedEdgeId && selectedNode?.id === node.id);
                const muted = selectedNodeId && node.id !== selectedNodeId && !displayed.edges.some(edge => (edge.source === selectedNodeId && edge.target === node.id) || (edge.target === selectedNodeId && edge.source === node.id));
                const nodeLabel = nodeCaption(node);
                const lines = captionLines(nodeLabel);
                const typeLabel = ENTITY_LABELS_FOR_UI[node.type] ?? node.typeLabel;
                const sourceCount = node.evidence.length;
                return <g key={node.id} data-graph-node className={"case-knowledge-node" + (selected ? " is-selected" : "") + (draggingNodeId === node.id ? " is-dragging" : "")} role="button" tabIndex={0} aria-pressed={selected} aria-label={typeLabel + "：" + nodeLabel} onPointerDown={event => beginNodeDrag(node, event)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectNode(node); } }}>
                  <title>{typeLabel + "：" + node.label + "；单击查看完整属性，双击展开关系"}</title>
                  <circle cx={node.x} cy={node.y} r={selected ? NODE_RADIUS + 7 : NODE_RADIUS} fill={COLOR[node.type] ?? "#9d7957"} style={{ opacity: muted ? 0.35 : 0.97 }}/>
                  <text className="case-knowledge-node-type" x={node.x} y={node.y - 27} textAnchor="middle">{typeLabel}</text>
                  <text className="case-knowledge-node-caption" textAnchor="middle">{lines.map((line, index) => <tspan key={index} x={node.x} y={node.y + (lines.length === 1 ? 9 : 0 + index * 17)}>{line}</tspan>)}</text>
                  {selected && sourceCount > 1 && <text className="case-knowledge-node-count" x={node.x} y={node.y + 36} textAnchor="middle">{node.type === "herb" ? `出现于 ${sourceCount} 诊次` : `${sourceCount} 条记录`}</text>}
                </g>;
              })}
            </g>
          </svg>
        </div>
      </div>
      <section className="case-knowledge-detail" aria-live="polite">
        <h5>{selectedEdge ? "关系属性" : "实体属性"}</h5>
        {selectedEdge ? <>
          <p className="case-knowledge-path"><strong>{graph.nodes.find(node => node.id === selectedEdge.source)?.label}</strong><span>{selectedEdge.label}</span><strong>{graph.nodes.find(node => node.id === selectedEdge.target)?.label}</strong></p>
          <dl><div><dt>关系类型</dt><dd>{selectedEdge.type}</dd></div>{Object.entries(selectedEdge.properties).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{valueText(value)}</dd></div>)}</dl>
          <Evidence items={selectedEdge.evidence}/>
        </> : selectedNode ? <>
          <p className="case-knowledge-path"><span className="case-knowledge-type">{selectedNode.typeLabel}</span>{selectedNode.type === "case" && <strong>{caseLabels.get(selectedNode.id) ?? "病例"}</strong>}</p>
          <dl><div><dt>名称</dt><dd>{selectedNode.label}</dd></div>{Object.entries(selectedNode.properties).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{valueText(value)}</dd></div>)}</dl>
          {selectedNode.type === "herb" && <section className="case-knowledge-attribute-summary" aria-label="药物出现与剂量摘要">
            <strong>全量图谱中的记录属性</strong>
            <dl>
              <div><dt>出现诊次</dt><dd>{new Set(selectedHerbRelations.map(edge => edge.source)).size}</dd></div>
              <div><dt>有剂量记录</dt><dd>{selectedHerbRelations.filter(edge => edge.properties.dose).length}/{selectedHerbRelations.length}</dd></div>
              {commonHerbDoses.length > 0 && <div><dt>常见剂量</dt><dd>{commonHerbDoses.map(([dose, count]) => `${dose}（${count}次）`).join("、")}</dd></div>}
              {commonHerbPreparations.length > 0 && <div><dt>炮制/用法</dt><dd>{commonHerbPreparations.map(([preparation, count]) => `${preparation}（${count}次）`).join("、")}</dd></div>}
            </dl>
          </section>}
          <Evidence items={selectedNode.evidence}/>
          <button type="button" className="btn btn-secondary case-knowledge-expand-node" onClick={() => expandNode(selectedNode)}>展开相关实体</button>
        </> : <p>选择图中的实体或连线，查看属性与来源。</p>}
      </section>
    </div>
    {(displayed.omittedNodes > 0 || displayed.omittedEdges > 0) && <p className="case-knowledge-coverage">为保持画面清晰，当前视图最多显示 110 个实体和 220 条关系；本次视图另有 {displayed.omittedNodes} 个实体、{displayed.omittedEdges} 条关系未显示，可双击可见节点逐层探索。</p>}
    <details className="case-knowledge-tables"><summary>实体、关系与来源清单</summary><div className="case-knowledge-switch" role="group" aria-label="图谱明细类型"><button type="button" aria-pressed={table === "entities"} onClick={() => setTable("entities")}>实体 {displayed.nodes.length}</button><button type="button" aria-pressed={table === "relationships"} onClick={() => setTable("relationships")}>关系 {displayed.edges.length}</button><button type="button" aria-pressed={table === "sources"} onClick={() => setTable("sources")}>来源 {sourceRows.length}</button></div>
      <div className="table-scroll">{table === "entities" ? <table className="data-table"><thead><tr><th>实体类型</th><th>名称</th><th>属性</th><th>来源</th></tr></thead><tbody>{displayed.nodes.map(node => <tr key={node.id} onClick={() => selectNode(node)}><td>{node.typeLabel}</td><td>{node.label}</td><td>{Object.entries(node.properties).map(([key, value]) => `${key}：${value}`).join("；") || "—"}</td><td>{node.evidence.map(item => `${item.sheet} ${item.row}行 · ${item.field}`).join("；") || "—"}</td></tr>)}</tbody></table> : table === "relationships" ? <table className="data-table"><thead><tr><th>起点</th><th>关系</th><th>终点</th><th>属性</th><th>来源</th></tr></thead><tbody>{displayed.edges.map(edge => <tr key={edge.id} onClick={() => { setSelectedEdgeId(edge.id); setSelectedNodeId(""); }}><td>{graph.nodes.find(node => node.id === edge.source)?.label}</td><td>{edge.label}</td><td>{graph.nodes.find(node => node.id === edge.target)?.label}</td><td>{Object.entries(edge.properties).map(([key, value]) => `${key}：${value}`).join("；") || "—"}</td><td>{edge.evidence.map(item => `${item.sheet} ${item.row}行 · ${item.field}`).join("；")}</td></tr>)}</tbody></table> : <table className="data-table"><thead><tr><th>表格</th><th>行</th><th>字段</th><th>原记录值</th><th>对应关系</th></tr></thead><tbody>{sourceRows.map(({ edge, evidence }, index) => <tr key={`${edge.id}-${index}`} onClick={() => { setSelectedEdgeId(edge.id); setSelectedNodeId(""); }}><td>{evidence.sheet}</td><td>{evidence.row}</td><td>{evidence.field}</td><td>{evidence.value ?? "—"}</td><td>{edge.label}</td></tr>)}</tbody></table>}</div>
    </details>
    {expanded && <button className="case-knowledge-close" type="button" onClick={() => setExpanded(false)}>关闭放大</button>}
    {!expanded && <button className="case-knowledge-expand" type="button" onClick={() => setExpanded(true)} aria-label="放大图谱"><Maximize2 size={16}/>放大</button>}
    <button className="case-knowledge-reset" type="button" onClick={() => { setSelectedEdgeId(""); setSelectedNodeId(""); setQuery(""); }} aria-label="清除选择"><RotateCcw size={15}/>重置选择</button>
  </section>;
}

const ENTITY_LABELS_FOR_UI: Record<string, string> = { case: "病例", visit: "诊次", western_diagnosis: "西医病名", tcm_diagnosis: "中医病名", syndrome: "证型", treatment: "治法", tongue: "舌象", pulse: "脉象", prescription: "方药", formula: "方剂", herb: "药物" };

function Evidence({ items }: { items: { sheet: string; row: number; field: string; value?: string }[] }) {
  if (!items.length) return <p className="case-knowledge-source">暂无来源记录</p>;
  return <div className="case-knowledge-source"><strong>来源记录</strong>{items.map((item, index) => <span key={`${item.sheet}-${item.row}-${item.field}-${index}`}>{item.sheet} 第 {item.row} 行 · {item.field}{item.value ? `：${item.value}` : ""}</span>)}</div>;
}
