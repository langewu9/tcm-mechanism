import { useEffect, useRef, useState } from "react";
import { getAnalysisTask, getAnalysisTaskSummaries, type AnalysisTask } from "../api/datasets";
import { restoreGalleryJobs } from "../api/task-restoration";
import { createVisualization } from "../api/network";
import { ApiError } from "../api/client";
import { RDemoGallery } from "./RDemoGallery";
import { ArtifactPreview } from "./ArtifactPreview";

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
  if (task.task_type === "network" && result.analysisKind === "catalog_evidence") return [
    { key: "evidence_network", label: "中药—成分—靶点目录关系图", available: hasGraph, note: "使用已保存的本地目录快照；R 图合并同一对实体的重复连线，完整来源记录保留在分析任务中。" },
  ];
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
  const hasPathway = list(network.nodes).some(node => record(node).type === "pathway") && hasGraph;
  const graphs: Chart[] = [
    { key: "gene_pathway_network", label: "基因—通路证据网络", available: hasPathway, note: "仅绘制当前本地已登记的实际关系，最多 80 节点、500 边。" },
    { key: "gene_pathway_distribution", label: "基因通路分布图", available: hasPathway, note: "按每通路的唯一关联基因计数，不是富集显著性检验。" },
  ];
  if (task.task_type === "network") return [
    { key: "evidence_network", label: "中药—成分—靶点—疾病网络", available: hasGraph, note: "按类型分层；无证据关系不生成示意边。" },
    ...graphs,
  ];
  const go = record(result.externalGProfiler);
  return [
    { key: "proteomics_summary", label: "分析概览", available: true, note: "差异筛选、标识映射和通路数量汇总。" },
    ...ppiCharts, ...graphs,
    { key: "proteomics_go_kegg_bar", label: "GO / KEGG 富集条形图", available: go.status === "succeeded" && list(go.terms).length > 0, note: "GO:BP / CC / MF 与 KEGG，按 FDR 排序；数据来自 g:Profiler。" },
    reactomeChart,
  ];
}

export function RAnalysisGallery({ taskId }: { taskId: number }) {
  const [parent, setParent] = useState<AnalysisTask | null>(null);
  const [jobs, setJobs] = useState<Record<string, AnalysisTask>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const submissionInFlight = useRef(false);
  const [reload, setReload] = useState(0);
  const [pollFailures, setPollFailures] = useState(0);
  const [pollError, setPollError] = useState<string | null>(null);
  useEffect(() => {
    const current = ++generation.current;
    setParent(null); setJobs({}); setError(null); setBusy(null); setPollError(null); setPollFailures(0);
    Promise.allSettled([getAnalysisTask(taskId), getAnalysisTaskSummaries(1, taskId)]).then(async ([sourceRead, pageRead]) => {
      if (generation.current !== current) return;
      if (sourceRead.status === "rejected") throw sourceRead.reason;
      const source = sourceRead.value;
      if (source.id !== taskId) throw new Error("Parent identity mismatch");
      setParent(source);
      if (pageRead.status === "rejected") throw pageRead.reason;
      const page = pageRead.value;
      const restored = await restoreGalleryJobs(page.results, taskId, new Set(rChartCatalog(source).map(chart => chart.key)), page.next);
      if (generation.current !== current) return;
      setJobs(restored);
    }).catch(cause => { if (generation.current === current) setError(cause instanceof ApiError ? cause.message : "R 分析目录加载失败。"); });
    return () => { generation.current++; };
  }, [taskId, reload]);
  useEffect(() => {
    let active = true;
    const current = generation.current;
    const pending = Object.entries(jobs).filter(([, job]) => ["queued", "running"].includes(job.status));
    if (!pending.length) return;
    const timer = window.setTimeout(() => {
      void Promise.allSettled(pending.map(async ([key, job]) => {
        const latest = await getAnalysisTask(job.id);
        if (latest.id !== job.id || latest.task_type !== "visualization" || latest.parent_task !== taskId
          || latest.input_parameters.chartKey !== key) throw new Error("Figure identity mismatch");
        return [key, latest] as const;
      })).then(reads => {
        if (!active || generation.current !== current) return;
        const updates = reads.flatMap(read => read.status === "fulfilled" ? [read.value] : []);
        if (updates.length) setJobs(previous => ({ ...previous, ...Object.fromEntries(updates) }));
        const failure = reads.find(read => read.status === "rejected");
        if (failure?.status === "rejected") {
          setPollError(`${failure.reason instanceof ApiError ? failure.reason.message : "R 图表状态读取失败。"} 正在重试读取已有任务，不会重新绘图。`);
          setPollFailures(value => value + 1);
        } else { setPollError(null); setPollFailures(0); }
      });
    }, Math.min(1500 * 2 ** Math.min(pollFailures, 4), 12000));
    return () => { active = false; window.clearTimeout(timer); };
  }, [jobs, taskId, pollFailures]);
  async function renderChart(key: string) {
    const chart = parent ? rChartCatalog(parent).find(item => item.key === key) : null;
    if (submissionInFlight.current || !chart?.available || parent?.status !== "succeeded"
      || (jobs[key] && ["queued", "running", "succeeded"].includes(jobs[key].status))) return;
    submissionInFlight.current = true;
    const current = generation.current;
    setBusy(key); setError(null);
    try {
      const job = await createVisualization(taskId, key);
      if (job.task_type !== "visualization" || job.parent_task !== taskId
        || job.input_parameters.analysisKind !== "r_visualization" || job.input_parameters.chartKey !== key) throw new Error("Figure identity mismatch");
      if (generation.current === current) setJobs(previous => ({ ...previous, [key]: job }));
    } catch (cause) {
      if (generation.current === current) setError(cause instanceof ApiError ? cause.message : "图表任务创建失败。");
    } finally { submissionInFlight.current = false; if (generation.current === current) setBusy(null); }
  }
  if (parent && parent.status !== "succeeded") return null;
  const charts = parent ? rChartCatalog(parent) : [];
  return <section className="proteomics-result-section" aria-label="R 分析与网络图目录">
    <p className="page-kicker">R ANALYSIS · INPUT INSPIRED</p>
    <h3 className="section-title-sm">R 分析与网络图目录</h3>
    <p className="section-help">仅使用当前任务已保存的结果。缺少互作或通路数据时明确停用，不填充假关系。PPI 置信度在原查询中设置；生成图表不会重新向外部数据库提交数据。</p>
    {error && <div className="notice-error" role="alert"><p>{error}</p><button className="btn btn-secondary" type="button" disabled={busy !== null} onClick={() => setReload(value => value + 1)}>重新读取图表记录</button></div>}
    {pollError && <p className="notice-error" role="alert">{pollError}</p>}
    {!parent && !error && <p role="status">正在读取可用图表…</p>}
    {charts.map(chart => {
      const job = jobs[chart.key];
      const pending = Boolean(job && ["queued", "running"].includes(job.status));
      const value = record(job?.result);
      const artifacts = list(value.artifacts) as Artifact[];
      const svg = artifacts.find(item => item.format === "svg");
      return <div className="panel source-record" key={chart.key}>
        <h4>{chart.label}</h4><p className="section-help">{chart.note}</p>
        <button className="btn btn-secondary" type="button" disabled={!chart.available || busy !== null || pending || job?.status === "succeeded"} onClick={() => void renderChart(chart.key)}>
          {!chart.available ? "缺少所需分析数据" : busy === chart.key ? "正在提交…" : pending ? `后台绘图 ${job?.progress ?? 0}%` : job?.status === "succeeded" ? "已生成" : job?.status === "failed" ? "重试绘图" : "生成 R 图表"}
        </button>
        {job?.status === "failed" && <p className="notice-error" role="alert">{job.error_summary}</p>}
        <RDemoGallery chartKey={chart.key} />
        {job?.status === "succeeded" && <>
          <p className="section-help">任务 #{job.id} · {String(value.rendererVersion ?? "")} · 父分析 #{taskId}</p>
          {svg && <ArtifactPreview src={`${svg.downloadUrl}?inline=1`} alt={chart.label} />}
          <div className="source-record-actions">{artifacts.map(item => <a className="btn btn-secondary" key={item.id} href={item.downloadUrl}>下载 {item.format.toUpperCase()}</a>)}</div>
        </>}
      </div>;
    })}
  </section>;
}
