import { useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { Download, FileText, FlaskConical, History } from "lucide-react";
import { ApiError } from "../api/client";
import { createTextAnalysis, exportTextAnalysis, getTextAnalysisWorkspace, type TextAnalysisTask, type TextAnalysisWorkspace } from "../api/analysis";
import { getAnalysisTask, type AnalysisTask } from "../api/datasets";
import { KnowledgeNetworkGraph } from "../components/KnowledgeNetworkGraph";

const matchLabels = { matched: "已有目录关联", no_rule_match: "未命中规则", catalog_missing: "缺少目录记录", ambiguous_syndrome: "目录同名歧义" };
const evidenceLevels = ["syndrome", "formula", "herbs", "compounds", "targets", "genes", "pathways"];
function errorMessage(error: unknown) { return error instanceof ApiError ? error.message : "请求未完成，请稍后重试。"; }
function verifyTextTask(saved: AnalysisTask, expectedId?: number): TextAnalysisTask {
  if (!Number.isSafeInteger(saved.id) || saved.id <= 0 || saved.task_type !== "text_analysis" || (expectedId !== undefined && saved.id !== expectedId)) {
    throw new Error("Text analysis task identity mismatch");
  }
  return saved as TextAnalysisTask;
}

export function AnalysisPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const savedTaskId = searchParams.get("textTask");
  const adoptedTaskId = useRef<string | null>(null);
  const mounted = useRef(false);
  const submissionInFlight = useRef<number | null>(null);
  const downloadInFlight = useRef<number | null>(null);
  const generation = useRef(0);
  const [workspace, setWorkspace] = useState<TextAnalysisWorkspace | null>(null);
  const [task, setTask] = useState<TextAnalysisTask | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [restoring, setRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const [pollError, setPollError] = useState<string | null>(null);
  const [pollFailures, setPollFailures] = useState(0);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; generation.current += 1; };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true); setHistoryError(null);
    getTextAnalysisWorkspace().then((data) => { if (active) setWorkspace(data); })
      .catch((cause: unknown) => { if (active) setHistoryError(errorMessage(cause)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reload]);

  useEffect(() => {
    // A selected workspace result or accepted creation is already in memory.
    // Adopting its URL must not clear that result or start a competing read.
    if (savedTaskId !== null && adoptedTaskId.current === savedTaskId) {
      adoptedTaskId.current = null;
      return;
    }
    adoptedTaskId.current = null;
    const current = ++generation.current;
    let active = true;
    submissionInFlight.current = null; downloadInFlight.current = null;
    setTask(null); setError(null); setRestoreError(null); setPollError(null); setPollFailures(0);
    setSubmitting(false); setDownloading(null); setRestoring(savedTaskId !== null);
    if (savedTaskId === null) return () => { active = false; };
    if (!/^[1-9]\d*$/.test(savedTaskId) || !Number.isSafeInteger(Number(savedTaskId))) {
      setRestoreError("证候文本分析任务编号无效。"); setRestoring(false);
      return () => { active = false; };
    }
    const expectedId = Number(savedTaskId);
    getAnalysisTask(expectedId)
      .then(saved => {
        if (!active || !mounted.current || generation.current !== current) return;
        setTask(verifyTextTask(saved, expectedId));
      })
      .catch((cause: unknown) => { if (active && mounted.current && generation.current === current) setRestoreError(errorMessage(cause)); })
      .finally(() => { if (active && mounted.current && generation.current === current) setRestoring(false); });
    return () => { active = false; };
  }, [savedTaskId, restoreAttempt]);

  useEffect(() => {
    if (!task || !["queued", "running"].includes(task.status)) return;
    const current = generation.current;
    let active = true;
    const timer = window.setTimeout(() => {
      getAnalysisTask(task.id)
        .then(saved => {
          if (!active || !mounted.current || generation.current !== current) return;
          setTask(verifyTextTask(saved, task.id)); setPollError(null); setPollFailures(0);
        })
        .catch((cause: unknown) => {
          if (!active || !mounted.current || generation.current !== current) return;
          setPollError(`${errorMessage(cause)} 正在重试读取已有任务，不会重新提交。`);
          setPollFailures(value => value + 1);
        });
    }, Math.min(1400 * 2 ** Math.min(pollFailures, 4), 12000));
    return () => { active = false; window.clearTimeout(timer); };
  }, [task, pollFailures]);

  function adoptTask(saved: TextAnalysisTask) {
    setTask(saved); setRestoring(false); setRestoreError(null); setPollError(null); setPollFailures(0);
    const id = String(saved.id);
    if (savedTaskId !== id) {
      adoptedTaskId.current = id;
      setSearchParams(previous => { const next = new URLSearchParams(previous); next.set("textTask", id); return next; }, { replace: true });
    }
  }

  function selectSavedTask(saved: TextAnalysisTask) {
    generation.current += 1; submissionInFlight.current = null; downloadInFlight.current = null;
    setSubmitting(false); setDownloading(null); setError(null);
    try { adoptTask(verifyTextTask(saved)); }
    catch (cause) { setTask(null); setRestoreError(errorMessage(cause)); }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submissionInFlight.current !== null || loading || restoring) return;
    const current = ++generation.current;
    submissionInFlight.current = current;
    const form = new FormData(event.currentTarget);
    setSubmitting(true); setError(null); setRestoreError(null); setPollError(null);
    try {
      const saved = await createTextAnalysis({
        name: String(form.get("name") ?? "").trim(), query: String(form.get("query") ?? "").trim(),
        caseId: form.get("caseId") ? Number(form.get("caseId")) : null,
      });
      if (!mounted.current || generation.current !== current) return;
      adoptTask(verifyTextTask(saved));
      setWorkspace(previous => previous ? { ...previous, tasks: [saved, ...previous.tasks.filter(item => item.id !== saved.id)].slice(0, 8) } : previous);
      // A failed history refresh must not be reported as a failed creation.
      setReload(value => value + 1);
    } catch (cause) { if (mounted.current && generation.current === current) setError(errorMessage(cause)); }
    finally { if (submissionInFlight.current === current) submissionInFlight.current = null; if (mounted.current && generation.current === current) setSubmitting(false); }
  }

  async function download(format: "csv" | "pdf") {
    if (!task || task.status !== "succeeded" || downloadInFlight.current !== null) return;
    const current = generation.current;
    downloadInFlight.current = current;
    setDownloading(format); setError(null);
    try {
      const blob = await exportTextAnalysis(task.id, format);
      if (!mounted.current || generation.current !== current) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = `text-analysis-task-${task.id}.${format}`;
      anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) { if (mounted.current && generation.current === current) setError(errorMessage(cause)); }
    finally { if (downloadInFlight.current === current) downloadInFlight.current = null; if (mounted.current && generation.current === current) setDownloading(null); }
  }

  // Bind the visible result during render as well as in the restoration effect:
  // the first frame of a different URL must not show the preceding task.
  const visibleTask = savedTaskId === null || savedTaskId === String(task?.id) ? task : null;
  const result = visibleTask?.status === "succeeded" ? visibleTask.result : null;

  return <>
    <div className="page-heading">
      <div className="page-heading-copy">

        <div className="flex items-center gap-3"><span className="page-heading-icon"><FlaskConical size={20} /></span><h2 className="page-title">证候与网络药理智能分析</h2></div>
        <p className="page-description">根据医案或研究问题，整理证候、方药及相关靶点与通路。</p>
      </div>
      <div className="page-heading-action"><span className="status-badge status-success">结果自动保存</span></div>
    </div>
    <div className="workspace-split">
      <form className="panel space-y-4 p-5" onSubmit={submit} aria-label="证候方药关联分析">
        <div>
          <h2 className="text-lg font-black">证候-方药-靶点分析</h2>
          <p className="mt-1 text-sm text-ink/58">输入医案或选择已保存医案，自动生成分析链路。</p>
        </div>
        <label className="form-label">任务名称<input className="field mt-2" name="name" maxLength={200} defaultValue="中风病医案网络药理分析" placeholder="任务名称" required /></label>
        <label className="form-label">关联医案<select className="field mt-2" name="caseId" defaultValue="">
          <option value="">不绑定医案</option>
          {workspace?.cases.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
        </select></label>
        {workspace?.casesTruncated && <p className="notice-info">选择列表显示最近 200 个医案；可在医案管理核对较早记录。</p>}
        <label className="form-label">分析问题<textarea className="field mt-2 min-h-44" name="query" maxLength={20000} placeholder="输入症状、证候、方药或希望验证的研究问题" required /></label>
        {error && <p className="notice-error" role="alert">{error}</p>}
        <button className="btn btn-primary" disabled={submitting || loading || restoring}>
          <FlaskConical size={17} />{submitting ? "分析中..." : "开始分析"}
        </button>
      </form>
      <section className="panel min-h-[360px] p-5" aria-label="分析结果">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-lg font-black">分析结果</h2>
          {result && <div className="flex gap-2">
            <button className="btn btn-secondary text-sm" disabled={!!downloading} onClick={() => void download("csv")}><Download size={15} />{downloading === "csv" ? "生成中…" : "CSV"}</button>
            <button className="btn btn-secondary text-sm" disabled={!!downloading} onClick={() => void download("pdf")}><FileText size={15} />{downloading === "pdf" ? "生成中…" : "PDF"}</button>
          </div>}
        </div>
        {visibleTask && <p className="section-help">任务 #{visibleTask.id} · {String(visibleTask.input_parameters.name ?? "规则分析任务")}</p>}
        {restoring && <p className="section-help" role="status">正在读取指定分析任务…</p>}
        {restoreError && <div className="notice-error" role="alert"><p>分析任务读取失败：{restoreError}</p><button type="button" className="btn btn-secondary" onClick={() => setRestoreAttempt(value => value + 1)}>重新读取分析任务</button></div>}
        {pollError && <p className="notice-error" role="status">{pollError}</p>}
        {visibleTask && ["queued", "running"].includes(visibleTask.status) && <p className="section-help" role="status">任务 #{visibleTask.id} {visibleTask.status === "queued" ? "排队中" : "分析中"}（{visibleTask.progress}%）。</p>}
        {visibleTask?.status === "failed" && <p className="notice-error" role="alert">任务 #{visibleTask.id} 分析失败：{visibleTask.error_summary || "请核对输入后再提交新的分析。"}</p>}
        {visibleTask?.status === "cancelled" && <p className="notice-info">任务 #{visibleTask.id} 已取消。</p>}
        {result ? <div className="space-y-4">
          <p className="rounded-md bg-cloud p-4 leading-7">{result.summary}</p>
          <div className="grid gap-3 md:grid-cols-2">
            {evidenceLevels.filter(level => level in result.evidence).map(level => [level, result.evidence[level]] as const).map(([level, value]) => <div key={level} className="rounded-md border border-pine/10 bg-white/65 p-3">
              <p className="text-xs font-bold uppercase text-pine">{level}</p>
              <p className="mt-1 text-sm leading-6">{(Array.isArray(value) ? value.join("、") : value) || "暂无本地来源关联"}</p>
            </div>)}
          </div>
          <span className={`status-badge ${result.matchStatus === "matched" ? "status-success" : "status-pending"}`}>{matchLabels[result.matchStatus]} · 任务 #{visibleTask?.id}</span>
          <details>
            <summary className="section-help">关键词、来源与核查提示 · {result.warnings.length} 项提示</summary>
            <div className="mt-3 space-y-3">
              {result.warnings.map((warning) => <p className="notice-info" key={warning}>{warning}</p>)}
              <p className="section-help">算法 {result.algorithmVersion} · 规则来源 {result.ruleSource}</p>
              <ul className="proteomics-pathways">{result.ruleScores.map((rule) => <li key={rule.name}><strong>{rule.name} · {rule.score} 个关键词</strong><span>{rule.matchedKeywords.join("、") || "未命中"}</span></li>)}</ul>
              <h3 className="section-title-sm">来源与关系记录 · {result.evidenceRecords.length} 条</h3>
              <ul className="proteomics-pathways">{result.sources.map((source) => <li key={source.id}><strong>{source.source} · {source.version}</strong><span className="break-all">SHA-256：{source.checksumSha256 || "尚未登记"}</span></li>)}</ul>
              <div className="table-scroll"><table className="data-table"><thead><tr><th>起点</th><th>关系</th><th>终点</th><th>来源/版本</th><th>来源记录</th><th>证据类型</th></tr></thead><tbody>{result.evidenceRecords.map((record) => <tr key={record.refId}><td>{record.subjectLabel}</td><td>{record.relationType}</td><td>{record.objectLabel}</td><td>{record.source} · {record.sourceVersion}</td><td>{record.sourceRecordId}</td><td>{record.evidenceType}</td></tr>)}</tbody></table></div>
            </div>
          </details>
          {result.network.nodes.length > 0 && <details><summary className="section-help">查看证据网络</summary><div className="mt-3"><KnowledgeNetworkGraph network={result.network} knownTruncated={result.limits.relationsTruncated} /></div></details>}
        </div> : !visibleTask && !restoring && !restoreError && <div className="empty-state min-h-64"><FlaskConical size={26} /><strong>等待分析任务</strong><p>提交问题后查看分析结果。</p></div>}
      </section>
    </div>
    <section className="panel mt-6 overflow-hidden" aria-labelledby="analysis-history-title">
      <div className="panel-header"><div><h2 id="analysis-history-title" className="section-title-sm">已保存结果</h2><p className="section-help">最近八项分析任务。</p></div><History size={18} className="text-cinnabar" /></div>
      <div className="divide-y divide-pine/10">
        {loading ? <p className="empty-state min-h-48" role="status">正在读取分析记录…</p> : historyError ? <div className="notice-error" role="alert"><p>分析记录读取失败：{historyError} 已保存的任务不会因此删除。</p><button type="button" className="btn btn-secondary" onClick={() => setReload(value => value + 1)}>重新读取分析记录</button></div> : workspace?.tasks.length ? workspace.tasks.map((saved) => <article className="saved-analysis" key={saved.id}>
          <div><p><button type="button" className="text-left hover:underline focus-visible:underline" disabled={submitting} onClick={() => selectSavedTask(saved)} aria-label={`查看结果：${String(saved.input_parameters.name ?? "规则分析任务")}`}>{String(saved.input_parameters.name ?? "规则分析任务")}</button></p><time dateTime={saved.created_at}>{new Date(saved.created_at).toLocaleDateString("zh-CN")}</time></div>
          <span>{saved.status === "succeeded" ? saved.result.summary : ({ queued: "排队中", running: "分析中", failed: "分析失败", cancelled: "已取消" })[saved.status]}</span>
        </article>) : <div className="empty-state min-h-48"><FlaskConical size={24} /><strong>暂无保存结果</strong><p>完成第一项分析后，结果摘要会出现在这里。</p></div>}
      </div>
    </section>
  </>;
}
