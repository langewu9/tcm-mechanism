import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useOutletContext } from "react-router-dom";
import { Download, FileText, FlaskConical, History, LogOut } from "lucide-react";
import { logout, type Session } from "../api/auth";
import { ApiError } from "../api/client";
import { createTextAnalysis, exportTextAnalysis, getTextAnalysisWorkspace, type TextAnalysisTask, type TextAnalysisWorkspace } from "../api/analysis";
import { KnowledgeNetworkGraph } from "../components/KnowledgeNetworkGraph";
import { WorkspaceModuleNav } from "../components/WorkspaceModuleNav";

const evidenceLabels: Record<string, string> = { syndrome: "证候候选", formula: "关联方剂", herbs: "中药", compounds: "成分", targets: "靶点", genes: "基因", pathways: "通路" };
const matchLabels = { matched: "已有目录关联", no_rule_match: "未命中规则", catalog_missing: "缺少目录记录", ambiguous_syndrome: "目录同名歧义" };
function errorMessage(error: unknown) { return error instanceof ApiError ? error.message : "请求未完成，请稍后重试。"; }

export function AnalysisPage() {
  const user = useOutletContext<NonNullable<Session["user"]>>();
  const navigate = useNavigate();
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

  async function signOut() {
    try { await logout(); navigate("/login", { replace: true }); }
    catch (cause) { setError(errorMessage(cause)); }
  }
  const result = task?.result;

  return <main className="workspace-page">
    <header className="workspace-nav">
      <Link to="/" className="site-brand" aria-label="远志 AI Scientist 首页"><img src="/images/yuanzhi-mark.png" alt="" width={42} height={42} className="brand-mark" /><span><strong>远志 AI Scientist</strong><small>研究者工作区</small></span></Link>
      <WorkspaceModuleNav isSuperuser={user.isSuperuser} />
      <div className="workspace-nav-actions"><span className="workspace-user">{user.username}{user.isSuperuser ? " · 平台管理员" : " · 研究者"}</span><button className="btn btn-secondary" onClick={() => void signOut()}><LogOut size={16} />退出</button></div>
    </header>
    <div className="app-main workspace-main"><div className="app-main-inner">
      <div className="page-heading"><div className="page-heading-copy"><p className="page-kicker">Analysis workbench</p><h1 className="page-title">证候与方药关联分析</h1><p className="page-description">从医案或研究问题匹配旧版关键词规则，查看本地证候、方药、成分、靶点与通路的来源关联。</p></div><span className="status-badge status-success">结果自动保存</span></div>
      {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
      <div className="case-workspace-grid">
        <form className="panel case-form" onSubmit={submit} aria-label="证候方药关联分析">
          <div className="panel-header"><div><h2 className="section-title-sm">证候—方药—靶点分析</h2><p className="section-help">四组关键词规则仅提供候选，结果需结合原始资料和目录证据复核。</p></div></div>
          <div className="case-form-fields">
            <label className="form-label">任务名称<input className="field" name="name" maxLength={200} defaultValue="中风病医案网络药理分析" required /></label>
            <label className="form-label">关联医案<select className="field" name="caseId" defaultValue=""><option value="">不绑定医案</option>{workspace?.cases.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
            {workspace?.casesTruncated && <p className="notice-info">选择列表显示最近 200 个医案；可在医案管理核对较早记录。</p>}
            <label className="form-label">分析问题<textarea className="field case-textarea" name="query" maxLength={20000} placeholder="输入脱敏症状、证候、方药或希望验证的研究问题" required /></label>
          </div>
          <div className="case-form-footer"><p>结果来自本地规则和已登记知识目录。</p><button className="btn btn-primary" disabled={submitting || loading}><FlaskConical size={17} />{submitting ? "分析中…" : "开始分析"}</button></div>
        </form>
        <section className="panel proteomics-result-panel" aria-label="最新分析结果">
          <div className="case-list-heading"><h2 className="section-title-sm">最新分析结果</h2>{task && <div className="proteomics-export-actions"><button className="btn btn-secondary" disabled={!!downloading} onClick={() => void download("csv")}><Download size={15} />{downloading === "csv" ? "生成中…" : "CSV"}</button><button className="btn btn-secondary" disabled={!!downloading} onClick={() => void download("pdf")}><FileText size={15} />{downloading === "pdf" ? "生成中…" : "PDF"}</button></div>}</div>
          {result ? <>
            <span className={`status-badge ${result.matchStatus === "matched" ? "status-success" : "status-pending"}`}>{matchLabels[result.matchStatus]} · 任务 #{task?.id}</span>
            <p className="dataset-description">{result.summary}</p>
            {result.warnings.map((warning) => <p className="notice-info" key={warning}>{warning}</p>)}
            <details><summary>关键词命中依据</summary><ul className="proteomics-pathways">{result.ruleScores.map((rule) => <li key={rule.name}><strong>{rule.name} · {rule.score} 个关键词</strong><span>{rule.matchedKeywords.join("、") || "未命中"}</span></li>)}</ul></details>
            <div className="proteomics-validation-grid">{Object.entries(result.evidence).map(([level, value]) => <div key={level}><span>{evidenceLabels[level] ?? level}</span><p>{(Array.isArray(value) ? value.join("、") : value) || "暂无本地来源关联"}</p></div>)}</div>
            <p className="section-help">算法 {result.algorithmVersion} · 规则来源 {result.ruleSource}</p>
            <details><summary>来源与关系记录 · {result.evidenceRecords.length} 条</summary><ul className="proteomics-pathways">{result.sources.map((source) => <li key={source.id}><strong>{source.source} · {source.version}</strong><span>SHA-256：{source.checksumSha256 || "尚未登记"}</span></li>)}</ul>
              <div className="table-scroll"><table className="data-table"><thead><tr><th>起点</th><th>关系</th><th>终点</th><th>来源/版本</th><th>来源记录</th><th>证据类型</th></tr></thead><tbody>{result.evidenceRecords.map((record) => <tr key={record.refId}><td>{record.subjectLabel}</td><td>{record.relationType}</td><td>{record.objectLabel}</td><td>{record.source} · {record.sourceVersion}</td><td>{record.sourceRecordId}</td><td>{record.evidenceType}</td></tr>)}</tbody></table></div>
            </details>
          </> : <div className="empty-state dashboard-empty"><FlaskConical size={26} /><strong>等待分析任务</strong><p>提交研究问题后，这里会显示摘要、证据条目和导出入口。</p></div>}
        </section>
      </div>
      {result && result.network.nodes.length > 0 && <KnowledgeNetworkGraph network={result.network} knownTruncated={result.limits.relationsTruncated} />}
      <section className="panel dashboard-panel" aria-labelledby="analysis-history-title"><div className="panel-header"><div><h2 id="analysis-history-title" className="section-title-sm">已保存结果</h2><p className="section-help">最近八项规则分析任务</p></div><History size={18} /></div>
        {loading ? <p className="empty-state" role="status">正在读取分析记录…</p> : workspace?.tasks.length ? workspace.tasks.map((saved) => <article className="saved-analysis" key={saved.id}><div><p>{String(saved.input_parameters.name ?? "规则分析任务")}</p><time dateTime={saved.created_at}>{new Date(saved.created_at).toLocaleString("zh-CN")}</time><button className="btn btn-secondary" onClick={() => setTask(saved)}>查看结果</button></div><span>{saved.result.summary}</span></article>) : <div className="empty-state"><FlaskConical size={24} /><strong>暂无保存结果</strong><p>完成第一项分析后，摘要会出现在这里。</p></div>}
      </section>
    </div></div>
  </main>;
}
