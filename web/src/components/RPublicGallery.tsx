import { useEffect, useState } from "react";
import { RChartViewer, hasInteractiveRenderer } from "./RChartViewer";
import { R_CHARTS } from "../demo/catalog";

type PublicChart = { key: string; label: string; inputSha256: string; rendererVersion: string; artifacts: Record<string, string> };
type PublicManifest = { publicExample: true; synthetic: false; disclaimer: string; charts: PublicChart[];
  provenance: { source: string; sourceVersion: string; license: string; retrievedAt: string; contentSha256: string;
    queryGeneCount: number; mappedGeneCount: number; displayedNodeCount: number; displayedEdgeCount: number;
    returnedUniqueEdgeCount: number; networkType: string; requiredScore: number; background: string } };

export function readPublicManifest(value: unknown): PublicManifest {
  const manifest = value as PublicManifest | null;
  if (!manifest || manifest.synthetic !== false || manifest.publicExample !== true || typeof manifest.disclaimer !== "string"
    || !Array.isArray(manifest.charts) || !manifest.charts.length || new Set(manifest.charts.map(chart => chart.key)).size !== manifest.charts.length
    || manifest.charts.some(chart => !R_CHARTS.some(([key]) => key === chart.key) || !/^[a-f0-9]{64}$/.test(chart.inputSha256)
      || typeof chart.label !== "string" || !hasInteractiveRenderer(chart.rendererVersion) || !chart.artifacts || !/^[a-f0-9]{64}$/.test(chart.artifacts.html))
    || manifest.provenance?.source !== "STRING" || manifest.provenance?.networkType !== "physical" || manifest.provenance?.license !== "CC BY 4.0"
    || !/^[a-f0-9]{64}$/.test(manifest.provenance.contentSha256)) throw new Error("Invalid public example manifest");
  return manifest;
}

export function RPublicGallery({ chartKey }: { chartKey: string }) {
  const [manifest, setManifest] = useState<PublicManifest | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    fetch("/r-public-demo/manifest.json").then(async response => { if (!response.ok) throw new Error(); return readPublicManifest(await response.json()); })
      .then(value => { if (active) setManifest(value); }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, []);
  if (error) return <p className="notice-error" role="alert">公开数据图表暂不可用，请稍后重试。</p>;
  if (!manifest) return <p role="status">正在读取独立公开数据示例…</p>;
  const chart = manifest.charts.find(chart => chart.key === chartKey);
  const source = manifest.provenance;
  return <section className="panel source-record" aria-label="STRING 公开数据示例">
    <p className="notice-info">{manifest.disclaimer}</p>
    <details className="raw-details"><summary>数据来源、许可与方法</summary>
    <p className="section-help">STRING {source.sourceVersion} · {source.license} · {source.queryGeneCount} 个预选基因 / {source.mappedGeneCount} 个已映射基因；PPI 物理互作筛选 ≥ {source.requiredScore / 1000}。
      PPI 子图展示 {source.displayedNodeCount} 个节点、{source.displayedEdgeCount}/{source.returnedUniqueEdgeCount} 条边（按分数选择，最多 500 边）。基因—通路边是数据库命中注释，不是物理互作，边值 1 仅表示关系存在。</p>
    <p className="section-help">快照时间：{source.retrievedAt}。仅为公开基因集的数据库示例，不是差异蛋白实验，也没有证明中药—疾病关系。
      GO / KEGG / Reactome 使用 STRING 报告的 FDR，默认人类基因组背景；不与当前任务混用。</p>
    <div className="source-record-actions"><a className="btn btn-secondary" href="https://string-db.org/help/api/" target="_blank" rel="noreferrer">数据来源与方法</a>
      <a className="btn btn-secondary" href="https://string-db.org/cgi/access" target="_blank" rel="noreferrer">CC BY 4.0 许可</a></div>
    </details>
    {!chart ? <p className="notice-warning">本图暂无公开数据示例，请选择其他图表或查看合成演示。</p> : <>
      <h4>{chart.label}</h4>
      <RChartViewer key={chart.key} title={chart.label} interactive svgUrl={`/r-public-demo/${chart.key}.svg`} htmlUrl={`/r-public-demo/${chart.key}.html?v=${chart.artifacts.html}`} />
      <div className="source-record-actions">{["json", "svg", "png", "pdf", "html"].map(format => <a className="btn btn-secondary" download key={format} href={`/r-public-demo/${chart.key}.${format}`}>{format === "json" ? "下载配套数据" : `下载 ${format.toUpperCase()}`}</a>)}</div>
    </>}
  </section>;
}
