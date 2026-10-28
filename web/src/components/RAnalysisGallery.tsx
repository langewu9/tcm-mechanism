import { useEffect, useRef, useState } from "react";
import { getAnalysisTask, getAnalysisTasks, type AnalysisTask } from "../api/datasets";
import { createVisualization } from "../api/network";
import { ApiError } from "../api/client";
import { RChartSource, RChartSourceProvider } from "./RChartSource";
import { SubviewTabs, type Subview } from "./SubviewTabs";
import { RChartViewer, hasInteractiveRenderer } from "./RChartViewer";

type Chart = { key: string; label: string; available: boolean; note: string };
type Artifact = { id: number; format: string; downloadUrl: string };
function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function list(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
export function rChartCatalog(task: AnalysisTask): Chart[] {
  const result = record(task.result);
  const network = record(result.network);
  const hasGraph = list(network.links).length > 0;
  const ppi = task.task_type === "proteomics" ? record(result.externalString) : result;
  const hasPpi = ppi.source === "STRING" && ppi.networkType === "physical"
    && (ppi.status === "succeeded" || (ppi.status === undefined && ppi.analysisKind === "string_ppi")) && list(ppi.edges).length > 0;
  const ppiCharts: Chart[] = [
    { key: "ppi_network", label: "STRING PPI 网络图", available: hasPpi, note: "需要已单独同意并成功返回的物理互作；节点大小为展示子图连接度。" },
    { key: "ppi_degree", label: "PPI 连接度排行", available: hasPpi, note: "按完整有效返回图的唯一邻居数排序，不是因果或核心蛋白结论。" },
  ];
  if (task.task_type === "network" && result.analysisKind === "string_ppi") return ppiCharts;
  const reactome = task.task_type === "proteomics" ? record(result.externalReactome) : result;
  const reactomeChart: Chart = { key: "reactome_enrichment", label: "Reactome 通路气泡图", available: list(reactome.pathways).length > 0 && (reactome.status === "succeeded" || reactome.analysisKind === "reactome_enrichment"), note: "需要有效 FDR 和命中/通路实体数；不冒充 GO/KEGG 结果。" };
  if (result.analysisKind === "reactome_enrichment") return [reactomeChart];
  if (!["proteomics", "network"].includes(task.task_type)) return [];
  if (result.analysisKind === "catalog_evidence" && result.queryType === "comparison") return [
    { key: "catalog_summary", label: "名称对照数量概览", available: list(result.catalogSummary).length > 0, note: "按规范化比对键统计，同家族候选单列且不计入精确交集，不代表化学结构鉴定。" },
  ];
  if (task.task_type === "network" && result.analysisKind === "catalog_evidence") return [
    { key: "evidence_network", label: "检索圆形证据网络", available: hasGraph, note: "圆形网络；只绘制快照内实际登记关系，完整证据保留在来源快照。" },
    { key: "catalog_summary", label: "实体与证据概览", available: list(result.catalogSummary).length > 0, note: "按本地实体主键 / 关系主键去重计数，不合并同名异标识。" },
    { key: "catalog_degree", label: result.queryType === "pathway" ? "通路注释分布" : "实体连接度分布", available: hasGraph || list(result.catalogCoverage).length > 0, note: "唯一邻居数 / 本地通路覆盖计数，不是核心靶点结论或富集显著性。" },
  ];
  const hasPathway = list(network.nodes).some(node => record(node).type === "pathway") && hasGraph;
  const graphs: Chart[] = [
    { key: "gene_pathway_network", label: "基因—通路证据网络", available: hasPathway, note: "仅绘制当前本地已登记的实际关系，最多 80 节点、500 边。" },
    { key: "gene_pathway_distribution", label: "基因通路分布图", available: hasPathway, note: "按每通路的唯一关联基因计数，不是富集显著性检验。" },
  ];
  if (task.task_type === "network") return [
    { key: "evidence_network", label: "中药—成分—靶点—疾病网络", available: hasGraph, note: "圆形网络；无证据关系不生成示意边。" },
    ...["overlap", "components", "pathways"].map((key, index) => ({ key, label: ["靶点比对统计", "成分靶点覆盖", "本地通路注释分布"][index],
      available: list(record(result.charts)[key]).length > 0, note: "R 交互点图展示已保存的查询统计；不同集合不相加作总数，本地注释不冒充富集结果。" })),
    ...graphs,
  ];
  const go = record(result.externalGProfiler);
  return [
    { key: "proteomics_summary", label: "分析概览", available: true, note: "差异筛选、标识映射和通路数量汇总。" },
    ...ppiCharts, ...graphs,
    { key: "proteomics_go_kegg_bar", label: "GO / KEGG 富集显著性点图", available: go.status === "succeeded" && list(go.terms).length > 0, note: "GO:BP / CC / MF 与 KEGG，按 FDR 排序；数据来自 g:Profiler。" },
    reactomeChart,
  ];
}

export function RAnalysisGallery({ taskId, additionalCharts = [], initialSource = "task" }: { taskId: number; additionalCharts?: Subview[]; initialSource?: string }) {
  const [selectedKey, setSelectedKey] = useState(additionalCharts[0]?.key ?? "");
  const [chartSource, setChartSource] = useState(initialSource);
  const [parent, setParent] = useState<AnalysisTask | null>(null);
  const [jobs, setJobs] = useState<Record<string, AnalysisTask>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const renderLock = useRef(false);
  useEffect(() => {
    const current = ++generation.current;
    setParent(null); setJobs({}); setError(null); setBusy(null);
    renderLock.current = false;
    Promise.all([getAnalysisTask(taskId), getAnalysisTasks(1, taskId)]).then(([source, page]) => {
      if (generation.current !== current) return;
      setParent(source);
      const restored: Record<string, AnalysisTask> = {};
      for (const job of page.results) {
        const key = job.input_parameters.chartKey;
        if (job.task_type === "visualization" && job.parent_task === taskId && typeof key === "string" && !restored[key]) restored[key] = job;
      }
      setJobs(restored);
    }).catch(cause => { if (generation.current === current) setError(cause instanceof ApiError ? cause.message : "R 分析目录加载失败。"); });
    return () => { generation.current++; };
  }, [taskId]);
  useEffect(() => {
    let active = true;
    const current = generation.current;
    const pending = Object.entries(jobs).filter(([, job]) => ["queued", "running"].includes(job.status));
    if (!pending.length) return;
    let timer: number;
    async function poll() {
      try {
        const updates = await Promise.all(pending.map(async ([key, job]) => {
          const latest = await getAnalysisTask(job.id);
          if (latest.id !== job.id || latest.parent_task !== taskId || latest.input_parameters.chartKey !== key) throw new Error("R 图表来源不一致。");
          return [key, latest] as const;
        }));
        if (active && generation.current === current) { setJobs(previous => ({ ...previous, ...Object.fromEntries(updates) })); setError(null); }
      } catch (cause) {
        if (active && generation.current === current) {
          setError(cause instanceof ApiError ? cause.message : "R 图表状态读取失败，正在重试读取已有任务。");
          timer = window.setTimeout(() => void poll(), 1500);
        }
      }
    }
    timer = window.setTimeout(() => void poll(), 1500);
    return () => { active = false; window.clearTimeout(timer); };
  }, [jobs, taskId]);
  async function renderChart(key: string) {
    if (renderLock.current) return;
    renderLock.current = true;
    const current = generation.current;
    setBusy(key); setError(null);
    try {
      const job = await createVisualization(taskId, key);
      if (generation.current === current) setJobs(previous => ({ ...previous, [key]: job }));
    } catch (cause) {
      if (generation.current === current) setError(cause instanceof ApiError ? cause.message : "图表任务创建失败。");
    } finally { if (generation.current === current) { renderLock.current = false; setBusy(null); } }
  }
  if (parent && parent.status !== "succeeded") return null;
  const charts = parent ? rChartCatalog(parent) : [];
  return <RChartSourceProvider source={chartSource} onChange={setChartSource}><section className="proteomics-result-section" aria-label="图表与网络">

    <h3 className="section-title-sm">图表与网络</h3>

    {error && <div className="notice-error" role="alert">{error}</div>}
    {!parent && !error && <p role="status">正在读取可用图表…</p>}
    <SubviewTabs label="选择 R 分析图表" value={selectedKey || additionalCharts[0]?.key || charts.find(chart => chart.available)?.key || ""} onChange={setSelectedKey} views={[...additionalCharts, ...charts.map(chart => {
      const job = jobs[chart.key];
      const pending = Boolean(job && ["queued", "running"].includes(job.status));
      const value = record(job?.result);
      const artifacts = list(value.artifacts) as Artifact[];
      const svg = artifacts.find(item => item.format === "svg");
      const html = artifacts.find(item => item.format === "html");
      return { key: chart.key, label: chart.label, content: <div className="panel source-record">
        <h4>{chart.label}</h4><p className="section-help">{chart.note}</p>
        <RChartSource key={chart.key} chartKey={chart.key}>
        <button className="btn btn-secondary" type="button" disabled={!chart.available || busy !== null || pending || job?.status === "succeeded"} onClick={() => void renderChart(chart.key)}>
          {!chart.available ? "缺少所需分析数据" : busy === chart.key ? "正在提交…" : pending ? `后台绘图 ${job?.progress ?? 0}%` : job?.status === "succeeded" ? "已生成" : job?.status === "failed" ? "重试绘图" : "生成 R 图表"}
        </button>
        {job?.status === "failed" && <p className="notice-error" role="alert">{job.error_summary}</p>}
        {job?.status === "succeeded" && <>
          <details className="raw-details"><summary>绘图记录</summary><p className="section-help">任务 #{job.id} · {String(value.rendererVersion ?? "")} · 分析 #{taskId}</p></details>
          {!hasInteractiveRenderer(value.rendererVersion) && <p className="notice-info">此任务提供静态图表，可查看或下载原始图片。</p>}
          <RChartViewer key={job.id} title={chart.label} interactive={hasInteractiveRenderer(value.rendererVersion)}
            svgUrl={svg && `${svg.downloadUrl}?inline=1`} htmlUrl={html && `${html.downloadUrl}?inline=1`} />
          <div className="source-record-actions">{artifacts.map(item => <a className="btn btn-secondary" key={item.id} href={item.downloadUrl}>下载 {item.format.toUpperCase()}</a>)}</div>
        </>}
        </RChartSource>
      </div> };
    })]} />
  </section></RChartSourceProvider>;
}
