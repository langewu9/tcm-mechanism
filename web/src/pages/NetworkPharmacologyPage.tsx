import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { Activity, ArrowLeft, Network, RefreshCw } from "lucide-react";
import { getAnalysisTask, getAnalysisTaskSummaries, type AnalysisTask } from "../api/datasets";
import { createVisualization, runNetworkPharmacology, runReactomeEnrichment, runStringNetwork, type NetworkPharmacologyResult, type ReactomeEnrichmentResult as ReactomeResult } from "../api/network";
import { ApiError } from "../api/client";
import { KnowledgeNetworkGraph } from "../components/KnowledgeNetworkGraph";
import { NetworkResultDownloads } from "../components/NetworkResultDownloads";
import { ReactomeEnrichmentResult } from "../components/ReactomeEnrichmentResult";
import { StringTaskResult } from "../components/StringNetworkResult";
import { NetworkPharmacologyCharts } from "../components/NetworkPharmacologyCharts";
import { RAnalysisGallery } from "../components/RAnalysisGallery";
import { RChartViewer, hasInteractiveRenderer } from "../components/RChartViewer";
import { TargetIntersectionFigure, TargetIntersectionNotice, intersectionState } from "../components/TargetIntersectionFigure";
import { waitForCompleteTask } from "../api/complete-evidence";

type QueryTask = { sourceTaskId: number; task: AnalysisTask };

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "请求未完成，请稍后重试。";
}

function verifyTaskSource(task: AnalysisTask, sourceTaskId: number, kind: string) {
  if (task.parent_task !== sourceTaskId || task.input_parameters.analysisKind !== kind) {
    throw new ApiError("分析任务与当前查询的来源关联不一致，暂不展示该结果。", "TASK_SOURCE_MISMATCH", null, null, 502);
  }
}

function isParentId(value: unknown, parentId: number) {
  return value === parentId || value === String(parentId);
}

function verifyOverlapTask(task: AnalysisTask, sourceTaskId: number, requestedId?: number) {
  if (!Number.isSafeInteger(task.id) || task.id < 1 || (requestedId !== undefined && task.id !== requestedId)
    || task.task_type !== "visualization" || task.parent_task !== sourceTaskId
    || task.input_parameters.analysisKind !== "r_visualization" || task.input_parameters.chartKey !== "overlap"
    || !isParentId(task.input_parameters.parentTaskId, sourceTaskId)) {
    throw new ApiError("R 图表任务与当前分析的来源关联不一致，暂不展示该图表。", "TASK_SOURCE_MISMATCH", null, null, 502);
  }
  if (task.status === "succeeded") {
    const value = task.result as Record<string, unknown>;
    if (value.taskId !== task.id || !isParentId(value.parentTaskId, sourceTaskId) || value.chartKey !== "overlap") {
      throw new ApiError("R 图表结果与请求的任务编号不一致，暂不展示该图表。", "TASK_SOURCE_MISMATCH", null, null, 502);
    }
  }
}

async function restoreOverlapTask(sourceTaskId: number, isActive: () => boolean): Promise<AnalysisTask | null> {
  const seen = new Set<number>();
  for (let pageNumber = 1; isActive(); pageNumber++) {
    // Only use the authenticated summaries endpoint; never follow a supplied next URL.
    const page = await getAnalysisTaskSummaries(pageNumber, sourceTaskId);
    if (!isActive()) return null;
    let newRows = 0;
    for (const summary of page.results) {
      if (!seen.has(summary.id)) { seen.add(summary.id); newRows++; }
      if (!Number.isSafeInteger(summary.id) || summary.id < 1 || summary.task_type !== "visualization"
        || summary.parent_task !== sourceTaskId || summary.display_parameters?.analysisKind !== "r_visualization"
        || summary.display_parameters.chartKey !== "overlap"
        || !isParentId(summary.display_parameters.parentTaskId, sourceTaskId)) continue;
      const task = await getAnalysisTask(summary.id);
      if (!isActive()) return null;
      verifyOverlapTask(task, sourceTaskId, summary.id);
      return task;
    }
    if (!page.next) return null;
    if (!newRows) throw new Error("R 图表历史分页响应无效，请重新读取。");
  }
  return null;
}

export function NetworkPharmacologyPage() {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const savedNetworkId = params.get("networkTask");
  const [herb, setHerb] = useState("");
  const [disease, setDisease] = useState("");
  const [result, setResult] = useState<NetworkPharmacologyResult | null>(null);
  const [pathwayBinding, setPathwayBinding] = useState<QueryTask | null>(null);
  const [stringBinding, setStringBinding] = useState<QueryTask | null>(null);
  const [visualizationBinding, setVisualizationBinding] = useState<QueryTask | null>(null);
  const [shareWithReactome, setShareWithReactome] = useState(false);
  const [shareWithString, setShareWithString] = useState(false);
  const [requiredScore, setRequiredScore] = useState(700);
  const [busy, setBusy] = useState(false);
  const [localProgress, setLocalProgress] = useState("");
  const [pathwaySubmitting, setPathwaySubmitting] = useState(false);
  const [stringSubmitting, setStringSubmitting] = useState(false);
  const [visualizationSubmitting, setVisualizationSubmitting] = useState(false);
  const [visualizationHistorySource, setVisualizationHistorySource] = useState<number | null>(null);
  const [visualizationHistoryLoading, setVisualizationHistoryLoading] = useState(false);
  const [visualizationHistoryError, setVisualizationHistoryError] = useState<string | null>(null);
  const [visualizationHistoryReload, setVisualizationHistoryReload] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [pollingError, setPollingError] = useState<string | null>(null);
  const [caseContext, setCaseContext] = useState<{ caseId: number; candidateId: number } | null>(null);
  const mounted = useRef(false);
  const localSubmissionInFlight = useRef(false);
  const submittedTaskId = useRef<number | null>(null);
  const queryGeneration = useRef(0);
  const currentSourceTaskId = useRef<number | null>(null);
  const submittingGeneration = useRef<{ pathway: number | null; string: number | null; visualization: number | null }>({ pathway: null, string: null, visualization: null });
  const pathwayTask = pathwayBinding?.sourceTaskId === result?.taskId ? pathwayBinding?.task ?? null : null;
  const stringTask = stringBinding?.sourceTaskId === result?.taskId ? stringBinding?.task ?? null : null;
  const reactomeResult = pathwayTask?.status === "succeeded" ? pathwayTask.result as unknown as ReactomeResult : null;
  const visualizationTask = visualizationBinding?.sourceTaskId === result?.taskId ? visualizationBinding?.task ?? null : null;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; queryGeneration.current += 1; currentSourceTaskId.current = null; };
  }, []);

  function isCurrentQuery(generation: number, sourceTaskId: number) {
    return mounted.current && queryGeneration.current === generation && currentSourceTaskId.current === sourceTaskId;
  }

  useEffect(() => {
    if (!savedNetworkId || (localSubmissionInFlight.current && savedNetworkId === String(submittedTaskId.current))) return;
    const generation = ++queryGeneration.current;
    let active = true;
    currentSourceTaskId.current = null;
    submittingGeneration.current.visualization = null;
    setVisualizationSubmitting(false);
    setVisualizationBinding(null); setVisualizationHistorySource(null); setVisualizationHistoryError(null);
    setResult(null); setError(null); setBusy(true);
    setLocalProgress("正在读取已保存的本地分析…");
    async function restore() {
      try {
        if (!/^[1-9]\d*$/.test(savedNetworkId!) || !Number.isSafeInteger(Number(savedNetworkId))) throw new Error("网络药理任务编号无效。");
        const source = await getAnalysisTask(Number(savedNetworkId));
        if (!active || !mounted.current || queryGeneration.current !== generation) return;
        if (source.id !== Number(savedNetworkId) || source.task_type !== "network" || source.input_parameters.analysisKind !== "network_pharmacology") throw new Error("该任务不是网络药理分析，请从对应目录查询打开。");
        const task = await waitForCompleteTask(source, {
          isActive: () => active && mounted.current && queryGeneration.current === generation,
          onTask: current => setLocalProgress(`任务 #${current.id} · ${current.status} · ${current.progress}%`),
          onReadError: () => setLocalProgress("任务进度读取失败，正在重试读取已有任务…"),
        });
        if (!active || !mounted.current || queryGeneration.current !== generation) return;
        if (task.id !== source.id || task.task_type !== "network" || task.input_parameters.analysisKind !== "network_pharmacology") throw new Error("历史任务来源不一致，请重新读取。");
        const data = task.result as unknown as NetworkPharmacologyResult;
        if (!data.summary || !Array.isArray(data.targets) || !data.network) throw new Error("任务没有可展示的网络药理结果。");
        currentSourceTaskId.current = task.id;
        setResult({ ...data, taskId: task.id }); setHerb(data.summary.herb); setDisease(data.summary.disease);
        setVisualizationHistorySource(task.id);
      } catch (cause) { if (active && mounted.current && queryGeneration.current === generation) setError(cause instanceof Error ? cause.message : "历史分析读取失败，请刷新重试。"); }
      finally { if (active && mounted.current && queryGeneration.current === generation) setBusy(false); }
    }
    void restore();
    return () => { active = false; };
  }, [savedNetworkId]);

  useEffect(() => {
    if (visualizationHistorySource === null) { setVisualizationHistoryLoading(false); return; }
    const sourceTaskId = visualizationHistorySource;
    const generation = queryGeneration.current;
    let active = true;
    const isActive = () => active && isCurrentQuery(generation, sourceTaskId);
    setVisualizationHistoryLoading(true); setVisualizationHistoryError(null);
    void restoreOverlapTask(sourceTaskId, isActive).then(task => {
      if (isActive()) setVisualizationBinding(task ? { sourceTaskId, task } : null);
    }).catch(() => {
      if (isActive()) setVisualizationHistoryError("历史 R 图表读取失败，主分析结果已保留。可重新读取历史图表，不会自动重新绘图。");
    }).finally(() => { if (isActive()) setVisualizationHistoryLoading(false); });
    return () => { active = false; };
  }, [visualizationHistorySource, visualizationHistoryReload]);

  useEffect(() => {
    if (!location.state || typeof location.state !== "object") return;
    const state = location.state as Record<string, unknown>;
    if (typeof state.herb === "string") setHerb(state.herb);
    if (typeof state.disease === "string") setDisease(state.disease);
    if (typeof state.sourceCaseId === "number" && typeof state.sourceCandidateId === "number") {
      setCaseContext({ caseId: state.sourceCaseId, candidateId: state.sourceCandidateId });
    } else {
      setCaseContext(null);
    }
  }, [location.key, location.state]);

  useEffect(() => {
    const generation = queryGeneration.current;
    let active = true;
    const pending = [
      { binding: pathwayBinding, update: setPathwayBinding, kind: "reactome_enrichment" },
      { binding: stringBinding, update: setStringBinding, kind: "string_ppi" },
      { binding: visualizationBinding, update: setVisualizationBinding, kind: "r_visualization" },
    ].filter(({ binding }) => binding && binding.sourceTaskId === result?.taskId && ["queued", "running"].includes(binding.task.status));
    if (!pending.length) { setPollingError(null); return; }
    let timer: number;
    async function poll() {
      const reads = await Promise.allSettled(pending.map(async ({ binding, update, kind }) => {
        if (!binding || !active || !isCurrentQuery(generation, binding.sourceTaskId)) return false;
        try {
          const latest = await getAnalysisTask(binding.task.id);
          if (!active || !isCurrentQuery(generation, binding.sourceTaskId)) return false;
          if (kind === "r_visualization") verifyOverlapTask(latest, binding.sourceTaskId, binding.task.id);
          else {
            if (latest.id !== binding.task.id) throw new Error("任务编号与读取请求不一致。");
            verifyTaskSource(latest, binding.sourceTaskId, kind);
          }
          update((current) => current?.sourceTaskId === binding.sourceTaskId && current.task.id === latest.id ? { sourceTaskId: binding.sourceTaskId, task: latest } : current);
          return true;
        } catch (cause) {
          if (active && isCurrentQuery(generation, binding.sourceTaskId)) setPollingError(`${errorMessage(cause)} 正在重试读取已有任务。`);
          return false;
        }
      }));
      if (active && mounted.current && queryGeneration.current === generation && reads.every((read) => read.status === "fulfilled" && read.value)) setPollingError(null);
      // A transient read failure must keep polling the existing task, without resubmitting it.
      if (active && mounted.current && queryGeneration.current === generation) timer = window.setTimeout(() => void poll(), 1500);
    }
    timer = window.setTimeout(() => void poll(), 1500);
    return () => { active = false; window.clearTimeout(timer); };
  }, [pathwayBinding, stringBinding, visualizationBinding, result?.taskId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (localSubmissionInFlight.current) return;
    localSubmissionInFlight.current = true;
    submittedTaskId.current = null;
    const generation = ++queryGeneration.current;
    currentSourceTaskId.current = null;
    submittingGeneration.current = { pathway: null, string: null, visualization: null };
    setBusy(true);
    setLocalProgress("正在提交完整本地分析…");
    setError(null);
    setPollingError(null);
    setResult(null);
    setPathwayBinding(null);
    setStringBinding(null);
    setVisualizationBinding(null);
    setVisualizationHistorySource(null);
    setVisualizationHistoryError(null);
    setVisualizationHistoryLoading(false);
    setPathwaySubmitting(false);
    setStringSubmitting(false);
    setVisualizationSubmitting(false);
    setShareWithReactome(false);
    setShareWithString(false);
    let rememberedTask = 0;
    try {
      const latest = await runNetworkPharmacology({
        herb,
        disease,
        ...(caseContext ? { source_case_id: caseContext.caseId, source_candidate_id: caseContext.candidateId } : {}),
      }, {
        isActive: () => mounted.current && queryGeneration.current === generation,
        onTask: task => { if (mounted.current && queryGeneration.current === generation) {
          setLocalProgress(`任务 #${task.id} · ${task.status === "queued" ? "排队中" : task.status === "running" ? "正在读取完整证据" : "已完成"} · ${task.progress}%`);
          if (rememberedTask !== task.id) { rememberedTask = task.id; submittedTaskId.current = task.id; setParams(current => { const next = new URLSearchParams(current); next.set("networkTask", String(task.id)); return next; }, { replace: true }); }
        } },
        onReadError: () => { if (mounted.current && queryGeneration.current === generation) setLocalProgress("任务进度暂时读取失败，正在重试读取已有任务…"); },
      });
      if (mounted.current && queryGeneration.current === generation) {
        currentSourceTaskId.current = latest.taskId;
        setResult(latest);
      }
    } catch (cause) {
      if (mounted.current && queryGeneration.current === generation) setError(cause instanceof Error ? cause.message : errorMessage(cause));
    } finally {
      localSubmissionInFlight.current = false;
      if (mounted.current && queryGeneration.current === generation) setBusy(false);
    }
  }

  async function requestPathways() {
    if (!result || !shareWithReactome || pathwaySubmitting || result.targets.length > 500 || result.limits.targetsTruncated || Boolean(pathwayTask && ["queued", "running"].includes(pathwayTask.status))) return;
    const generation = queryGeneration.current;
    const sourceTaskId = result.taskId;
    if (!isCurrentQuery(generation, sourceTaskId) || submittingGeneration.current.pathway === generation) return;
    submittingGeneration.current.pathway = generation;
    setError(null);
    setPathwaySubmitting(true);
    setShareWithReactome(false);
    setPathwayBinding(null);
    try {
      const task = await runReactomeEnrichment(sourceTaskId);
      verifyTaskSource(task, sourceTaskId, "reactome_enrichment");
      if (isCurrentQuery(generation, sourceTaskId)) setPathwayBinding({ sourceTaskId, task });
    } catch (cause) { if (isCurrentQuery(generation, sourceTaskId)) setError(errorMessage(cause)); }
    finally {
      if (submittingGeneration.current.pathway === generation) submittingGeneration.current.pathway = null;
      if (isCurrentQuery(generation, sourceTaskId)) setPathwaySubmitting(false);
    }
  }

  async function requestString() {
    if (!result || !shareWithString || stringSubmitting || result.targets.length > 200 || result.limits.targetsTruncated || Boolean(stringTask && ["queued", "running"].includes(stringTask.status))) return;
    const generation = queryGeneration.current;
    const sourceTaskId = result.taskId;
    if (!isCurrentQuery(generation, sourceTaskId) || submittingGeneration.current.string === generation) return;
    submittingGeneration.current.string = generation;
    setError(null);
    setStringSubmitting(true);
    setShareWithString(false);
    setStringBinding(null);
    try {
      const task = await runStringNetwork(sourceTaskId, requiredScore);
      verifyTaskSource(task, sourceTaskId, "string_ppi");
      if (isCurrentQuery(generation, sourceTaskId)) setStringBinding({ sourceTaskId, task });
    } catch (cause) { if (isCurrentQuery(generation, sourceTaskId)) setError(errorMessage(cause)); }
    finally {
      if (submittingGeneration.current.string === generation) submittingGeneration.current.string = null;
      if (isCurrentQuery(generation, sourceTaskId)) setStringSubmitting(false);
    }
  }

  async function requestVisualization() {
    if (!result || !intersectionState(result).comparable || visualizationSubmitting || visualizationHistoryLoading || Boolean(visualizationTask && ["queued", "running"].includes(visualizationTask.status))) return;
    const generation = queryGeneration.current;
    const sourceTaskId = result.taskId;
    if (!isCurrentQuery(generation, sourceTaskId) || submittingGeneration.current.visualization === generation) return;
    submittingGeneration.current.visualization = generation;
    setError(null);
    setVisualizationSubmitting(true);
    try {
      const task = visualizationTask
        ? await createVisualization(sourceTaskId, "overlap", { regenerate: true })
        : await createVisualization(sourceTaskId, "overlap");
      verifyOverlapTask(task, sourceTaskId);
      if (isCurrentQuery(generation, sourceTaskId)) setVisualizationBinding({ sourceTaskId, task });
    } catch (cause) { if (isCurrentQuery(generation, sourceTaskId)) setError(errorMessage(cause)); }
    finally {
      if (submittingGeneration.current.visualization === generation) submittingGeneration.current.visualization = null;
      if (isCurrentQuery(generation, sourceTaskId)) setVisualizationSubmitting(false);
    }
  }

  return <>

      <div className="page-heading"><div className="page-heading-copy"><h1 className="page-title">中药—疾病靶点交集</h1><p className="page-description">在已导入的本地知识目录中匹配中药成分靶点和疾病靶点，展示关系证据与来源版本。</p></div><Link to="/" className="btn btn-secondary"><ArrowLeft size={16} />返回首页</Link></div>
      {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
      {busy && <p className="section-help" role="status">{localProgress}</p>}
      {pollingError && <div className="notice-error workspace-notice" role="status">{pollingError}</div>}
      <div className="case-workspace-grid workspace-split">
        <form className="panel case-form" onSubmit={(event) => void submit(event)}>
          <div className="panel-header"><div><h2 className="section-title-sm">设置查询条件</h2><p className="section-help">最多输入 12 味中药或方剂；名称需与已导入目录匹配，方剂会沿带来源版本的组成关系展开。</p></div><span className="page-heading-icon"><Network size={19} /></span></div>
          <div className="case-form-fields">
            <label className="form-label" htmlFor="network-herb">中药或方剂名称<textarea className="field case-textarea" id="network-herb" value={herb} onChange={(event) => setHerb(event.target.value)} placeholder="例如：黄芩、丹参，或麦门冬汤" required /></label>
            <label className="form-label" htmlFor="network-disease">疾病名称<input className="field" id="network-disease" value={disease} onChange={(event) => setDisease(event.target.value)} placeholder="例如：肺纤维化" required /></label>
          </div>
          <div className="case-form-footer"><p>{caseContext ? `来源：已确认医案 #${caseContext.caseId} 中的方剂候选。` : "结果只是数据库关联证据，不代表因果或临床结论。"}</p><button className="btn btn-primary" type="submit" disabled={busy}>{busy ? <RefreshCw size={15} className="spin" /> : <Activity size={15} />}{busy ? "正在计算…" : "计算本地交集"}</button></div>
        </form>
        <section className="case-list" aria-live="polite">
          {!result ? <div className="panel empty-state"><Network size={27} /><strong>等待查询条件</strong><p>数据会在本地知识目录中检索，不会调用外部服务。</p></div> : <>
            <div className="case-list-heading"><div><h2 className="section-title-sm">分析任务 #{result.taskId}</h2></div><span className={`status-badge ${intersectionState(result).comparable && !intersectionState(result).partial ? "status-success" : "status-pending"}`}>{intersectionState(result).badge} · 已保存</span></div>
            <div className="panel proteomics-result-panel">
              <TargetIntersectionNotice result={result} onDiseaseSelect={(label) => {
                if (!isCurrentQuery(queryGeneration.current, result.taskId) || localSubmissionInFlight.current) return;
                queryGeneration.current += 1; currentSourceTaskId.current = null;
                setDisease(label); setResult(null); setPathwayBinding(null); setStringBinding(null); setVisualizationBinding(null);
                setVisualizationHistorySource(null); setVisualizationHistoryLoading(false); setVisualizationHistoryError(null);
                setShareWithReactome(false); setShareWithString(false); setPollingError(null); setError(null);
              }} />
              <TargetIntersectionFigure result={result} />
              <div className="source-record-actions"><button className="btn btn-secondary" type="button" disabled={!intersectionState(result).comparable || visualizationSubmitting || visualizationHistoryLoading || Boolean(visualizationTask && ["queued", "running"].includes(visualizationTask.status))} onClick={() => void requestVisualization()}>{visualizationSubmitting ? "正在提交…" : visualizationTask && ["queued", "running"].includes(visualizationTask.status) ? "后台绘图中…" : visualizationTask?.status === "succeeded" ? "重新运行 R 绘图" : visualizationTask?.status === "failed" ? "重试绘图" : "生成 R 图表"}</button></div>
              {visualizationHistoryLoading && <p className="section-help" role="status">正在读取已保存的 R 图表…</p>}
              {visualizationHistoryError && <div className="notice-error" role="alert"><p>{visualizationHistoryError}</p><button className="btn btn-secondary" type="button" disabled={visualizationSubmitting || visualizationHistoryLoading} onClick={() => setVisualizationHistoryReload(value => value + 1)}>重新读取历史 R 图表</button></div>}
              {visualizationTask && <VisualizationResult task={visualizationTask} />}
              <div className="proteomics-metrics">
                <Metric label="已返回中药靶点" value={result.summary.herbTargetCount} />
                <Metric label="已返回疾病靶点" value={result.summary.unmatchedDiseases.length ? "待匹配" : result.summary.diseaseTargetCount} />
                <Metric label="原始实体交集" value={intersectionState(result).comparable ? result.summary.strictIntersectionCount : "待核验"} />
                <Metric label="疾病—中药直接关联" value={result.summary.directAssociationTargetCount} />
                <Metric label="候选靶点" value={result.summary.candidateTargetCount} />
                <Metric label="关联成分" value={result.summary.componentCount} />
              </div>
              <NetworkResultDownloads result={result} />
              <RAnalysisGallery key={`network-gallery-${result.taskId}`} taskId={result.taskId} additionalCharts={[{ key: "query-statistics", label: "查询统计", content: <NetworkPharmacologyCharts key={`statistics-${result.taskId}`} result={result} reactome={reactomeResult} /> }]} />
              <details className="raw-details"><summary>查看备用证据链图（节点与来源详情）</summary>
                <KnowledgeNetworkGraph network={result.network} knownTruncated={result.limits.nodesTruncated || result.limits.linksTruncated || result.limits.targetsTruncated} />
              </details>
              {result.summary.matchedFormulas?.length ? <p className="section-help">方剂 {result.summary.matchedFormulas.join("、")} 已按本地组成关系展开为中药：{result.summary.matchedHerbs.join("、") || "暂无可追溯组成"}。</p> : null}
              {result.targets.length ? <div className="case-list-items">{result.targets.map((target, index) => <article className="panel source-record" key={`${target.normalizedTarget}-${index}`}>
                <div className="case-record-top"><div><h3>{target.target} <span className="status-badge status-warning">{target.matchType}</span></h3><p className="section-help">成分：{target.components.join("、") || "无中药成分证据"} · 通路：{target.pathways.join("、") || "无通路注释"}</p></div></div>
                <p className="section-help">中药证据 {target.herbEvidenceCount} 条 · 疾病证据 {target.diseaseEvidenceCount} 条 · 直接关联 {target.directEvidenceCount} 条</p>
                <ul className="proteomics-pathways">{target.sources.slice(0, 8).map((source, index) => <li key={`${source.sourceRecordId}-${index}`}><strong>{source.source} · {source.sourceVersion}</strong><span>{source.relationType} / {source.evidenceType} / {source.sourceRecordId}</span></li>)}</ul>
              </article>)}</div> : <div className="panel empty-state"><strong>{intersectionState(result).badge}</strong><p>{intersectionState(result).message}</p></div>}
              {(result.limits.nodesTruncated || result.limits.targetsTruncated || result.limits.linksTruncated) && <p className="section-help">页面网络图和靶点表可能只展示部分记录；完整证据以该任务的冻结导出为准。</p>}
              {result.targets.length >= 2 && <section className="case-form-fields external-analysis-options" aria-label="可选外部分析">
                <label className="proteomics-consent"><input type="checkbox" checked={shareWithReactome} onChange={(event) => setShareWithReactome(event.target.checked)} /><span><strong>同意提交基因标识到 MyGene.info 与 Reactome</strong><small>仅提交当前页面列出的候选靶点，最多 500 个；不提交医案或完整数据文件。</small></span></label>
                <div className="source-record-actions"><button className="btn btn-secondary" type="button" disabled={!shareWithReactome || pathwaySubmitting || result.targets.length > 500 || result.limits.targetsTruncated || Boolean(pathwayTask && ["queued", "running"].includes(pathwayTask.status))} onClick={() => void requestPathways()}>{pathwaySubmitting ? "正在创建 Reactome 任务…" : "Reactome 通路富集"}</button>{result.targets.length > 500 || result.limits.targetsTruncated ? <span className="section-help">Reactome 最多接收 500 个完整显示的靶点；当前结果过多，请缩小范围。</span> : null}</div>
                {pathwayTask && <ReactomeEnrichmentResult task={pathwayTask} source={result} />}
                <label className="proteomics-consent"><input type="checkbox" checked={shareWithString} onChange={(event) => setShareWithString(event.target.checked)} /><span><strong>同意提交基因标识到 STRING</strong><small>仅提交当前页面列出的候选靶点；STRING 物理互作网络可能与功能关联网络不同。</small></span></label>
                <label className="form-label">最低置信度<select className="field" value={requiredScore} onChange={(event) => setRequiredScore(Number(event.target.value))}><option value={400}>中等（400）</option><option value={700}>高（700）</option><option value={900}>最高（900）</option></select></label>
                <div className="source-record-actions"><button className="btn btn-secondary" type="button" disabled={!shareWithString || stringSubmitting || result.targets.length > 200 || result.limits.targetsTruncated || Boolean(stringTask && ["queued", "running"].includes(stringTask.status))} onClick={() => void requestString()}>{stringSubmitting ? "正在创建 STRING 任务…" : "STRING PPI 网络"}</button>{result.targets.length > 200 || result.limits.targetsTruncated ? <span className="section-help">STRING 最多接收 200 个完整显示的靶点；当前结果过多，请缩小范围。</span> : null}</div>
                {stringTask && <StringTaskResult task={stringTask} sourceTaskId={result.taskId} />}
                {stringTask?.status === "succeeded" && <RAnalysisGallery key={`string-gallery-${stringTask.id}`} taskId={stringTask.id} />}
              </section>}
              {pathwayTask?.status === "succeeded" && <RAnalysisGallery key={`reactome-gallery-${pathwayTask.id}`} taskId={pathwayTask.id} />}
            </div>
          </>}
        </section>
      </div>

  </>;
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return <div className="proteomics-metric"><span>{label}</span><strong>{typeof value === "number" ? value.toLocaleString("zh-CN") : value}</strong></div>;
}

function VisualizationResult({ task }: { task: AnalysisTask }) {
  const previousRenderTaskId = task.input_parameters.previousRenderTaskId ?? (task.result as { previousRenderTaskId?: number } | null)?.previousRenderTaskId;
  const history = <div className="source-record-actions"><Link className="btn btn-secondary" to={`/tasks/${task.id}`}>查看绘图任务 #{task.id}</Link>
    {typeof previousRenderTaskId === "number" && Number.isSafeInteger(previousRenderTaskId) && previousRenderTaskId > 0 && previousRenderTaskId !== task.id
      && <Link className="btn btn-secondary" to={`/tasks/${previousRenderTaskId}`}>查看上一版图表（任务 #{previousRenderTaskId}）</Link>}
  </div>;
  if (["queued", "running"].includes(task.status)) return <div><p className="section-help">R 图表任务 #{task.id} 正在后台执行（{task.progress}%）。</p>{history}</div>;
  if (task.status === "failed") return <div><div className="notice-error" role="alert">R 图表生成失败：{task.error_summary}</div>{history}</div>;
  if (task.status === "cancelled") return <div><p className="section-help" role="status">R 图表任务 #{task.id} 已取消。</p>{history}</div>;
  const value = task.result as { rendererVersion?: string; artifacts?: Array<{ id: number; format: string; filename: string; downloadUrl: string; rendererVersion: string }> };
  const artifacts = value.artifacts ?? [];
  const svg = artifacts.find((artifact) => artifact.format === "svg");
  const html = artifacts.find((artifact) => artifact.format === "html");
  return <div className="panel source-record"><h3>R 图表 · {String(value.rendererVersion ?? "")}</h3>
    {history}
    <RChartViewer key={task.id} title="中药—疾病靶点比对统计" interactive={hasInteractiveRenderer(value.rendererVersion)}
      svgUrl={svg && `${svg.downloadUrl}?inline=1`} htmlUrl={html && `${html.downloadUrl}?inline=1`} />
    <div className="source-record-actions">{artifacts.map((artifact) => <a className="btn btn-secondary" key={artifact.id} href={artifact.downloadUrl}>下载 {artifact.format.toUpperCase()}</a>)}</div>
  </div>;
}
