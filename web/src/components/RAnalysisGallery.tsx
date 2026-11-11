import { useEffect, useRef, useState } from "react";
import { getAnalysisTask, getAnalysisTaskSummaries, type AnalysisTask } from "../api/datasets";
import { restoreGalleryJobs } from "../api/task-restoration";
import { createVisualization } from "../api/network";
import { ApiError } from "../api/client";
import { RChartSource, RChartSourceProvider } from "./RChartSource";
import { SubviewTabs, type Subview } from "./SubviewTabs";
import { RChartViewer, hasInteractiveRenderer } from "./RChartViewer";

type Chart = { key: string; label: string; available: boolean; note: string; unavailableReason?: string; nextStep?: string };
type Artifact = { id: number; format: string; downloadUrl: string };
function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function list(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function finiteNumber(value: unknown): value is number { return typeof value === "number" && Number.isFinite(value); }
function namedCountRows(value: unknown, labelKey = "label", valueKey = "value") {
  return list(value).some(item => {
    const row = record(item);
    return typeof row[labelKey] === "string" && String(row[labelKey]).trim() && finiteNumber(row[valueKey]);
  });
}
function chart(key: string, label: string, available: boolean, note: string, unavailableReason: string, nextStep: string): Chart {
  return { key, label, available, note, ...(!available ? { unavailableReason, nextStep } : {}) };
}
function externalGap(task: AnalysisTask, source: Record<string, unknown>, provider: "STRING" | "Reactome" | "g:Profiler") {
  const flag = { STRING: "externalString", Reactome: "externalReactome", "g:Profiler": "externalGProfiler" }[provider];
  const savedState = ({
    disabled: "服务在本次分析时未启用",
    unavailable: "本次查询服务不可用，未取得成功结果",
    insufficient_identifiers: "本次查询可用的人类基因/蛋白标识不足",
    no_mapped_identifiers: "本次查询没有映射到可用的人类基因/蛋白标识",
    input_limit_exceeded: "本次查询的标识数量超过服务限制",
    no_interactions: "本次查询未返回符合条件的物理互作边",
    no_significant_terms: "本次查询没有显著的 GO/KEGG 条目",
    no_significant_pathways: "本次查询没有显著的 Reactome 通路",
  } as Record<string, string>)[String(source.status)];
  const nextStep = task.task_type === "proteomics"
    ? `核对可识别的人类基因/蛋白标识，在分析设置中单独同意 ${provider}，重新提交分析；成功结果会保存到新任务，当前图表不会自动调用外部服务。`
    : `核对当前查询的基因标识和服务状态，在网络药理分析中单独同意并重新查询 ${provider}；成功后再生成图表。`;
  return {
    unavailableReason: savedState ? `${provider}：${savedState}。`
      : task.task_type === "proteomics" && task.input_parameters?.[flag] === false
        ? `本次任务未启用 ${provider}，没有保存相应分析结果。`
        : `当前任务没有保存可绘制的 ${provider} 成功结果。`,
    nextStep,
  };
}
function verifyGalleryJob(job: AnalysisTask, parentId: number, key: string, expectedId?: number) {
  if (!Number.isSafeInteger(job.id) || job.id < 1 || (expectedId !== undefined && job.id !== expectedId)
    || job.task_type !== "visualization" || job.parent_task !== parentId
    || job.input_parameters.analysisKind !== "r_visualization" || job.input_parameters.chartKey !== key
    || Number(job.input_parameters.parentTaskId) !== parentId) throw new Error("Figure identity mismatch");
  if (job.status === "succeeded") {
    const result = record(job.result);
    if (result.taskId !== job.id || Number(result.parentTaskId) !== parentId || result.chartKey !== key) throw new Error("Figure result identity mismatch");
  }
}
export function rChartCatalog(task: AnalysisTask): Chart[] {
  const result = record(task.result);
  const network = record(result.network);
  const hasGraph = list(network.links).length > 0;
  const graphReason = "当前任务没有保存可绘制的目录证据连线；目录中存在实体不等于本次查询有关系。";
  const graphNext = "在药理检索中选择有来源关系的实体，保存或准备本次检索快照，再生成图表；不会补造缺失连线。";
  if (task.task_type === "network" && result.analysisKind === "catalog_evidence" && !result.queryType) return [
    chart("evidence_network", "中药—成分—靶点目录关系图", hasGraph, "使用已保存的本地目录快照；R 图合并同一对实体的重复连线，完整来源记录保留在分析任务中。", graphReason, graphNext),
  ];
  const ppi = task.task_type === "proteomics" ? record(result.externalString) : result;
  const hasPpi = ppi.source === "STRING" && ppi.networkType === "physical"
    && (ppi.status === "succeeded" || (ppi.status === undefined && ppi.analysisKind === "string_ppi")) && list(ppi.edges).length > 0;
  const ppiGap = externalGap(task, ppi, "STRING");
  if (ppi.status === "succeeded") ppiGap.unavailableReason = ppi.source !== "STRING" || ppi.networkType !== "physical"
    ? "当前保存的结果不是 STRING 物理互作，目录关系不能替代 PPI 边。"
    : "STRING 查询已完成，但当前任务没有保存物理互作边。";
  const ppiCharts: Chart[] = [
    chart("ppi_network", "STRING PPI 网络图", hasPpi, "需要已单独同意并成功返回的物理互作；节点大小为展示子图连接度。", ppiGap.unavailableReason, ppiGap.nextStep),
    chart("ppi_degree", "PPI 连接度排行", hasPpi, "按完整有效返回图的唯一邻居数排序，不是因果或核心蛋白结论。", ppiGap.unavailableReason, ppiGap.nextStep),
  ];
  if (task.task_type === "network" && result.analysisKind === "string_ppi") return ppiCharts;
  const reactome = task.task_type === "proteomics" ? record(result.externalReactome) : result;
  const reactomeGap = externalGap(task, reactome, "Reactome");
  const hasReactome = (reactome.status === "succeeded" || (reactome.status === undefined && reactome.analysisKind === "reactome_enrichment"))
    && list(reactome.pathways).some(item => {
      const row = record(item);
      return typeof row.name === "string" && row.name.trim() && finiteNumber(row.fdr) && row.fdr > 0 && row.fdr <= .05
        && finiteNumber(row.matchedEntities) && Number.isInteger(row.matchedEntities) && row.matchedEntities >= 1
        && finiteNumber(row.totalEntities) && Number.isInteger(row.totalEntities) && row.totalEntities >= row.matchedEntities;
    });
  if (reactome.status === "succeeded" || (reactome.status === undefined && reactome.analysisKind === "reactome_enrichment")) {
    reactomeGap.unavailableReason = "当前 Reactome 结果没有同时具备通路名称、0 < FDR ≤ 0.05、有效命中数及通路实体总数的条目。";
  }
  const reactomeChart = chart("reactome_enrichment", "Reactome 通路气泡图", hasReactome, "需要有效 FDR 和命中/通路实体数；不冒充 GO/KEGG 结果。", reactomeGap.unavailableReason, reactomeGap.nextStep);
  if (result.analysisKind === "reactome_enrichment") return [reactomeChart];
  if (!["proteomics", "network"].includes(task.task_type)) return [];
  if (result.analysisKind === "catalog_evidence" && result.queryType === "comparison") return [
    chart("catalog_summary", "名称对照数量概览", namedCountRows(result.catalogSummary), "按规范化比对键统计，同家族候选单列且不计入精确交集，不代表化学结构鉴定。", "当前名称对照快照没有保存有效的名称数量统计条目。", "重新提交检测列表与参考列表，并准备新的名称对照快照；已保存的合法零计数也可绘图。"),
  ];
  if (task.task_type === "network" && result.analysisKind === "catalog_evidence") return [
    chart("evidence_network", "检索圆形证据网络", hasGraph, "圆形网络；只绘制快照内实际登记关系，完整证据保留在来源快照。", graphReason, graphNext),
    chart("catalog_summary", "实体与证据概览", namedCountRows(result.catalogSummary), "按本地实体主键 / 关系主键去重计数，不合并同名异标识。", "当前检索快照没有保存有效的实体或证据数量统计。", "重新检索并准备新的目录快照；已有的合法零计数无需补数据即可绘图。"),
    chart("catalog_degree", result.queryType === "pathway" ? "通路注释分布" : "实体连接度分布", result.queryType === "pathway" ? namedCountRows(result.catalogCoverage) : hasGraph, "唯一邻居数 / 本地通路覆盖计数，不是核心靶点结论或富集显著性。", result.queryType === "pathway" ? "当前通路快照没有保存有效的靶点注释计数。" : graphReason, result.queryType === "pathway" ? "重新检索并准备通路快照；注释数为 0 的有效条目仍可绘制，此图不需要外部富集。" : graphNext),
  ];
  const nodeTypes = new Map<string, string>();
  for (const item of list(network.nodes)) {
    const node = record(item);
    if (typeof node.id === "string" && node.id && typeof node.label === "string" && node.label.trim() && typeof node.type === "string") nodeTypes.set(node.id, node.type);
  }
  const hasPathway = list(network.links).some(item => {
    const edge = record(item), left = typeof edge.source === "string" ? nodeTypes.get(edge.source) : undefined,
      right = typeof edge.target === "string" ? nodeTypes.get(edge.target) : undefined;
    return (left === "pathway" && ["target", "gene", "protein"].includes(String(right)))
      || (right === "pathway" && ["target", "gene", "protein"].includes(String(left)));
  });
  const pathwayReason = "当前任务没有保存基因/蛋白与通路之间的实际关联边；仅有通路名称或候选符号不能生成此图。";
  const pathwayNext = task.task_type === "proteomics"
    ? "核对输入的基因/蛋白标识及本地通路注释后重新分析；仅格式识别的候选符号不等于已验证靶点。"
    : "使用已登记基因—通路关系的查询重新生成分析快照；本地图不要求外部富集结果。";
  const graphs: Chart[] = [
    chart("gene_pathway_network", "基因—通路证据网络", hasPathway, "仅绘制当前本地已登记的实际关系，最多 80 节点、500 边。", pathwayReason, pathwayNext),
    chart("gene_pathway_distribution", "基因通路分布图", hasPathway, "按每通路的唯一关联基因计数，不是富集显著性检验。", pathwayReason, pathwayNext),
  ];
  if (task.task_type === "network") return [
    chart("evidence_network", "中药—成分—靶点—疾病网络", hasGraph, "圆形网络；无证据关系不生成示意边。", graphReason, graphNext),
    ...["overlap", "components", "pathways"].map((key, index) => chart(key, ["靶点比对统计", "成分靶点覆盖", "本地通路注释分布"][index],
      namedCountRows(record(result.charts)[key], "name", key === "overlap" ? "value" : "targets"), "R 交互点图展示已保存的查询统计；不同集合不相加作总数，本地注释不冒充富集结果。",
      ["当前网络药理任务没有保存有效的中药—疾病靶点比对计数。", "当前任务没有保存有效的成分靶点覆盖计数。", "当前任务没有保存有效的本地通路靶点注释计数。"][index],
      "核对中药、疾病名称和本地关系证据，重新完成网络药理分析；已保存的合法零计数不会因值为 0 被禁用。")),
    ...graphs,
  ];
  const go = record(result.externalGProfiler);
  const goGap = externalGap(task, go, "g:Profiler");
  const hasGo = go.status === "succeeded" && list(go.terms).some(item => {
    const term = record(item);
    return typeof term.name === "string" && term.name.trim() && ["GO:BP", "GO:CC", "GO:MF", "KEGG"].includes(String(term.source))
      && finiteNumber(term.adjustedPValue) && term.adjustedPValue > 0 && term.adjustedPValue <= .05;
  });
  if (go.status === "succeeded") goGap.unavailableReason = "当前 GO/KEGG 结果没有名称、类别完整且 0 < FDR ≤ 0.05 的显著条目。";
  const hasTopNodes = list(result.topNodes).slice(0, 30).some(item => {
    const row = record(item);
    return typeof row.symbol === "string" && row.symbol.trim() && finiteNumber(row.degree);
  });
  const summary = record(result.summary);
  const hasSummary = ["selectedRowCount", "normalizedCount", "databaseMappedCount", "unmappedCount", "candidateOverlapCount", "pathwayCount"].some(key => finiteNumber(summary[key]));
  return [
    chart("proteomics_summary", "分析概览", hasSummary, "差异筛选、标识映射和通路数量汇总；合法的零计数仍可绘制。", "当前任务没有保存可绘制的差异筛选、标识映射或通路数量统计。", "重新读取该任务；若统计仍缺失，请使用原数据集重新提交蛋白组学分析。"),
    chart("proteomics_top_nodes", "本地通路网络连接度", hasTopNodes, "使用本任务保存的候选符号与本地通路关联数；degree 为 0 仍可绘制，表示未登记关联。候选符号可包含仅格式识别项，不等于已验证靶点或核心蛋白。", "当前任务没有保存符号及有限数值 degree 完整的候选条目。", "先查看“验证与通路”的候选表，核对输入标识并重新分析；已有 degree 为 0 的有效条目无需补造通路即可绘图。"),
    ...ppiCharts, ...graphs,
    chart("proteomics_go_kegg_bar", "GO / KEGG 富集显著性点图", hasGo, "GO:BP / CC / MF 与 KEGG，按 FDR 排序；数据来自 g:Profiler。", goGap.unavailableReason, goGap.nextStep),
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
  const submissionInFlight = useRef(false);
  const [reload, setReload] = useState(0);
  const [pollFailures, setPollFailures] = useState(0);
  const [pollError, setPollError] = useState<string | null>(null);
  const [historyReady, setHistoryReady] = useState(false);
  useEffect(() => {
    const current = ++generation.current;
    setParent(null); setJobs({}); setError(null); setBusy(null); setPollError(null); setPollFailures(0); setHistoryReady(false);
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
      for (const [key, job] of Object.entries(restored)) verifyGalleryJob(job, taskId, key);
      setJobs(restored); setHistoryReady(true);
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
        verifyGalleryJob(latest, taskId, key, job.id);
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
    if (submissionInFlight.current || !historyReady || !chart?.available || parent?.status !== "succeeded"
      || (jobs[key] && ["queued", "running"].includes(jobs[key].status))) return;
    submissionInFlight.current = true;
    const current = generation.current;
    setBusy(key); setError(null);
    try {
      const job = jobs[key]
        ? await createVisualization(taskId, key, { regenerate: true })
        : await createVisualization(taskId, key);
      verifyGalleryJob(job, taskId, key);
      if (generation.current === current) setJobs(previous => ({ ...previous, [key]: job }));
    } catch (cause) {
      if (generation.current === current) setError(cause instanceof ApiError ? cause.message : "图表任务创建失败。");
    } finally { submissionInFlight.current = false; if (generation.current === current) setBusy(null); }
  }
  if (parent && parent.status !== "succeeded") return null;
  const charts = parent ? rChartCatalog(parent) : [];
  return <RChartSourceProvider source={chartSource} onChange={setChartSource}><section className="proteomics-result-section" aria-label="图表与网络">

    <h3 className="section-title-sm">图表与网络</h3>

    {error && <div className="notice-error" role="alert"><p>{error}</p><button className="btn btn-secondary" type="button" disabled={busy !== null} onClick={() => setReload(value => value + 1)}>重新读取图表记录</button></div>}
    {pollError && <p className="notice-error" role="alert">{pollError}</p>}
    {!parent && !error && <p role="status">正在读取可用图表…</p>}
    <SubviewTabs label="选择 R 分析图表" value={selectedKey || additionalCharts[0]?.key || charts.find(chart => chart.available)?.key || ""} onChange={setSelectedKey} views={[...additionalCharts, ...charts.map(chart => {
      const job = jobs[chart.key];
      const pending = Boolean(job && ["queued", "running"].includes(job.status));
      const value = record(job?.result);
      const previousRenderTaskId = job?.input_parameters.previousRenderTaskId ?? value.previousRenderTaskId;
      const artifacts = list(value.artifacts) as Artifact[];
      const svg = artifacts.find(item => item.format === "svg");
      const html = artifacts.find(item => item.format === "html");
      return { key: chart.key, label: chart.label, content: <div className="panel source-record">
        <h4>{chart.label}</h4><p className="section-help">{chart.note}</p>
        <RChartSource key={chart.key} chartKey={chart.key}>
        <button className="btn btn-secondary" type="button" disabled={!historyReady || !chart.available || busy !== null || pending} onClick={() => void renderChart(chart.key)}>
          {!chart.available ? "缺少所需分析数据" : busy === chart.key ? "正在提交…" : pending ? `后台绘图 ${job?.progress ?? 0}%` : job?.status === "succeeded" ? "重新运行 R 绘图" : job?.status === "failed" ? "重试绘图" : "生成 R 图表"}
        </button>
        {!chart.available && <div className="notice-info" role="status"><p>{chart.unavailableReason}</p><p>下一步：{chart.nextStep}</p></div>}
        {job && <div className="source-record-actions">
          <a className="btn btn-secondary" href={`/tasks/${job.id}`}>查看绘图任务 #{job.id}</a>
          {typeof previousRenderTaskId === "number" && Number.isSafeInteger(previousRenderTaskId) && previousRenderTaskId > 0 && previousRenderTaskId !== job.id
            && <a className="btn btn-secondary" href={`/tasks/${previousRenderTaskId}`}>查看上一版图表（任务 #{previousRenderTaskId}）</a>}
        </div>}
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
