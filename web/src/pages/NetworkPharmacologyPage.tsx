import { WorkspaceModuleNav } from "../components/WorkspaceModuleNav";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useOutletContext } from "react-router-dom";
import { Activity, ArrowLeft, Network, RefreshCw } from "lucide-react";
import { logout, type Session } from "../api/auth";
import { getAnalysisTask, type AnalysisTask } from "../api/datasets";
import { createVisualization, runNetworkPharmacology, runReactomeEnrichment, runStringNetwork, type NetworkPharmacologyResult } from "../api/network";
import { ApiError } from "../api/client";
import { KnowledgeNetworkGraph } from "../components/KnowledgeNetworkGraph";
import { NetworkPharmacologyCharts } from "../components/NetworkPharmacologyCharts";
import { NetworkResultDownloads } from "../components/NetworkResultDownloads";

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "请求未完成，请稍后重试。";
}

export function NetworkPharmacologyPage() {
  const user = useOutletContext<NonNullable<Session["user"]>>();
  const location = useLocation();
  const navigate = useNavigate();
  const [herb, setHerb] = useState("");
  const [disease, setDisease] = useState("");
  const [result, setResult] = useState<NetworkPharmacologyResult | null>(null);
  const [pathwayTask, setPathwayTask] = useState<AnalysisTask | null>(null);
  const [stringTask, setStringTask] = useState<AnalysisTask | null>(null);
  const [visualizationTask, setVisualizationTask] = useState<AnalysisTask | null>(null);
  const [shareWithReactome, setShareWithReactome] = useState(false);
  const [shareWithString, setShareWithString] = useState(false);
  const [requiredScore, setRequiredScore] = useState(700);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [caseContext, setCaseContext] = useState<{ caseId: number; candidateId: number } | null>(null);

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
    const pending = [pathwayTask, stringTask, visualizationTask].filter((task): task is AnalysisTask => Boolean(task && ["queued", "running"].includes(task.status)));
    if (!pending.length) return;
    const timer = window.setTimeout(() => {
      for (const task of pending) {
        void getAnalysisTask(task.id).then((latest) => {
          if (latest.input_parameters.analysisKind === "reactome_enrichment") setPathwayTask(latest);
          if (latest.input_parameters.analysisKind === "string_ppi") setStringTask(latest);
          if (latest.input_parameters.analysisKind === "r_visualization") setVisualizationTask(latest);
        }).catch((cause: unknown) => setError(errorMessage(cause)));
      }
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [pathwayTask, stringTask, visualizationTask]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    setPathwayTask(null);
    setStringTask(null);
    setVisualizationTask(null);
    try {
      setResult(await runNetworkPharmacology({
        herb,
        disease,
        ...(caseContext ? { source_case_id: caseContext.caseId, source_candidate_id: caseContext.candidateId } : {}),
      }));
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function requestPathways() {
    if (!result || !shareWithReactome) return;
    setError(null);
    try {
      setPathwayTask(await runReactomeEnrichment(result.targets.map((item) => item.target)));
    } catch (cause) { setError(errorMessage(cause)); }
  }

  async function requestString() {
    if (!result || !shareWithString) return;
    setError(null);
    try {
      setStringTask(await runStringNetwork(result.targets.map((item) => item.target), requiredScore));
    } catch (cause) { setError(errorMessage(cause)); }
  }

  async function requestVisualization() {
    if (!result) return;
    setError(null);
    try { setVisualizationTask(await createVisualization(result.taskId, "overlap")); }
    catch (cause) { setError(errorMessage(cause)); }
  }

  async function signOut() {
    try { await logout(); navigate("/login", { replace: true }); }
    catch (cause) { setError(errorMessage(cause)); }
  }

  return <main className="workspace-page">
    <header className="workspace-nav">
      <Link to="/" className="site-brand" aria-label="远志 AI Scientist 首页"><img src="/images/yuanzhi-mark.png" alt="" width={42} height={42} className="brand-mark" /><span><strong>远志 AI Scientist</strong><small>研究者工作区</small></span></Link>
      <WorkspaceModuleNav isSuperuser={user.isSuperuser} />
      <div className="workspace-nav-actions"><span className="workspace-user">{user.username}{user.isSuperuser ? " · 平台管理员" : " · 研究者"}</span><button className="btn btn-secondary" type="button" onClick={() => void signOut()}>退出</button></div>
    </header>
    <div className="app-main workspace-main"><div className="app-main-inner">
      <div className="page-heading"><div className="page-heading-copy"><p className="page-kicker">Network pharmacology</p><h1 className="page-title">中药—疾病靶点交集</h1><p className="page-description">在已导入的本地知识目录中匹配中药成分靶点和疾病靶点，展示关系证据与来源版本。</p></div><Link to="/" className="btn btn-secondary"><ArrowLeft size={16} />返回首页</Link></div>
      {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
      <div className="case-workspace-grid">
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
            <div className="case-list-heading"><div><p className="page-kicker">Evidence-backed result</p><h2 className="section-title-sm">分析任务 #{result.taskId}</h2></div><span className="status-badge status-success">已保存，可在任务记录中追溯</span></div>
            <div className="panel proteomics-result-panel">
              <div className="source-record-actions"><button className="btn btn-secondary" type="button" disabled={Boolean(visualizationTask && ["queued", "running"].includes(visualizationTask.status))} onClick={() => void requestVisualization()}>生成 R 图表</button></div>
              {visualizationTask && <VisualizationResult task={visualizationTask} />}
              <div className="proteomics-metrics">
                <Metric label="匹配中药靶点" value={result.summary.herbTargetCount} />
                <Metric label="匹配疾病靶点" value={result.summary.diseaseTargetCount} />
                <Metric label="严格交集" value={result.summary.strictIntersectionCount} />
                <Metric label="疾病—中药直接关联" value={result.summary.directAssociationTargetCount} />
                <Metric label="候选靶点" value={result.summary.candidateTargetCount} />
                <Metric label="关联成分" value={result.summary.componentCount} />
              </div>
              <NetworkResultDownloads result={result} />
              <NetworkPharmacologyCharts key={result.taskId} result={result} />
              <KnowledgeNetworkGraph network={result.network} knownTruncated={result.limits.linksTruncated || result.limits.targetsTruncated} />
              {(result.summary.unmatchedHerbs.length > 0 || result.summary.unmatchedDiseases.length > 0 || Boolean(result.summary.unresolvedFormulas?.length)) && <div className="notice-error" role="status">{result.summary.unmatchedHerbs.length > 0 ? `未匹配中药或方剂：${result.summary.unmatchedHerbs.join("、")}。` : ""}{result.summary.unmatchedDiseases.length > 0 ? `未匹配疾病：${result.summary.unmatchedDiseases.join("、")}。` : ""}{result.summary.unresolvedFormulas?.length ? `已匹配方剂但本地没有带来源版本的组成关系：${result.summary.unresolvedFormulas.join("、")}。` : ""}当前按知识目录中的精确名称匹配，请检查数据源导入结果和实体名称。</div>}
              {result.summary.matchedFormulas?.length ? <p className="section-help">方剂 {result.summary.matchedFormulas.join("、")} 已按本地组成关系展开为中药：{result.summary.matchedHerbs.join("、") || "暂无可追溯组成"}。</p> : null}
              {result.targets.length ? <div className="case-list-items">{result.targets.map((target) => <article className="panel source-record" key={target.normalizedTarget}>
                <div className="case-record-top"><div><h3>{target.target} <span className="status-badge status-warning">{target.matchType}</span></h3><p className="section-help">成分：{target.components.join("、") || "无中药成分证据"} · 通路：{target.pathways.join("、") || "无通路注释"}</p></div></div>
                <p className="section-help">中药证据 {target.herbEvidenceCount} 条 · 疾病证据 {target.diseaseEvidenceCount} 条 · 直接关联 {target.directEvidenceCount} 条</p>
                <ul className="proteomics-pathways">{target.sources.slice(0, 8).map((source, index) => <li key={`${source.sourceRecordId}-${index}`}><strong>{source.source} · {source.sourceVersion}</strong><span>{source.relationType} / {source.evidenceType} / {source.sourceRecordId}</span></li>)}</ul>
              </article>)}</div> : <div className="panel empty-state"><strong>没有可报告的交集</strong><p>当前已导入来源没有提供足够的关系证据；系统不会用示例规则生成候选靶点。</p></div>}
              {(result.limits.targetsTruncated || result.limits.linksTruncated) && <p className="section-help">结果过大，页面仅展示了部分网络节点或靶点。</p>}
              {result.targets.length >= 2 && <section className="case-form-fields external-analysis-options" aria-label="可选外部分析">
                <label className="proteomics-consent"><input type="checkbox" checked={shareWithReactome} onChange={(event) => setShareWithReactome(event.target.checked)} /><span><strong>同意提交基因标识到 MyGene.info 与 Reactome</strong><small>仅提交当前页面列出的候选靶点，最多 500 个；不提交医案或完整数据文件。</small></span></label>
                <div className="source-record-actions"><button className="btn btn-secondary" type="button" disabled={!shareWithReactome || result.targets.length > 500 || result.limits.targetsTruncated || Boolean(pathwayTask && ["queued", "running"].includes(pathwayTask.status))} onClick={() => void requestPathways()}>Reactome 通路富集</button>{result.targets.length > 500 || result.limits.targetsTruncated ? <span className="section-help">Reactome 最多接收 500 个完整显示的靶点；当前结果过多，请缩小范围。</span> : null}</div>
                {pathwayTask && <ExternalTaskResult task={pathwayTask} kind="reactome_enrichment" />}
                <label className="proteomics-consent"><input type="checkbox" checked={shareWithString} onChange={(event) => setShareWithString(event.target.checked)} /><span><strong>同意提交基因标识到 STRING</strong><small>仅提交当前页面列出的候选靶点；STRING 物理互作网络可能与功能关联网络不同。</small></span></label>
                <label className="form-label">最低置信度<select className="field" value={requiredScore} onChange={(event) => setRequiredScore(Number(event.target.value))}><option value={400}>中等（400）</option><option value={700}>高（700）</option><option value={900}>最高（900）</option></select></label>
                <div className="source-record-actions"><button className="btn btn-secondary" type="button" disabled={!shareWithString || result.targets.length > 200 || result.limits.targetsTruncated || Boolean(stringTask && ["queued", "running"].includes(stringTask.status))} onClick={() => void requestString()}>STRING PPI 网络</button>{result.targets.length > 200 || result.limits.targetsTruncated ? <span className="section-help">STRING 最多接收 200 个完整显示的靶点；当前结果过多，请缩小范围。</span> : null}</div>
                {stringTask && <ExternalTaskResult task={stringTask} kind="string_ppi" />}
              </section>}
            </div>
          </>}
        </section>
      </div>
    </div></div>
  </main>;
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div className="proteomics-metric"><span>{label}</span><strong>{value.toLocaleString("zh-CN")}</strong></div>;
}

function ExternalTaskResult({ task, kind }: { task: AnalysisTask; kind: "reactome_enrichment" | "string_ppi" }) {
  if (["queued", "running"].includes(task.status)) return <p className="section-help">{kind === "reactome_enrichment" ? "Reactome" : "STRING"} 任务 #{task.id} 正在后台执行（{task.progress}%）。</p>;
  if (task.status === "failed") return <div className="notice-error" role="alert">外部分析任务 #{task.id} 失败：{task.error_summary}</div>;
  const value = task.result as Record<string, unknown>;
  if (kind === "reactome_enrichment") {
    const pathways = Array.isArray(value.pathways) ? value.pathways as Array<Record<string, unknown>> : [];
    return <div className="panel source-record"><h3>Reactome 富集结果 · {String(value.sourceVersion ?? "来源版本未返回")}</h3><p className="section-help">映射 {String(value.mappedCount ?? 0)} 个标识 · 未识别 {String(value.identifiersNotFound ?? 0)} 个</p>
      {pathways.length ? <ul className="proteomics-pathways">{pathways.slice(0, 20).map((item, index) => <li key={`${String(item.stableId)}-${index}`}><strong>{String(item.name)}</strong><span>{String(item.stableId)} · FDR {String(item.fdr)}</span></li>)}</ul> : <p className="section-help">此输入未返回符合当前筛选阈值的通路。</p>}
    </div>;
  }
  const edges = Array.isArray(value.edges) ? value.edges as Array<Record<string, unknown>> : [];
  const nodes = Array.isArray(value.nodes) ? value.nodes as Array<Record<string, unknown>> : [];
  return <div className="panel source-record"><h3>STRING 网络 · {String(value.sourceVersion ?? "版本未配置")}</h3><p className="section-help">互作 {String(value.interactionCount ?? 0)} 条 · 阈值 {String(value.requiredScore ?? 0)}</p>
    {nodes.length > 0 && <><p className="section-help">中心性按当前筛选物理互作图计算：degree 为邻居数；betweenness 为归一化无权 Brandes 最短路径中介中心性，不代表因果作用。</p><div className="table-scroll"><table className="data-table"><thead><tr><th>蛋白</th><th>degree</th><th>betweenness</th></tr></thead><tbody>
      {[...nodes].sort((left, right) => (Number(right.betweenness) || 0) - (Number(left.betweenness) || 0) || (Number(right.degree) || 0) - (Number(left.degree) || 0)).slice(0, 30).map((node, index) => <tr key={`${String(node.id)}-${index}`}><td>{String(node.label ?? node.id ?? "")}</td><td>{String(node.degree ?? "—")}</td><td>{typeof node.betweenness === "number" ? node.betweenness.toPrecision(4) : "—"}</td></tr>)}
    </tbody></table></div></>}
    {edges.length ? <ul className="proteomics-pathways">{edges.slice(0, 30).map((item, index) => <li key={`${String(item.source)}-${String(item.target)}-${index}`}><strong>{String(item.source)} ↔ {String(item.target)}</strong><span>score {String(item.scoreOutOf1000)}/1000</span></li>)}</ul> : <p className="section-help">当前标识和置信度下没有返回互作边。</p>}
  </div>;
}

function VisualizationResult({ task }: { task: AnalysisTask }) {
  if (["queued", "running"].includes(task.status)) return <p className="section-help">R 图表任务 #{task.id} 正在后台执行（{task.progress}%）。</p>;
  if (task.status === "failed") return <div className="notice-error" role="alert">R 图表生成失败：{task.error_summary}</div>;
  const value = task.result as { rendererVersion?: string; artifacts?: Array<{ id: number; format: string; filename: string; downloadUrl: string; rendererVersion: string }> };
  const artifacts = value.artifacts ?? [];
  const svg = artifacts.find((artifact) => artifact.format === "svg");
  return <div className="panel source-record"><h3>R 图表 · {String(value.rendererVersion ?? "")}</h3>
    {svg && <img className="visualization-preview" src={`${svg.downloadUrl}?inline=1`} alt="中药—疾病靶点交集柱状图" />}
    <div className="source-record-actions">{artifacts.map((artifact) => <a className="btn btn-secondary" key={artifact.id} href={artifact.downloadUrl}>下载 {artifact.format.toUpperCase()}</a>)}</div>
  </div>;
}
