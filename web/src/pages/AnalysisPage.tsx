import { useEffect, useState, type FormEvent } from "react";
import { Download, FileText, FlaskConical, History } from "lucide-react";
import { ApiError } from "../api/client";
import { createTextAnalysis, exportTextAnalysis, getTextAnalysisWorkspace, type TextAnalysisTask, type TextAnalysisWorkspace } from "../api/analysis";
import { KnowledgeNetworkGraph } from "../components/KnowledgeNetworkGraph";

const matchLabels = { matched: "已有目录关联", no_rule_match: "未命中规则", catalog_missing: "缺少目录记录", ambiguous_syndrome: "目录同名歧义" };
function errorMessage(error: unknown) { return error instanceof ApiError ? error.message : "请求未完成，请稍后重试。"; }

export function AnalysisPage() {
  const [workspace, setWorkspace] = useState<TextAnalysisWorkspace | null>(null);
  const [task, setTask] = useState<TextAnalysisTask | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getTextAnalysisWorkspace().then((data) => { if (active) setWorkspace(data); })
      .catch((cause: unknown) => { if (active) setError(errorMessage(cause)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSubmitting(true); setError(null);
    try {
      const saved = await createTextAnalysis({
        name: String(form.get("name") ?? "").trim(), query: String(form.get("query") ?? "").trim(),
        caseId: form.get("caseId") ? Number(form.get("caseId")) : null,
      });
      setTask(saved);
      setWorkspace(await getTextAnalysisWorkspace());
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setSubmitting(false); }
  }

  async function download(format: "csv" | "pdf") {
    if (!task) return;
    setDownloading(format); setError(null);
    try {
      const blob = await exportTextAnalysis(task.id, format);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = `text-analysis-task-${task.id}.${format}`;
      anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setDownloading(null); }
  }

  const result = task?.result;

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
        <button className="btn btn-primary" disabled={submitting || loading}>
          <FlaskConical size={17} />{submitting ? "分析中..." : "开始分析"}
        </button>
      </form>
      <section className="panel min-h-[360px] p-5" aria-label="最新分析结果">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-lg font-black">最新分析结果</h2>
          {task && <div className="flex gap-2">
            <button className="btn btn-secondary text-sm" disabled={!!downloading} onClick={() => void download("csv")}><Download size={15} />{downloading === "csv" ? "生成中…" : "CSV"}</button>
            <button className="btn btn-secondary text-sm" disabled={!!downloading} onClick={() => void download("pdf")}><FileText size={15} />{downloading === "pdf" ? "生成中…" : "PDF"}</button>
          </div>}
        </div>
        {result ? <div className="space-y-4">
          <p className="rounded-md bg-cloud p-4 leading-7">{result.summary}</p>
          <div className="grid gap-3 md:grid-cols-2">
            {Object.entries(result.evidence).map(([level, value]) => <div key={level} className="rounded-md border border-pine/10 bg-white/65 p-3">
              <p className="text-xs font-bold uppercase text-pine">{level}</p>
              <p className="mt-1 text-sm leading-6">{(Array.isArray(value) ? value.join("、") : value) || "暂无本地来源关联"}</p>
            </div>)}
          </div>
          <span className={`status-badge ${result.matchStatus === "matched" ? "status-success" : "status-pending"}`}>{matchLabels[result.matchStatus]} · 任务 #{task?.id}</span>
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
        </div> : <div className="empty-state min-h-64"><FlaskConical size={26} /><strong>等待分析任务</strong><p>提交问题后查看分析结果。</p></div>}
      </section>
    </div>
    <section className="panel mt-6 overflow-hidden" aria-labelledby="analysis-history-title">
      <div className="panel-header"><div><h2 id="analysis-history-title" className="section-title-sm">已保存结果</h2><p className="section-help">最近八项分析任务。</p></div><History size={18} className="text-cinnabar" /></div>
      <div className="divide-y divide-pine/10">
        {loading ? <p className="empty-state min-h-48" role="status">正在读取分析记录…</p> : workspace?.tasks.length ? workspace.tasks.map((saved) => <article className="saved-analysis" key={saved.id}>
          <div><p><button type="button" className="text-left hover:underline focus-visible:underline" onClick={() => setTask(saved)} aria-label={`查看结果：${String(saved.input_parameters.name ?? "规则分析任务")}`}>{String(saved.input_parameters.name ?? "规则分析任务")}</button></p><time dateTime={saved.created_at}>{new Date(saved.created_at).toLocaleDateString("zh-CN")}</time></div>
          <span>{saved.result.summary}</span>
        </article>) : <div className="empty-state min-h-48"><FlaskConical size={24} /><strong>暂无保存结果</strong><p>完成第一项分析后，结果摘要会出现在这里。</p></div>}
      </div>
    </section>
  </>;
}
