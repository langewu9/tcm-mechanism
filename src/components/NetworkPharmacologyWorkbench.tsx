"use client";

import { useMemo, useState } from "react";
import { Download, FileJson, GitCompareArrows, Network, Route, Search, Table2 } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { HorizontalPager, useTablePager } from "@/components/ViewportPager";

type TargetRow = {
  target: string;
  normalizedTarget: string;
  matchType: string;
  targetName: string;
  genes: string;
  pathways: string;
  components: string;
  herbs: string;
  diseaseNames: string;
  herbEvidenceCount: number;
  diseaseEvidenceCount: number;
  directEvidenceCount: number;
  sources: string;
};

type ApiResult = {
  ok: boolean;
  summary: {
    herb: string;
    disease: string;
    herbTargetCount: number;
    diseaseTargetCount: number;
    strictIntersectionCount: number;
    directAssociationTargetCount: number;
    candidateTargetCount: number;
    componentCount: number;
    pathwayCount: number;
    rowLimit: number;
    diseaseQueries?: string[];
    matchedDiseaseNames?: string[];
  };
  charts: {
    overlap: { name: string; value: number }[];
    components: { name: string; targets: number }[];
    pathways: { name: string; targets: number }[];
  };
  targets: TargetRow[];
  raw: Record<string, Record<string, unknown>[]>;
};

type EnrichedPathway = {
  rank: number;
  name: string;
  stableId: string | null;
  sourceUrl: string | null;
  matchedEntities: number;
  totalEntities: number;
  coverage: number;
  pValue: number;
  fdr: number;
};

type PathwayEnrichment = {
  run: {
    id: string;
    source: string;
    sourceVersion: string | null;
    sourceToken: string | null;
    rawTargetCount: number;
    inputCount: number;
    identifiersFound: number;
    identifiersNotFound: number;
    createdAt: string;
  };
  pathways: EnrichedPathway[];
};

type QueryNode = {
  id: string;
  label: string;
  kind: "herb" | "component" | "target" | "set" | "pathway" | "disease";
  x: number;
  y: number;
};

const colors = ["#9c2b22", "#c89b3c", "#b7682f", "#e0bd67", "#7a3326", "#d99b3d"];
const nodeColors: Record<QueryNode["kind"], string> = {
  herb: "#c89b3c",
  component: "#b7682f",
  target: "#8b4a16",
  set: "#6f7452",
  pathway: "#e0bd67",
  disease: "#9c2b22"
};

function compactNumber(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function shortText(value: string, size = 12) {
  return value.length > size ? `${value.slice(0, size)}...` : value;
}

function csvValue(value: unknown) {
  const text = Array.isArray(value) ? value.join("; ") : String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

function downloadCsv(filename: string, rows: Record<string, unknown>[]) {
  if (!rows.length) return;
  const headers = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const body = rows.map((row) => headers.map((header) => csvValue(row[header])).join(","));
  const blob = new Blob([`\ufeff${[headers.join(","), ...body].join("\n")}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function splitList(value: string) {
  return value.split("; ").map((item) => item.trim()).filter(Boolean);
}

function MiniMetric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{compactNumber(value)}</strong>
    </div>
  );
}

function EvidenceTable({ rows }: { rows: TargetRow[] }) {
  const { visibleRange, pager } = useTablePager(rows.length);
  const visible = rows.slice(...visibleRange);
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="data-table">
        <thead>
          <tr>
            <th>靶点名称</th>
            <th>匹配类型</th>
            <th>相关成分</th>
            <th>对应通路</th>
            <th>中药证据</th>
            <th>疾病证据</th>
            <th>来源</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((row) => (
            <tr key={`${row.matchType}-${row.normalizedTarget}`}>
              <td title={row.target}>{row.target}</td>
              <td>{row.matchType}</td>
              <td title={row.components}>{row.components || "-"}</td>
              <td title={row.pathways}>{row.pathways || "待富集"}</td>
              <td>{row.herbEvidenceCount}</td>
              <td>{row.diseaseEvidenceCount + row.directEvidenceCount}</td>
              <td title={row.sources}>{row.sources || "-"}</td>
            </tr>
          ))}
        </tbody>
        </table>
      </div>
      {pager}
    </div>
  );
}

function positionedLayer<T extends { id: string; label: string; kind: QueryNode["kind"] }>(items: T[], x: number, height: number) {
  const top = 112;
  const bottom = 84;
  if (items.length === 1) return [{ ...items[0], x, y: (top + height - bottom) / 2 }];
  const gap = (height - top - bottom) / Math.max(items.length - 1, 1);
  return items.map((item, index) => ({ ...item, x, y: top + gap * index }));
}

function networkLabelLines(label: string, maxLength: number) {
  const normalized = label.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) return [normalized];
  const preferredBreak = normalized.lastIndexOf(" ", maxLength);
  const splitAt = preferredBreak >= Math.floor(maxLength * 0.55) ? preferredBreak : maxLength;
  const first = normalized.slice(0, splitAt).trim();
  const remainder = normalized.slice(splitAt).trim();
  const second = remainder.length > maxLength ? `${remainder.slice(0, maxLength - 1)}…` : remainder;
  return [first, second].filter(Boolean);
}

function networkNodeDimensions(kind: QueryNode["kind"], degree: number) {
  const sizes: Record<QueryNode["kind"], { width: number; height: number }> = {
    herb: { width: 130, height: 54 },
    component: { width: 142, height: 46 },
    target: { width: 168, height: 48 },
    set: { width: 132, height: 54 },
    pathway: { width: 206, height: 52 },
    disease: { width: 132, height: 54 }
  };
  const base = sizes[kind];
  return { width: base.width + Math.min(degree * 2, 18), height: base.height };
}

function QueryEvidenceNetwork({ result, enrichment }: { result: ApiResult; enrichment: PathwayEnrichment | null }) {
  const width = 1460;
  const selectedTargetRows = [...result.targets]
    .sort((left, right) => (
      right.herbEvidenceCount + right.diseaseEvidenceCount + right.directEvidenceCount
    ) - (
      left.herbEvidenceCount + left.diseaseEvidenceCount + left.directEvidenceCount
    ))
    .slice(0, 9);
  const targetItems = selectedTargetRows.map((row) => ({ id: `target:${row.normalizedTarget}`, label: row.target, kind: "target" as const }));
  const targetIdSet = new Set(targetItems.map((item) => item.id));
  const componentItems = result.charts.components.slice(0, 8).map((item) => ({ id: `component:${item.name}`, label: item.name, kind: "component" as const }));
  const componentIdSet = new Set(componentItems.map((item) => item.id));
  const pathwaySource = enrichment?.pathways.length ? enrichment.pathways : result.charts.pathways;
  const pathwayItems = pathwaySource.slice(0, 5).map((item) => ({ id: `pathway:${item.name}`, label: item.name, kind: "pathway" as const }));
  const pathwayIdSet = new Set(pathwayItems.map((item) => item.id));
  const herbNode = { id: "herb", label: result.summary.herb, kind: "herb" as const };
  const targetSetNode = { id: "target-set", label: "候选靶点集", kind: "set" as const };
  const diseaseNode = { id: "disease", label: result.summary.disease, kind: "disease" as const };
  const maxLayerSize = Math.max(componentItems.length, targetItems.length, pathwayItems.length + 1, 1);
  const height = Math.max(640, maxLayerSize * 56 + 150);

  const nodes: QueryNode[] = [
    ...positionedLayer([herbNode], 92, height),
    ...positionedLayer(componentItems.length ? componentItems : targetItems.slice(0, 1).map((item) => ({ ...item, id: `component:${item.label}`, kind: "component" as const })), 370, height),
    ...positionedLayer(targetItems, 710, height),
    ...(pathwayItems.length ? positionedLayer([targetSetNode], 1010, height) : []),
    ...positionedLayer(pathwayItems.length ? [...pathwayItems, diseaseNode] : [diseaseNode], 1320, height)
  ];
  const byId = new Map(nodes.map((node) => [node.id, node]));

  const links: Array<{ source: string; target: string; label: string; kind: "contains" | "acts" | "summary" | "enrichment" | "disease" }> = [];
  for (const component of componentItems) links.push({ source: "herb", target: component.id, label: "含有", kind: "contains" });
  if (!componentItems.length) {
    for (const target of targetItems.slice(0, 6)) links.push({ source: "herb", target: target.id, label: "候选", kind: "acts" });
  }
  for (const row of selectedTargetRows) {
    const targetId = `target:${row.normalizedTarget}`;
    if (!targetIdSet.has(targetId)) continue;
    for (const component of splitList(row.components).slice(0, 6)) {
      const componentId = `component:${component}`;
      if (componentIdSet.has(componentId)) links.push({ source: componentId, target: targetId, label: "作用", kind: "acts" });
    }
    for (const pathway of splitList(row.pathways).slice(0, 4)) {
      const pathwayId = `pathway:${pathway}`;
      if (pathwayIdSet.has(pathwayId)) links.push({ source: targetId, target: pathwayId, label: "通路", kind: "enrichment" });
    }
    if (pathwayItems.length) links.push({ source: targetId, target: "target-set", label: "汇总", kind: "summary" });
    links.push({ source: targetId, target: "disease", label: row.matchType, kind: "disease" });
  }
  if (pathwayItems.length) {
    for (const pathway of pathwayItems) links.push({ source: "target-set", target: pathway.id, label: "富集", kind: "enrichment" });
  }

  const degree = new Map<string, number>();
  for (const link of links) {
    degree.set(link.source, (degree.get(link.source) ?? 0) + 1);
    degree.set(link.target, (degree.get(link.target) ?? 0) + 1);
  }
  const edgeStyle = {
    contains: { stroke: "#b58c55", opacity: 0.34, dash: undefined },
    acts: { stroke: "#718a7a", opacity: 0.34, dash: undefined },
    summary: { stroke: "#7c8164", opacity: 0.32, dash: "5 4" },
    enrichment: { stroke: "#a37b35", opacity: 0.4, dash: "6 4" },
    disease: { stroke: "#a95e53", opacity: 0.28, dash: undefined }
  } as const;

  return (
    <div className="network-canvas">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="当前查询的中药成分靶点通路证据链网络">
        <rect width={width} height={height} rx="12" fill="#fffdf8" />
        {[
          { x: 92, label: "中药" },
          { x: 370, label: "活性成分" },
          { x: 710, label: "候选靶点" },
          ...(pathwayItems.length ? [{ x: 1010, label: "靶点集合" }] : []),
          { x: 1320, label: "通路 / 疾病" }
        ].map((stage) => (
          <g key={stage.label}>
            <line x1={stage.x} y1={66} x2={stage.x} y2={height - 58} stroke="#e6ded0" strokeDasharray="3 7" />
            <text x={stage.x} y={37} textAnchor="middle" fill="#58483c" fontSize="15" fontWeight="700">
              {stage.label}
            </text>
          </g>
        ))}
        {links.slice(0, 90).map((link, index) => {
          const source = byId.get(link.source);
          const target = byId.get(link.target);
          if (!source || !target) return null;
          const sourceSize = networkNodeDimensions(source.kind, degree.get(source.id) ?? 0);
          const targetSize = networkNodeDimensions(target.kind, degree.get(target.id) ?? 0);
          const sourceX = source.x + sourceSize.width / 2;
          const targetX = target.x - targetSize.width / 2;
          const midX = (sourceX + targetX) / 2;
          const style = edgeStyle[link.kind];
          return (
            <path
              key={`${link.source}-${link.target}-${index}`}
              d={`M ${sourceX} ${source.y} C ${midX} ${source.y}, ${midX} ${target.y}, ${targetX} ${target.y}`}
              fill="none"
              stroke={style.stroke}
              strokeOpacity={style.opacity}
              strokeWidth="1.15"
              strokeDasharray={style.dash}
            >
              <title>{`${source.label} -${link.label}-> ${target.label}`}</title>
            </path>
          );
        })}
        {nodes.map((node) => {
          const nodeDegree = degree.get(node.id) ?? 0;
          const size = networkNodeDimensions(node.kind, nodeDegree);
          const maxLabelLength = node.kind === "pathway"
            ? 24
            : node.kind === "target"
              ? 18
              : node.kind === "herb"
                ? 9
                : node.kind === "disease" || node.kind === "set"
                  ? 10
                  : 16;
          const lines = networkLabelLines(node.label, maxLabelLength);
          const color = nodeColors[node.kind];
          const rx = node.kind === "component" ? size.height / 2 : node.kind === "pathway" ? 10 : 7;
          return (
            <g key={node.id} transform={`translate(${node.x}, ${node.y})`}>
              <rect x={-size.width / 2} y={-size.height / 2} width={size.width} height={size.height} rx={rx} fill="#fffaf1" stroke={color} strokeWidth={node.kind === "herb" || node.kind === "disease" ? 2.4 : 1.8} />
              <circle cx={-size.width / 2 + 12} cy={0} r={4.5 + Math.min(nodeDegree, 6) * 0.35} fill={color} />
              <text textAnchor="middle" fill="#35251f" fontSize={node.kind === "pathway" ? 10.4 : 11} fontWeight={node.kind === "herb" || node.kind === "disease" ? 800 : 650}>
                {lines.map((line, lineIndex) => <tspan key={line} x={5} y={(lineIndex - (lines.length - 1) / 2) * 14 + 4}>{line}</tspan>)}
              </text>
              <title>{`${node.label} · 连接度 ${nodeDegree}`}</title>
            </g>
          );
        })}
        <g transform={`translate(30, ${height - 28})`}>
          <text fill="#75675c" fontSize="11">展示证据度前 9 位候选靶点 · 节点宽度随连接度轻微变化 · 实线表示数据关联 · 虚线表示集合富集关系</text>
        </g>
      </svg>
    </div>
  );
}

function NetworkResultPager({ result, enrichment, enriching }: { result: ApiResult; enrichment: PathwayEnrichment | null; enriching: boolean }) {
  const pathwayRows = enrichment
    ? enrichment.pathways.map((pathway) => ({
        name: pathway.name,
        targets: pathway.matchedEntities,
        fdr: pathway.fdr,
        stableId: pathway.stableId ?? ""
      }))
    : result.charts.pathways;
  const componentRows = result.charts.components;
  const targetRows = result.targets;
  const resolvedDiseaseNames = result.summary.matchedDiseaseNames?.slice(0, 6) ?? [];

  return (
    <HorizontalPager ariaLabel="网络药理学结果分页" pages={[
      {
        id: "overview",
        label: "靶点概览",
        content: <div className="space-y-5">
          <div className="np-metrics">
            <MiniMetric label="中药靶点" value={result.summary.herbTargetCount} />
            <MiniMetric label="疾病靶点" value={result.summary.diseaseTargetCount} />
            <MiniMetric label="严格交集" value={result.summary.strictIntersectionCount} />
            <MiniMetric label="直接关联" value={result.summary.directAssociationTargetCount} />
            <MiniMetric label="候选靶点" value={result.summary.candidateTargetCount} />
            <MiniMetric label={enrichment ? "富集通路" : "通路注释"} value={enrichment ? enrichment.pathways.length : result.summary.pathwayCount} />
          </div>
          {resolvedDiseaseNames.length ? <div className="notice-success">中文疾病名已解析为本地疾病库记录：{resolvedDiseaseNames.join("、")}</div> : null}
          {enrichment ? <div className="notice-success">Reactome 通路补全已保存：{enrichment.run.rawTargetCount} 个候选靶点已规范化为 {enrichment.run.inputCount} 个基因符号，Reactome 识别 {enrichment.run.identifiersFound} 个，保留 {enrichment.pathways.length} 条 FDR ≤ 0.05 的通路结果。</div> : null}
          <div className="grid gap-5 xl:grid-cols-2">
            <div className="figure-card">
              <div className="figure-heading"><span>Prep A</span><div><h2>靶点比对概览</h2><p>{result.summary.herb} 与 {result.summary.disease} 的靶点规模、严格交集和直接关联。</p></div></div>
              <div className="h-72"><ResponsiveContainer width="100%" height="100%"><BarChart data={result.charts.overlap} margin={{ top: 10, right: 16, bottom: 4, left: 0 }}><CartesianGrid stroke="#ded3c2" strokeDasharray="3 3" vertical={false} /><XAxis dataKey="name" tickLine={false} axisLine={{ stroke: "#b9ad9c" }} /><YAxis tickFormatter={compactNumber} tickLine={false} axisLine={false} width={54} /><Tooltip formatter={(value) => compactNumber(Number(value))} /><Bar dataKey="value" radius={[5, 5, 0, 0]}>{result.charts.overlap.map((item, index) => <Cell key={item.name} fill={colors[index % colors.length]} />)}</Bar></BarChart></ResponsiveContainer></div>
            </div>
            <div className="figure-card">
              <div className="figure-heading"><span>Prep B</span><div><h2>候选靶点构成</h2><p>区分严格交集和疾病-中药直接关联靶点，便于后续筛选策略分层。</p></div></div>
              <div className="h-72"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={[{ name: "严格交集", value: result.summary.strictIntersectionCount }, { name: "直接关联", value: result.summary.directAssociationTargetCount }]} dataKey="value" nameKey="name" innerRadius={56} outerRadius={92} paddingAngle={2}><Cell fill="#9c2b22" /><Cell fill="#b94232" /></Pie><Legend verticalAlign="bottom" height={28} /><Tooltip formatter={(value) => compactNumber(Number(value))} /></PieChart></ResponsiveContainer></div>
            </div>
          </div>
        </div>
      },
      {
        id: "distribution",
        label: "成分与通路",
        content: <div className="grid gap-5 p-5 xl:grid-cols-2">
          <div className="figure-card">
            <div className="figure-heading"><span>Prep C</span><div><h2>关联成分 Top 20</h2><p>只统计本次查询候选靶点涉及的成分，辅助优先挑选后续验证对象。</p></div></div>
            <div className="h-80">{componentRows.length ? <ResponsiveContainer width="100%" height="100%"><BarChart data={componentRows.slice(0, 12)} layout="vertical" margin={{ top: 8, right: 20, bottom: 8, left: 48 }}><CartesianGrid stroke="#ded3c2" strokeDasharray="3 3" horizontal={false} /><XAxis type="number" tickLine={false} axisLine={false} /><YAxis dataKey="name" type="category" width={126} tickLine={false} axisLine={false} tickFormatter={(value) => shortText(String(value), 13)} /><Tooltip /><Bar dataKey="targets" name="候选靶点" fill="#c89b3c" radius={[0, 4, 4, 0]} /></BarChart></ResponsiveContainer> : <div className="empty-state h-full min-h-0">暂无成分覆盖数据。</div>}</div>
          </div>
          <div className="figure-card">
            <div className="figure-heading"><span>Prep D</span><div><h2>{enrichment ? "Reactome 富集通路" : "对应通路"}</h2><p>{enrichment ? "按 FDR 排序展示本次候选靶点的查询级通路富集结果；命中数为 Reactome 返回的匹配实体数。" : "提交查询后自动以当前候选靶点生成可追溯的 Reactome 富集结果。"}</p></div></div>
            <div className="h-80">{pathwayRows.length ? <ResponsiveContainer width="100%" height="100%"><BarChart data={pathwayRows.slice(0, 12)} layout="vertical" margin={{ top: 8, right: 20, bottom: 8, left: 48 }}><CartesianGrid stroke="#ded3c2" strokeDasharray="3 3" horizontal={false} /><XAxis type="number" tickLine={false} axisLine={false} /><YAxis dataKey="name" type="category" width={150} tickLine={false} axisLine={false} tickFormatter={(value) => shortText(String(value), 16)} /><Tooltip formatter={(value, name, item) => name === "FDR" ? Number(value).toExponential(2) : value} /><Bar dataKey="targets" name={enrichment ? "命中实体" : "靶点数"} fill="#9b6b34" radius={[0, 4, 4, 0]} /></BarChart></ResponsiveContainer> : <div className="empty-state h-full min-h-0"><Route size={24} /><strong>{enriching ? "正在生成 Reactome 通路" : "暂无可用通路结果"}</strong><p>{enriching ? "正在将当前候选靶点规范化并计算富集通路，请稍候。" : "请重新提交查询以自动生成当前候选靶点的 Reactome 富集结果。"}</p></div>}</div>
          </div>
        </div>
      },
      {
        id: "network",
        label: "证据链网络",
        content: <section className="figure-card m-5"><div className="figure-heading"><span>Prep E</span><div><h2>查询证据链网络</h2><p>采用传统网络药理学分层布局展示中药、活性成分、候选靶点、富集通路与疾病关系；节点大小反映连接度。</p></div></div><QueryEvidenceNetwork result={result} enrichment={enrichment} /></section>
      },
      {
        id: "table",
        label: "交集靶点表",
        content: <section className="figure-card m-5 p-0"><div className="figure-heading px-4 pt-4"><span>Prep F</span><div><h2>疾病靶点交集一览</h2><p>包含靶点名称、匹配类型、对应成分、通路、证据计数和数据库来源。</p></div></div>{targetRows.length ? <EvidenceTable rows={targetRows} /> : <div className="empty-state">暂无候选交集靶点，请更换疾病或中药名称。</div>}</section>
      }
    ]} />
  );
}

export function NetworkPharmacologyWorkbench() {
  const [herb, setHerb] = useState("麦冬、半夏、人参、大枣、甘草、粳米");
  const [disease, setDisease] = useState("肺纤维化");
  const [loading, setLoading] = useState(false);
  const [enriching, setEnriching] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ApiResult | null>(null);
  const [enrichment, setEnrichment] = useState<PathwayEnrichment | null>(null);

  const targetRows = useMemo(() => result?.targets ?? [], [result]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/network-pharmacology", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ herb, disease })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "网络药理学比对失败");
      setResult(data);
      setEnrichment(null);
      await enrichPathways(data);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "网络药理学比对失败");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  async function enrichPathways(networkResult = result) {
    if (!networkResult?.targets.length) return;
    setEnriching(true);
    setError("");
    try {
      const response = await fetch("/api/pathway-enrichment", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          herb: networkResult.summary.herb,
          disease: networkResult.summary.disease,
          targets: networkResult.targets.map((row) => row.target)
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "通路补全失败");
      setEnrichment(data);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "通路补全失败");
    } finally {
      setEnriching(false);
    }
  }

  return (
    <section className="panel overflow-hidden">
      <div className="panel-header">
        <div>
          <p className="page-kicker">NETWORK PHARMACOLOGY</p>
          <h2 className="section-title-sm">中药-疾病靶点交集工作台</h2>
          <p className="section-help">所有图表都会随当前中药与疾病查询词重新计算，不再展示全库或最近任务的全局图。</p>
        </div>
        <span className="status-badge status-success">查询驱动</span>
      </div>

      <div className={`grid gap-5 p-5 ${result ? "" : "xl:grid-cols-[360px_minmax(0,1fr)]"}`}>
        <form className="space-y-4" onSubmit={submit}>
          <label className="form-label">
            麦门冬汤组成（可输入多味中药）
            <textarea className="field mt-2 min-h-28" value={herb} onChange={(event) => setHerb(event.target.value)} placeholder="例如：麦冬、半夏、人参、大枣、甘草、粳米" />
          </label>
          <label className="form-label">
            疾病名称
            <input className="field mt-2" value={disease} onChange={(event) => setDisease(event.target.value)} placeholder="例如：肺纤维化" />
          </label>
          {error ? <div className="notice-error">{error}</div> : null}
          <button className="btn btn-primary w-full" disabled={loading} type="submit">
            <Search size={17} />
            {loading ? "正在比对..." : "生成交集与通路"}
          </button>
          {result ? (
            <div className="download-panel">
              <button type="button" onClick={() => downloadCsv(`targets_${herb}_${disease}.csv`, targetRows)}>
                <Table2 size={15} /> 交集靶点表
              </button>
              <button type="button" onClick={() => downloadCsv(`raw_herb_${herb}.csv`, result.raw.herbLinks ?? [])}>
                <Download size={15} /> 中药侧原始表
              </button>
              <button type="button" onClick={() => downloadCsv(`raw_disease_${disease}.csv`, result.raw.diseaseTargets ?? [])}>
                <Download size={15} /> 疾病侧原始表
              </button>
              <button type="button" onClick={() => downloadCsv(`direct_${herb}_${disease}.csv`, result.raw.directDiseaseHerbLinks ?? [])}>
                <GitCompareArrows size={15} /> 直接关联表
              </button>
              <button type="button" onClick={() => downloadJson(`network_pharmacology_${herb}_${disease}.json`, result)}>
                <FileJson size={15} /> 完整 JSON
              </button>
              <button type="button" disabled={enriching || !targetRows.length} onClick={() => enrichPathways()}>
                <Route size={15} /> {enriching ? "正在生成 Reactome 通路..." : enrichment ? "重新生成 Reactome 通路" : "生成 Reactome 通路"}
              </button>
              {enrichment ? <button type="button" onClick={() => downloadJson(`reactome_pathways_${herb}_${disease}.json`, enrichment)}><Download size={15} /> 导出通路结果</button> : null}
            </div>
          ) : null}
        </form>

        {!result ? (
          <div className="empty-state min-h-[26rem]">
            <Network size={28} />
            <strong>输入中药和疾病后生成全部图表</strong>
            <p>提交后，页面上的统计、柱图、环图、成分图、通路图、证据链网络和表格都会围绕本次查询词更新。</p>
          </div>
        ) : <NetworkResultPager result={result} enrichment={enrichment} enriching={enriching} />}
      </div>
    </section>
  );
}
