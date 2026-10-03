import { WorkspaceModuleNav } from "../components/WorkspaceModuleNav";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useOutletContext } from "react-router-dom";
import { Bot, CircleHelp, LoaderCircle, Search, X } from "lucide-react";
import { logout, type Session } from "../api/auth";
import { ApiError } from "../api/client";
import { createResearchAssistantTask } from "../api/assistant";
import { getAnalysisTask, type AnalysisTask } from "../api/datasets";
import { searchCatalogEntities, type KnowledgeEntity, type KnowledgeSearchPage } from "../api/catalog";

const entityTypes = [
  ["", "全部实体"], ["disease", "疾病"], ["herb", "中药"], ["formula", "方剂"],
  ["compound", "成分"], ["syndrome", "证候"], ["gene", "基因"], ["protein", "蛋白"], ["pathway", "通路"],
];
const entityLabels = Object.fromEntries(entityTypes.filter(([value]) => value).map(([value, label]) => [value, label]));

type AssistantResult = {
  analysisKind?: string;
  source?: string;
  answer?: string;
  citations?: string[];
  uncertainties?: string[];
  model?: { name: string; version: string } | null;
  evidence?: {
    entities: Array<{ refId: string; entityType: string; label: string; stableId: string; source: string | null; sourceVersion: string | null }>;
    relations: Array<{ refId: string; subject: string; predicate: string; object: string; evidenceType: string; evidenceText: string; source: string; sourceVersion: string; sourceRecordId: string }>;
    truncated: boolean;
  };
};

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "请求未完成，请稍后重试。";
}

export function ResearchAssistantPage() {
  const user = useOutletContext<NonNullable<Session["user"]>>();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [searchType, setSearchType] = useState("");
  const [results, setResults] = useState<KnowledgeSearchPage | null>(null);
  const [selected, setSelected] = useState<KnowledgeEntity[]>([]);
  const [question, setQuestion] = useState("");
  const [allowModel, setAllowModel] = useState(false);
  const [task, setTask] = useState<AnalysisTask | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!task || !["queued", "running"].includes(task.status)) return;
    const timer = window.setTimeout(() => {
      void getAnalysisTask(task.id).then(setTask).catch((cause: unknown) => setError(errorMessage(cause)));
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [task]);

  async function searchKnowledge(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!search.trim()) return;
    setError(null);
    setBusy(true);
    try { setResults(await searchCatalogEntities(search.trim(), searchType)); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  function addEntity(entity: KnowledgeEntity) {
    setSelected((items) => items.some((item) => item.id === entity.id) || items.length >= 8 ? items : [...items, entity]);
  }

  async function submitQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim() || !selected.length) return;
    setError(null);
    setTask(null);
    setBusy(true);
    try {
      setTask(await createResearchAssistantTask({
        question: question.trim(),
        entityIds: selected.map((entity) => entity.id),
        useModel: allowModel,
        confirmModelSharing: allowModel,
      }));
      setAllowModel(false);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function signOut() {
    try { await logout(); navigate("/login", { replace: true }); }
    catch (cause) { setError(errorMessage(cause)); }
  }

  const result = task?.status === "succeeded" ? task.result as AssistantResult : null;
  const citedEvidence = new Set(result?.citations ?? []);
  const allEvidence = [
    ...(result?.evidence?.entities ?? []).map((item) => ({ refId: item.refId, title: `${item.label} · ${item.stableId}`, detail: `${item.source ?? "来源未登记"} ${item.sourceVersion ?? ""}` })),
    ...(result?.evidence?.relations ?? []).map((item) => ({ refId: item.refId, title: `${item.subject} → ${item.object} · ${item.predicate}`, detail: `${item.source} ${item.sourceVersion} / ${item.sourceRecordId}${item.evidenceText ? ` · ${item.evidenceText}` : ""}` })),
  ];

  return <main className="workspace-page">
    <header className="workspace-nav">
      <Link to="/" className="site-brand" aria-label="远志 AI Scientist 首页"><img src="/images/yuanzhi-mark.png" alt="" width={42} height={42} className="brand-mark" /><span><strong>远志 AI Scientist</strong><small>研究者工作区</small></span></Link>
      <WorkspaceModuleNav isSuperuser={user.isSuperuser} />
      <div className="workspace-nav-actions"><span className="workspace-user">{user.username}{user.isSuperuser ? " · 平台管理员" : " · 研究者"}</span><button className="btn btn-secondary" type="button" onClick={() => void signOut()}>退出</button></div>
    </header>
    <div className="app-main workspace-main"><div className="app-main-inner">
      <div className="page-heading"><div className="page-heading-copy"><p className="page-kicker">Evidence-grounded assistant</p><h1 className="page-title">科研助手</h1><p className="page-description">先选取已启用来源版本的本地知识记录，再基于这些证据进行问答；不会自动猜测实体或补造数据库结果。</p></div><Link to="/research" className="btn btn-secondary"><Search size={16} />浏览知识目录</Link></div>
      {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
      <div className="case-workspace-grid">
        <section className="panel case-form">
          <div className="panel-header"><div><h2 className="section-title-sm">选择本地证据</h2><p className="section-help">最多选 8 个实体，平台只会附带这些实体及其有来源版本的关系。</p></div><span className="page-heading-icon"><Search size={19} /></span></div>
          <form className="case-form-fields" onSubmit={(event) => void searchKnowledge(event)}>
            <label className="form-label">名称<input className="field" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="例如：黄芪、肺纤维化、槲皮素" required /></label>
            <label className="form-label">实体类型<select className="field" value={searchType} onChange={(event) => setSearchType(event.target.value)}>{entityTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <button className="btn btn-secondary" type="submit" disabled={busy}><Search size={15} />搜索本地目录</button>
          </form>
          {results && <div className="knowledge-entity-list assistant-entity-results">{results.results.map((entity) => {
            const hasVersionedSource = Boolean(entity.source_slug && entity.source_version);
            return <button className="knowledge-entity-option" key={entity.id} type="button" disabled={!hasVersionedSource || selected.some((item) => item.id === entity.id) || selected.length >= 8} onClick={() => addEntity(entity)}><span><strong>{entity.label}</strong><small>{entityLabels[entity.entity_type] ?? entity.entity_type} · {entity.stable_id}</small></span><small>{hasVersionedSource ? `${entity.source_slug} ${entity.source_version}` : "来源版本未登记，不能用于助手"}</small></button>;
          })}{!results.results.length && <p className="section-help">没有匹配的启用目录记录。</p>}</div>}
          <div className="case-list-items assistant-selected-list"><h3 className="section-title-sm">已选择 {selected.length}/8</h3>{selected.length ? selected.map((entity) => <div className="panel assistant-selected-item" key={entity.id}><span><strong>{entity.label}</strong><small>{entity.source_slug ?? "来源未登记"} {entity.source_version ?? ""}</small></span><button className="btn btn-secondary" type="button" aria-label={`移除${entity.label}`} onClick={() => setSelected((items) => items.filter((item) => item.id !== entity.id))}><X size={15} /></button></div>) : <p className="section-help">尚未选择证据实体。</p>}</div>
        </section>
        <section className="case-list">
          <form className="panel case-form" onSubmit={(event) => void submitQuestion(event)}>
            <div className="panel-header"><div><h2 className="section-title-sm">提出研究问题</h2><p className="section-help">问题和任务结果会归属于当前账号，保留任务号及引用的数据来源版本。</p></div><span className="page-heading-icon"><Bot size={19} /></span></div>
            <label className="form-label" htmlFor="assistant-question">问题<textarea className="field case-textarea" id="assistant-question" maxLength={2000} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：本地记录中有哪些黄芪—成分—靶点关系？证据来自哪些版本？" required /></label>
            <label className="proteomics-consent"><input type="checkbox" checked={allowModel} onChange={(event) => setAllowModel(event.target.checked)} /><span><strong>同意将本次问题和已选本地证据发送给平台配置的本机/内网模型</strong><small>默认不调用模型；只会发送这次问题和页面列出的目录记录，不发送医案或上传文件。模型生成内容仍需人工核对。</small></span></label>
            <div className="case-form-footer"><p>未勾选时只保存并返回本地目录证据，不生成模型回答。</p><button className="btn btn-primary" type="submit" disabled={busy || !selected.length || !question.trim()}>{busy ? <LoaderCircle size={15} className="spin" /> : <Bot size={15} />}{busy ? "正在提交…" : "检索并分析"}</button></div>
          </form>
          {!task && <div className="panel empty-state"><CircleHelp size={25} /><strong>等待问题</strong><p>先选实体，再提交问题。需要模型时，提交前可以单独同意本次发送。</p></div>}
          {task && <section className="panel assistant-task-result" aria-live="polite">
            <div className="case-list-heading"><div><p className="page-kicker">Task #{task.id}</p><h2 className="section-title-sm">{task.status === "queued" || task.status === "running" ? "正在整理证据" : task.status === "succeeded" ? "证据与回答" : "任务未完成"}</h2></div><span className={`status-badge ${task.status === "succeeded" ? "status-success" : task.status === "failed" ? "status-warning" : ""}`}>{task.status}{["queued", "running"].includes(task.status) ? ` · ${task.progress}%` : ""}</span></div>
            {task.status === "failed" && <div className="notice-error" role="alert">{task.error_summary}</div>}
            {result && <>
              {result.answer && <><h3 className="section-title-sm">模型回答</h3><p className="assistant-answer">{result.answer}</p><p className="section-help">模型：{result.model?.name ?? "未知"} · 版本：{result.model?.version ?? "未知"}。内容为研究假设，须回看引用记录。</p></>}
              {!result.answer && <p className="section-help">已完成本地目录检索。本次没有调用生成式模型。</p>}
              {result.uncertainties?.map((item, index) => <p className="notice-info" key={index}>{item}</p>)}
              {result.evidence?.truncated && <p className="notice-info">关系记录超过本次上限，结果已截断；请缩小实体范围后重新检索。</p>}
              <h3 className="section-title-sm">本次证据 · {allEvidence.length} 条</h3>
              {allEvidence.length ? <ul className="proteomics-pathways">{allEvidence.map((item) => <li key={item.refId}><strong>{citedEvidence.has(item.refId) ? "模型已引用 · " : ""}{item.title}</strong><span>{item.detail}</span></li>)}</ul> : <p className="section-help">所选实体没有启用来源版本的关系记录。</p>}
            </>}
          </section>}
        </section>
      </div>
    </div></div>
  </main>;
}
