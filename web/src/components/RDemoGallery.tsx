import { useEffect, useState } from "react";
import { Maximize2 } from "lucide-react";
import { R_CHARTS } from "../demo/catalog";
import { RChartViewer, hasInteractiveRenderer } from "./RChartViewer";
import "../styles/chart-gallery.css";

type DemoChart = { key: string; label: string; rendererVersion: string; inputSha256: string; rowCount: number; nodeCount: number; edgeCount: number; artifacts: Record<string, string> };
type Manifest = { synthetic: true; datasetVersion: string; disclaimer: string; charts: DemoChart[] };
export const GALLERY_VERSION = "dense-20261027";
export const GALLERY_PAGE_SIZE = 6;
const groups = [
  { key: "all", label: "全部图表", charts: [] },
  { key: "network", label: "网络与关联", charts: ["ppi_network", "ppi_degree", "evidence_network", "gene_pathway_network", "gene_pathway_distribution", "proteomics_top_nodes", "catalog_degree"] },
  { key: "enrichment", label: "功能富集", charts: ["proteomics_go_kegg_enrichment", "proteomics_go_kegg_bar", "reactome_enrichment"] },
  { key: "overview", label: "差异与概览", charts: ["proteomics_volcano", "proteomics_summary", "overlap", "components", "pathways", "catalog_summary"] },
];
export function readDemoManifest(value: unknown): Manifest {
  const data = value as Manifest | null;
  if (!data || data.synthetic !== true || data.datasetVersion !== GALLERY_VERSION || typeof data.disclaimer !== "string" || !Array.isArray(data.charts)
    || data.charts.length !== R_CHARTS.length || new Set(data.charts.map(chart => chart?.key)).size !== R_CHARTS.length
    || data.charts.some(chart => !chart || !R_CHARTS.some(([key]) => key === chart.key) || typeof chart.label !== "string"
      || !/^[a-f0-9]{64}$/.test(chart.inputSha256) || !hasInteractiveRenderer(chart.rendererVersion)
      || !Number.isInteger(chart.rowCount) || chart.rowCount < 1 || !Number.isInteger(chart.nodeCount) || chart.nodeCount < 0
      || !Number.isInteger(chart.edgeCount) || chart.edgeCount < 0 || !chart.artifacts
      || ["svg", "png", "pdf", "html"].some(format => !/^[a-f0-9]{64}$/.test(chart.artifacts[format])))) throw new Error("Invalid gallery manifest");
  return data;
}
export function galleryPage(charts: DemoChart[], category: string, page: number) {
  const group = groups.find(item => item.key === category) ?? groups[0];
  const filtered = charts.filter(chart => group.key === "all" || group.charts.includes(chart.key));
  const pages = Math.max(1, Math.ceil(filtered.length / GALLERY_PAGE_SIZE));
  const current = Math.min(Math.max(0, page), pages - 1);
  return { charts: filtered.slice(current * GALLERY_PAGE_SIZE, (current + 1) * GALLERY_PAGE_SIZE), total: filtered.length, pages, current };
}
function chartStats(chart: DemoChart) {
  return chart.nodeCount ? `${chart.nodeCount} 个节点 · ${chart.edgeCount} 条关系` : `${chart.rowCount.toLocaleString("zh-CN")} 条数据`;
}

export function RDemoGallery({ chartKey, defaultOpen = false, embedded = false }: { chartKey?: string; defaultOpen?: boolean; embedded?: boolean }) {
  const [opened, setOpened] = useState(defaultOpen);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [category, setCategory] = useState("all");
  const [page, setPage] = useState(0);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!opened) return;
    let active = true;
    setError("");
    fetch(`/r-demo/manifest.json?v=${GALLERY_VERSION}`, { cache: "no-store" }).then(async response => {
      if (!response.ok) throw new Error();
      const value = readDemoManifest(await response.json());
      if (active) setManifest(value);
    }).catch(() => { if (active) setError("演示图库暂不可用，请稍后重试。"); });
    return () => { active = false; };
  }, [opened, retry]);
  const selected = manifest?.charts.find(item => item.key === (chartKey ?? selectedKey));
  const window = manifest ? galleryPage(manifest.charts, category, page) : null;
  function downloads(chart: DemoChart) {
    return <div className="source-record-actions">{["json", "svg", "png", "pdf", "html"].map(format => <a className="btn btn-secondary" key={format} download href={`/r-demo/${chart.key}.${format}?v=${chart.artifacts[format] ?? chart.inputSha256}`}>{format === "json" ? "下载配套数据" : `下载 ${format.toUpperCase()}`}</a>)}</div>;
  }
  return <section className={`chart-gallery${embedded ? "" : " panel source-record"}`} aria-label={chartKey ? `${chartKey} 合成演示` : "合成演示图库"}>
    {!embedded && <header className="chart-gallery-heading"><div><h3 className="section-title-sm">演示图库</h3><p className="section-help">选择图窗，查看完整交互图表。</p></div>{!defaultOpen && <button type="button" className="btn btn-secondary" aria-expanded={opened} onClick={() => setOpened(!opened)}>{opened ? "收起图库" : "打开图库"}</button>}</header>}
    {opened && <>
      {error && <p className="notice-error" role="alert">{error} <button type="button" className="btn btn-secondary" onClick={() => setRetry(retry + 1)}>重新加载</button></p>}
      {!manifest && !error && <p role="status">正在加载图库…</p>}
      {manifest && <>
        <p className="chart-gallery-notice">合成演示数据，仅用于展示图表，不代表实验或数据库证据。</p>
        {chartKey && selected ? <><RChartViewer title={selected.label} interactive svgUrl={`/r-demo/${selected.key}.svg?v=${selected.artifacts.svg}`} htmlUrl={`/r-demo/${selected.key}.html?v=${selected.artifacts.html}`} />{downloads(selected)}</> : window && <>
          <div className="chart-gallery-filter" role="group" aria-label="图表分类">{groups.map(group => <button type="button" key={group.key} className="chart-gallery-chip" aria-pressed={category === group.key} onClick={() => { setCategory(group.key); setPage(0); }}>{group.label}</button>)}<span role="status">{window.total} 张图表</span></div>
          <div className="chart-gallery-grid">{window.charts.map(chart => <button key={chart.key} type="button" className="chart-gallery-card" onClick={() => setSelectedKey(chart.key)} aria-haspopup="dialog" aria-label={`打开${chart.label}`}>
            <span className="chart-gallery-preview"><img loading="lazy" src={`/r-demo/${chart.key}.svg?v=${chart.artifacts.svg}`} alt={`${chart.label}预览`} /></span>
            <span className="chart-gallery-caption"><span><strong>{chart.label}</strong><small>{chartStats(chart)}</small></span><Maximize2 size={17} aria-hidden="true" /></span>
          </button>)}</div>
          <nav className="table-pager" aria-label="图库分页"><span>第 {window.current + 1} / {window.pages} 页</span><div><button type="button" disabled={window.current === 0} onClick={() => setPage(window.current - 1)}>上一页</button><button type="button" disabled={window.current + 1 === window.pages} onClick={() => setPage(window.current + 1)}>下一页</button></div></nav>
          {selected && <RChartViewer key={selected.key} title={selected.label} interactive defaultExpanded onClose={() => setSelectedKey(null)} footer={downloads(selected)} svgUrl={`/r-demo/${selected.key}.svg?v=${selected.artifacts.svg}`} htmlUrl={`/r-demo/${selected.key}.html?v=${selected.artifacts.html}`} />}
        </>}
      </>}
    </>}
  </section>;
}
