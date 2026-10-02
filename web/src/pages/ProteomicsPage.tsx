import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useOutletContext } from "react-router-dom";
import { Activity, ArrowLeft, Download, LogOut, Play, RefreshCw } from "lucide-react";
import {
  getAnalysisTask,
  getAnalysisTasks,
  getDatasets,
  getProteomicsRows,
  exportProteomicsResults,
  runProteomicsAnalysis,
  type AnalysisTask,
  type ProteomicsResult,
  type ProteomicsRowPage,
  type ResearchDataset,
} from "../api/datasets";
import { logout, type Session } from "../api/auth";
import { ApiError } from "../api/client";

const initialMapping = {
  geneColumn: "",
  proteinColumn: "",
  log2FcColumn: "",
  fdrColumn: "",
  pValueColumn: "",
  directionColumn: "",
};

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "请求未完成，请稍后重试。";
}

function formatNumber(value: number | null | undefined) {
  return value == null ? "—" : Number(value).toPrecision(4);
}

function taskStatusLabel(status: AnalysisTask["status"]) {
  return ({ queued: "排队中", running: "分析中", succeeded: "已完成", failed: "失败", cancelled: "已取消" })[status];
}

function mappingStatusLabel(status: string) {
  return ({
    database: "本地核实",
    external: "外部映射",
    unverified: "格式推测",
    ambiguous: "标识歧义",
    unmapped: "未映射",
    missing: "缺少标识",
  } as Record<string, string>)[status] ?? status;
}

function downloadJson(filename: string, value: unknown) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function ProteomicsPage() {
  const user = useOutletContext<NonNullable<Session["user"]>>();
  const navigate = useNavigate();
  const [datasets, setDatasets] = useState<ResearchDataset[]>([]);
  const [datasetId, setDatasetId] = useState<number | "">("");
  const [task, setTask] = useState<AnalysisTask | null>(null);
  const [mapping, setMapping] = useState(initialMapping);
  const [thresholds, setThresholds] = useState({ log2FcMin: "1", fdrMax: "0.05", pValueMax: "0.05" });
  const [referenceTargets, setReferenceTargets] = useState("");
  const [externalReactome, setExternalReactome] = useState(false);
  const [externalString, setExternalString] = useState(false);
  const [stringRequiredScore, setStringRequiredScore] = useState("700");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [showRows, setShowRows] = useState(false);
  const [rowPageNumber, setRowPageNumber] = useState(1);
  const [rowPage, setRowPage] = useState<ProteomicsRowPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([getDatasets(), getAnalysisTasks()])
      .then(([datasetResponse, taskResponse]) => {
        if (!active) return;
        setDatasets(datasetResponse.results);
        if (datasetResponse.results.length) setDatasetId(datasetResponse.results[0].id);
        const latestTask = taskResponse.results.find((item) => item.task_type === "proteomics");
        if (latestTask) {
          setTask(latestTask);
          if (latestTask.dataset) setDatasetId(latestTask.dataset);
        }
      })
      .catch((cause: unknown) => { if (active) setError(errorMessage(cause)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!task || !["queued", "running"].includes(task.status)) return;
    let active = true;
    const timer = window.setTimeout(() => {
      getAnalysisTask(task.id)
        .then((latest) => { if (active) setTask(latest); })
        .catch((cause: unknown) => { if (active) setError(errorMessage(cause)); });
    }, 1400);
    return () => { active = false; window.clearTimeout(timer); };
  }, [task]);

  useEffect(() => {
    if (!showRows || !task || task.status !== "succeeded") return;
    let active = true;
    getProteomicsRows(task.id, rowPageNumber)
      .then((value) => { if (active) setRowPage(value); })
      .catch((cause: unknown) => { if (active) setError(errorMessage(cause)); });
    return () => { active = false; };
  }, [showRows, task, rowPageNumber]);

  const selectedDataset = useMemo(
    () => datasets.find((item) => item.id === datasetId) ?? null,
    [datasets, datasetId],
  );
  const taskDataset = useMemo(
    () => datasets.find((item) => item.id === task?.dataset) ?? null,
    [datasets, task?.dataset],
  );
  const result = task?.status === "succeeded" && task.task_type === "proteomics"
    ? task.result as ProteomicsResult
    : null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedDataset) return;
    setSubmitting(true);
    setError(null);
    setNotice(null);
    setShowRows(false);
    setRowPage(null);
    try {
      const taskResponse = await runProteomicsAnalysis(selectedDataset.id, {
        mapping,
        thresholds: {
          log2FcMin: Number(thresholds.log2FcMin),
          fdrMax: Number(thresholds.fdrMax),
          pValueMax: Number(thresholds.pValueMax),
        },
        referenceTargets: referenceTargets.split(/[\s,，、;；|/]+/).filter(Boolean),
        externalReactome,
        externalString,
        stringRequiredScore: Number(stringRequiredScore),
      });
      setTask(taskResponse);
      setNotice(`分析任务 #${taskResponse.id} 已进入后台队列。`);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setSubmitting(false);
    }
  }

  async function signOut() {
    setError(null);
    try { await logout(); navigate("/login", { replace: true }); }
    catch (cause) { setError(errorMessage(cause)); }
  }

  async function exportRows(format: "csv" | "xlsx") {
    if (!task) return;
    setError(null);
    try {
      const blob = await exportProteomicsResults(task.id, format);
      downloadBlob(`proteomics-task-${task.id}.${format}`, blob);
    } catch (cause) {
      setError(errorMessage(cause));
    }
  }

  return <main className="workspace-page">
    <header className="workspace-nav">
      <Link to="/" className="site-brand" aria-label="远志 AI Scientist 首页">
        <img src="/images/yuanzhi-mark.png" alt="" width={42} height={42} className="brand-mark" />
        <span><strong>远志 AI Scientist</strong><small>研究者工作区</small></span>
      </Link>
      <nav className="workspace-module-nav" aria-label="研究模块">
        <Link to="/cases">医案管理</Link><Link to="/datasets">研究数据集</Link><Link to="/proteomics" aria-current="page">蛋白组学</Link><Link to="/network-pharmacology">网络药理</Link>{user.isSuperuser && <Link to="/admin/sources">数据源同步</Link>}
      </nav>
      <div className="workspace-nav-actions"><span className="workspace-user">{user.username}{user.isSuperuser ? " · 平台管理员" : " · 研究者"}</span>
        <button className="btn btn-secondary" type="button" onClick={signOut}><LogOut size={16} />退出</button></div>
    </header>

    <div className="app-main workspace-main"><div className="app-main-inner">
      <div className="page-heading"><div className="page-heading-copy"><p className="page-kicker">Proteomics analysis</p><h1 className="page-title">差异蛋白组学分析</h1>
        <p className="page-description">复用 main 分支的差异蛋白筛选和本地网络逻辑；逐行保留筛选、映射和排除原因，未验证的符号会明确标出。</p></div>
        <Link to="/datasets" className="btn btn-secondary"><ArrowLeft size={16} />数据集管理</Link>
      </div>

      {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
      {notice && <div className="notice-success workspace-notice" role="status">{notice}</div>}

      <div className="case-workspace-grid proteomics-workspace-grid">
        <form className="panel case-form" onSubmit={(event) => void submit(event)} aria-label="启动差异蛋白分析">
          <div className="panel-header"><div><h2 className="section-title-sm">分析设置</h2><p className="section-help">数据集原始文件不会发送到外部服务。</p></div><span className="page-heading-icon"><Activity size={19} /></span></div>
          <div className="case-form-fields">
            {loading ? <p className="section-help" role="status">正在读取你的数据集…</p> : datasets.length ? <label className="form-label" htmlFor="proteomics-dataset">选择已上传数据集
              <select className="field" id="proteomics-dataset" value={datasetId} onChange={(event) => setDatasetId(Number(event.target.value))}>
                {datasets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.original_filename}</option>)}
              </select></label> : <div className="empty-state"><strong>还没有可分析的数据集</strong><p>先上传差异蛋白 CSV、TSV 或 Excel 文件。</p><Link className="btn btn-secondary" to="/datasets">上传数据集</Link></div>}

            {datasets.length > 0 && <>
              <p className="section-help">常见表头会自动识别。若使用了特殊表头，请填写文件中的确切列名；基因列和蛋白列至少能识别一个。</p>
              <div className="proteomics-column-grid">
                {([
                  ["geneColumn", "基因列", "Gene Symbol / 基因符号"],
                  ["proteinColumn", "蛋白列", "Protein / UniProt"],
                  ["log2FcColumn", "log2FC 列", "log2FC"],
                  ["fdrColumn", "FDR 列", "FDR / padj"],
                  ["pValueColumn", "P 值列", "pvalue"],
                  ["directionColumn", "变化方向列", "direction"],
                ] as const).map(([key, label, placeholder]) => <label className="form-label" key={key}>{label}
                  <input className="field" value={mapping[key]} placeholder={placeholder} onChange={(event) => setMapping((value) => ({ ...value, [key]: event.target.value }))} />
                </label>)}
              </div>
              <div className="proteomics-threshold-grid">
                <label className="form-label">|log2FC| ≥<input className="field" type="number" min="0" max="100" step="0.1" value={thresholds.log2FcMin} onChange={(event) => setThresholds((value) => ({ ...value, log2FcMin: event.target.value }))} /></label>
                <label className="form-label">FDR ≤<input className="field" type="number" min="0" max="1" step="0.01" value={thresholds.fdrMax} onChange={(event) => setThresholds((value) => ({ ...value, fdrMax: event.target.value }))} /></label>
                <label className="form-label">P 值 ≤<input className="field" type="number" min="0" max="1" step="0.01" value={thresholds.pValueMax} onChange={(event) => setThresholds((value) => ({ ...value, pValueMax: event.target.value }))} /></label>
              </div>
              <label className="form-label" htmlFor="proteomics-reference">候选靶点（可选）
                <textarea className="field case-textarea case-textarea-short" id="proteomics-reference" value={referenceTargets} onChange={(event) => setReferenceTargets(event.target.value)} placeholder="TP53, IL6, MAPK1" />
              </label>
              <label className="proteomics-consent">
                <input type="checkbox" checked={externalReactome} onChange={(event) => setExternalReactome(event.target.checked)} />
                <span><strong>启用 MyGene.info 标识映射与 Reactome 富集</strong><small>仅发送通过筛选的基因/蛋白标识（最多 500 个），不会发送完整文件、未通过行、账号或医案。当前外部分析仅支持人类标识；不勾选时所有分析留在本地。</small></span>
              </label>
              <label className="proteomics-consent">
                <input type="checkbox" checked={externalString} onChange={(event) => setExternalString(event.target.checked)} />
                <span><strong>另行同意查询 STRING 物理互作（PPI）</strong><small>最多发送筛选后 200 个基因/蛋白标识，只查询人类物理互作；不会发送原始文件或其他行。STRING 分数表示数据库互作证据，不证明因果关系。</small></span>
              </label>
              {externalString && <label className="form-label">STRING 最低置信度（0–1000）
                <input className="field" type="number" min="0" max="1000" step="50" value={stringRequiredScore} onChange={(event) => setStringRequiredScore(event.target.value)} />
              </label>}
            </>}
          </div>
          <div className="case-form-footer"><p>阈值筛选不会把缺失或非法统计值默认为显著。</p>
            <button className="btn btn-primary" type="submit" disabled={!selectedDataset || submitting || task?.status === "queued" || task?.status === "running"}>
              {submitting ? <RefreshCw size={16} className="spin" /> : <Play size={16} />}{submitting ? "正在提交…" : "提交后台分析"}
            </button></div>
        </form>

        <section className="case-list" aria-labelledby="proteomics-results-heading">
          <div className="case-list-heading"><div><p className="page-kicker">Reproducible analysis</p><h2 id="proteomics-results-heading" className="section-title-sm">分析结果</h2></div>
            {task && <span className={`status-badge ${task.status === "failed" ? "status-error" : task.status === "succeeded" ? "status-success" : "status-warning"}`}>{taskStatusLabel(task.status)}</span>}
          </div>
          {!task ? <div className="panel empty-state"><Activity size={27} /><strong>等待分析任务</strong><p>选择一个已上传的数据集并提交分析设置。</p></div>
            : <article className="panel proteomics-result-panel">
              <div className="case-record-top"><div><h3>任务 #{task.id} · {taskDataset?.name ?? `数据集 ${task.dataset ?? "已移除"}`}</h3><time dateTime={task.created_at}>创建于 {new Date(task.created_at).toLocaleString("zh-CN")}</time></div>
                {result && <div className="proteomics-export-actions">
                  <button type="button" className="btn btn-secondary" onClick={() => void exportRows("csv")}><Download size={15} />CSV</button>
                  <button type="button" className="btn btn-secondary" onClick={() => void exportRows("xlsx")}><Download size={15} />XLSX</button>
                  <button type="button" className="btn btn-secondary" onClick={() => downloadJson(`proteomics-task-${task.id}.json`, result)}><Download size={15} />JSON</button>
                </div>}</div>
              {(task.status === "queued" || task.status === "running") && <div className="analysis-progress" role="status"><span>任务已排队，分析过程在后台运行。</span><progress max={100} value={task.progress} /></div>}
              {task.status === "failed" && <div className="notice-error" role="alert">{task.error_summary || "分析失败，请检查文件和列映射。"}</div>}
              {result && <ProteomicsResultView result={result} task={task} showRows={showRows} rowPage={rowPage} rowPageNumber={rowPageNumber}
                onToggleRows={() => { setShowRows((value) => !value); setRowPageNumber(1); }}
                onRowPageChange={setRowPageNumber} />}
            </article>}
        </section>
      </div>
    </div></div>
  </main>;
}

function Metric({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return <div className="proteomics-metric"><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>;
}

function ProteomicsResultView({
  result, task, showRows, rowPage, rowPageNumber, onToggleRows, onRowPageChange,
}: {
  result: ProteomicsResult;
  task: AnalysisTask;
  showRows: boolean;
  rowPage: ProteomicsRowPage | null;
  rowPageNumber: number;
  onToggleRows: () => void;
  onRowPageChange: (page: number) => void;
}) {
  const externalStringNodes = new Map((result.externalString?.nodes ?? []).map((node) => [node.id, node.label]));
  return <div className="proteomics-result-content">
    <p className="section-help">原始文件 SHA-256：<code>{result.dataset.sha256}</code> · 算法版本：{result.algorithmVersion} · 来源版本数：{task.source_releases.length}</p>
    <div className="proteomics-metrics">
      <Metric label="通过筛选" value={result.summary.selectedRowCount} />
      <Metric label="唯一标识" value={result.summary.uniqueLabelCount} />
      <Metric label="本地映射" value={result.summary.databaseMappedCount} note={`外部映射 ${result.summary.externalMappedCount ?? 0} · 格式推测 ${result.summary.unverifiedSymbolCount}`} />
      <Metric label="未映射" value={result.summary.unmappedCount} />
      <Metric label="本地通路" value={result.summary.pathwayCount} />
      <Metric label="候选交集" value={result.summary.candidateOverlapCount} />
    </div>

    <section className="proteomics-qc panel">
      <div className="panel-header"><div><h3 className="section-title-sm">输入质量检查</h3><p className="section-help">所有输入行都保留了筛选结果和排除原因。</p></div></div>
      <div className="proteomics-qc-grid">
        <Metric label="输入行" value={result.qc.inputRowCount} />
        <Metric label="缺少标识" value={result.qc.missingIdentifierCount} />
        <Metric label="重复标识" value={result.qc.duplicateIdentifierCount} />
        <Metric label="非法数值行" value={result.qc.invalidNumericValueRowCount} />
        <Metric label="排除行" value={result.qc.excludedRowCount} />
      </div>
      {Object.keys(result.qc.excludedReasonCounts).length > 0 && <p className="section-help">排除原因：{Object.entries(result.qc.excludedReasonCounts).map(([reason, count]) => `${reason} ${count}`).join(" · ")}</p>}
    </section>

    {result.warnings.map((warning) => <p className="notice-warning" key={warning}>{warning}</p>)}
    <div className="notice-info"><Activity size={17} /><span>{result.summary.enrichmentNote}</span></div>

    {result.externalReactome && <section className="proteomics-result-section">
      <div className="case-list-heading"><div><h3 className="section-title-sm">MyGene.info / Reactome 外部结果</h3><p className="section-help">{result.externalReactome.organism} · {result.externalReactome.source}{result.externalReactome.sourceVersion ? ` ${result.externalReactome.sourceVersion}` : " · 版本未返回"}</p></div>
        <span className="status-badge">{{ succeeded: "有显著通路", no_significant_pathways: "无显著通路", no_mapped_identifiers: "没有可映射标识", unavailable: "服务不可用", disabled: "服务已停用" }[result.externalReactome.status] ?? result.externalReactome.status}</span>
      </div>
      <p className="section-help">映射 {result.externalReactome.mappings.length} 个标识；发送到 Reactome {result.externalReactome.submittedIdentifierCount ?? 0} 个。歧义 {result.externalReactome.ambiguousIdentifiers.length} 个，未映射 {result.externalReactome.unmappedIdentifiers.length} 个。</p>
      {result.externalReactome.pathways.length > 0 ? <div className="table-scroll"><table className="data-table"><thead><tr><th>通路</th><th>Reactome ID</th><th>命中实体</th><th>覆盖率</th><th>P 值</th><th>FDR</th></tr></thead><tbody>
        {result.externalReactome.pathways.map((pathway) => <tr key={pathway.stableId}><td>{pathway.name}</td><td>{pathway.stableId}</td><td>{pathway.matchedEntities}/{pathway.totalEntities ?? "—"}</td><td>{pathway.coverage == null ? "—" : formatNumber(pathway.coverage)}</td><td>{formatNumber(pathway.pValue)}</td><td>{formatNumber(pathway.fdr)}</td></tr>)}
      </tbody></table></div> : <p className="section-help">本次没有可展示的显著 Reactome 通路，或外部服务不可用。</p>}
      {result.externalReactome.ambiguousIdentifiers.length > 0 && <details className="case-notes"><summary>存在歧义的标识</summary><p>{result.externalReactome.ambiguousIdentifiers.join("、")}</p></details>}
    </section>}

    {result.externalString && <section className="proteomics-result-section">
      <div className="case-list-heading"><div><h3 className="section-title-sm">STRING 物理互作网络</h3><p className="section-help">{result.externalString.organism} · {result.externalString.source}{result.externalString.sourceVersion ? ` ${result.externalString.sourceVersion}` : " · 数据库版本未配置"} · 最低置信度 {result.externalString.requiredScore}/1000</p></div>
        <span className={`status-badge ${result.externalString.status === "succeeded" ? "status-success" : result.externalString.status === "unavailable" || result.externalString.status === "disabled" ? "status-warning" : ""}`}>{{ succeeded: "已返回互作", no_interactions: "没有满足阈值的互作", insufficient_identifiers: "可用标识不足", unavailable: "服务不可用", disabled: "服务已停用" }[result.externalString.status] ?? result.externalString.status}</span>
      </div>
      <p className="section-help">本次识别 {result.externalString.inputCount} 个标识，向 STRING 发送 {result.externalString.submittedIdentifierCount} 个；返回 {result.externalString.interactionCount} 条物理互作。分数是数据库证据，不代表因果结论。</p>
      {result.externalString.edges.length > 0 ? <div className="table-scroll"><table className="data-table"><thead><tr><th>蛋白 A</th><th>蛋白 B</th><th>STRING 评分</th></tr></thead><tbody>
        {result.externalString.edges.slice(0, 200).map((edge, index) => {
          return <tr key={`${edge.source}:${edge.target}:${index}`}><td>{externalStringNodes.get(edge.source) ?? edge.source}</td><td>{externalStringNodes.get(edge.target) ?? edge.target}</td><td>{edge.scoreOutOf1000}/1000</td></tr>;
        })}
      </tbody></table></div> : <p className="section-help">本次没有可展示的物理互作边。</p>}
      {result.externalString.truncatedIdentifierCount > 0 && <p className="section-help">超出每次 200 个标识的上限，未发送 {result.externalString.truncatedIdentifierCount} 个。</p>}
    </section>}

    <section className="proteomics-result-section">
      <div className="case-list-heading"><h3 className="section-title-sm">Top degree 候选蛋白</h3><span className="section-help">degree 表示本地已登记通路关联数，不代表因果结论。</span></div>
      {result.topNodes.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>基因/蛋白</th><th>映射状态</th><th>degree</th><th>log2FC</th><th>FDR</th><th>方向</th><th>通路</th></tr></thead><tbody>
        {result.topNodes.map((row) => <tr key={row.symbol}><td>{row.symbol}</td><td>{mappingStatusLabel(row.mappingStatus)}</td><td>{row.degree}</td><td>{formatNumber(row.log2FoldChange)}</td><td>{formatNumber(row.fdr)}</td><td>{row.direction || "—"}</td><td title={row.pathways.join("、")}>{row.pathways.slice(0, 2).join("、") || "—"}</td></tr>)}
      </tbody></table></div> : <div className="empty-state">当前本地知识库没有可展示的基因—通路关系。</div>}
    </section>

    <section className="proteomics-result-section">
      <h3 className="section-title-sm">与候选靶点交叉验证</h3>
      {result.validation.referenceTargets.length ? <div className="proteomics-validation-grid">
        <div><span>共同靶点</span><p>{result.validation.overlap.join("、") || "无"}</p></div>
        <div><span>组学特有</span><p>{result.validation.proteomicsOnly.slice(0, 30).join("、") || "无"}</p></div>
        <div><span>候选未检出</span><p>{result.validation.referenceOnly.slice(0, 30).join("、") || "无"}</p></div>
      </div> : <p className="section-help">本次未输入候选靶点，只生成蛋白组学内部结果。</p>}
    </section>

    <section className="proteomics-result-section">
      <div className="case-list-heading"><h3 className="section-title-sm">来源可追溯的本地通路</h3><span className="section-help">{result.pathways.length} 条</span></div>
      {result.pathways.length ? <ul className="proteomics-pathways">{result.pathways.slice(0, 100).map((pathway) => <li key={pathway.stableId}><strong>{pathway.name}</strong><span>{pathway.stableId} · {pathway.source} {pathway.version}</span></li>)}</ul> : <p className="section-help">没有命中当前本地通路目录。</p>}
    </section>

    {result.unmapped.length > 0 && <details className="case-notes"><summary>未映射标识（{result.summary.unmappedCount} 个）</summary>
      <p>{result.unmapped.join("、")}{result.unmappedTruncated ? "……（其余可在逐行 QC 中查看）" : ""}</p></details>}

    <section className="proteomics-result-section">
      <div className="case-list-heading"><div><h3 className="section-title-sm">逐行筛选结果</h3><p className="section-help">任务共处理 {result.qc.inputRowCount} 行；当前预览 {result.rows.length} 行。</p></div>
        <button className="btn btn-secondary" type="button" onClick={onToggleRows}>{showRows ? "收起完整结果" : "查看逐行 QC"}</button></div>
      {!showRows && <div className="table-scroll"><table className="data-table"><thead><tr><th>原始标识</th><th>规范标识</th><th>映射状态</th><th>log2FC</th><th>FDR</th><th>方向</th></tr></thead><tbody>
        {result.rows.slice(0, 20).map((row) => <tr key={row.index}><td>{row.originalLabel}</td><td>{row.symbol || "—"}</td><td>{mappingStatusLabel(row.mappingStatus)}</td><td>{formatNumber(row.log2FoldChange)}</td><td>{formatNumber(row.fdr)}</td><td>{row.direction || "—"}</td></tr>)}
      </tbody></table></div>}
      {result.previewTruncated && !showRows && <p className="section-help">预览超过 500 行；打开逐行 QC 可分页读取完整结果。</p>}
      {showRows && <>
        {rowPage ? <div className="table-scroll"><table className="data-table"><thead><tr><th>行</th><th>原始标识</th><th>规范标识</th><th>映射状态</th><th>log2FC</th><th>FDR</th><th>筛选</th><th>排除/警告</th></tr></thead><tbody>
          {rowPage.results.map((row) => <tr key={row.row_index}><td>{row.row_index + 1}</td><td>{row.original_label || "—"}</td><td>{row.normalized_symbol || "—"}</td><td>{mappingStatusLabel(row.mapping_status)}</td><td>{formatNumber(row.log2_fold_change)}</td><td>{formatNumber(row.fdr)}</td><td>{row.selected ? "通过" : "排除"}</td><td>{[...row.exclusion_reasons, ...row.qc_warnings].join("、") || "—"}</td></tr>)}
        </tbody></table></div> : <p className="section-help">正在读取逐行结果…</p>}
        {rowPage && <div className="case-pagination"><button className="btn btn-secondary" type="button" disabled={!rowPage.previous} onClick={() => onRowPageChange(Math.max(1, rowPageNumber - 1))}>上一页</button>
          <span>第 {rowPageNumber} 页 / 共 {rowPage.count} 行</span><button className="btn btn-secondary" type="button" disabled={!rowPage.next} onClick={() => onRowPageChange(rowPageNumber + 1)}>下一页</button></div>}
      </>}
    </section>
  </div>;
}
