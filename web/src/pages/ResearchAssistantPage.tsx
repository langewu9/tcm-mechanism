import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { Bot, CircleHelp, LoaderCircle, Search, X } from "lucide-react";
import { ApiError } from "../api/client";
import { createResearchAssistantTask } from "../api/assistant";
import { getAnalysisTask, type AnalysisTask } from "../api/datasets";
import { restoreLatestAssistantTask } from "../api/task-restoration";
import { searchCatalogEntities, type KnowledgeEntity, type KnowledgeSearchPage } from "../api/catalog";
import { ScientistReport, type ScientistReportResult } from "../components/ScientistReport";

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
  const location = useLocation();
  const [search, setSearch] = useState("");
  const [searchType, setSearchType] = useState("");
  const [results, setResults] = useState<KnowledgeSearchPage | null>(null);
  const [selected, setSelected] = useState<KnowledgeEntity[]>([]);
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<"evidence" | "scientist_hypothesis">("evidence");
  const [disease, setDisease] = useState("");
  const [formula, setFormula] = useState("");
  const [focus, setFocus] = useState("本地来源证据核对");
  const [allowModel, setAllowModel] = useState(false);
  const [task, setTask] = useState<AnalysisTask | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const [pollError, setPollError] = useState<string | null>(null);
  const [pollAttempt, setPollAttempt] = useState(0);
  const taskGeneration = useRef(0);
  const submissionInFlight = useRef(false);

  useEffect(() => {
    let active = true;
    const generation = taskGeneration.current;
    setRestoring(true); setRestoreError(null);
    const fixedId = new URLSearchParams(location.search).get("assistantTask");
    if (fixedId !== null) setTask(null);
    setAllowModel(false);
    const requestedId = fixedId === null ? undefined : /^[1-9]\d*$/.test(fixedId) ? Number(fixedId) : NaN;
    void restoreLatestAssistantTask(requestedId).then((saved) => {
      if (!active || generation !== taskGeneration.current || !saved) return;
      setTask(saved);
      // Restoration never restores model consent or resubmits a saved question.
      const question = saved.input_parameters.question;
      if (typeof question === "string") setQuestion((current) => fixedId !== null ? question.slice(0, 2000) : current || question.slice(0, 2000));
      if (saved.input_parameters.analysisKind === "scientist_hypothesis") {
        setMode("scientist_hypothesis");
        if (typeof saved.input_parameters.disease === "string") setDisease(saved.input_parameters.disease);
        if (Array.isArray(saved.input_parameters.formulaHerbs)) setFormula(saved.input_parameters.formulaHerbs.filter((value): value is string => typeof value === "string").join("、"));
        if (typeof saved.input_parameters.focus === "string") setFocus(saved.input_parameters.focus);
      } else setMode("evidence");
    }).catch((cause: unknown) => {
      if (active && generation === taskGeneration.current) setRestoreError(errorMessage(cause));
    }).finally(() => { if (active) setRestoring(false); });
    return () => { active = false; };
  }, [restoreAttempt, location.search]);

  useEffect(() => {
    const draft = (location.state as { draftQuestion?: unknown } | null)?.draftQuestion;
    if (typeof draft === "string") setQuestion(draft.slice(0, 2000));
  }, [location.state]);

  useEffect(() => {
    if (!task || !["queued", "running"].includes(task.status)) return;
    let active = true;
    const generation = taskGeneration.current;
    const timer = window.setTimeout(() => {
      void getAnalysisTask(task.id).then((updated) => {
        if (!active || generation !== taskGeneration.current) return;
        if (updated.id !== task.id || updated.task_type !== "research_assistant") throw new Error("任务身份不一致。");
        setTask(updated); setPollError(null);
      }).catch((cause: unknown) => {
        if (active && generation === taskGeneration.current) setPollError(errorMessage(cause));
      });
    }, 1500);
    return () => { active = false; window.clearTimeout(timer); };
  }, [task, pollAttempt]);

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
    if (!question.trim() || (mode === "evidence" ? !selected.length : !disease.trim() || !formula.trim()) || restoring || submissionInFlight.current) return;
    submissionInFlight.current = true;
    taskGeneration.current += 1;
    setRestoreError(null); setPollError(null);
    setError(null);
    setTask(null);
    setBusy(true);
    try {
      setTask(await createResearchAssistantTask(mode === "scientist_hypothesis" ? {
        mode, question: question.trim(), disease: disease.trim(), formula: formula.trim(), focus: focus.trim(),
        useModel: false, confirmModelSharing: false,
      } : {
        question: question.trim(),
        entityIds: selected.map((entity) => entity.id),
        useModel: allowModel,
        confirmModelSharing: allowModel,
      }));
      setAllowModel(false);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { submissionInFlight.current = false; setBusy(false); }
  }

  const result = task?.status === "succeeded" ? task.result as AssistantResult : null;
  const citedEvidence = new Set(result?.citations ?? []);
  const allEvidence = [
    ...(result?.evidence?.entities ?? []).map((item) => ({ refId: item.refId, title: `${item.label} · ${item.stableId}`, detail: `${item.source ?? "来源未登记"} ${item.sourceVersion ?? ""}` })),
    ...(result?.evidence?.relations ?? []).map((item) => ({ refId: item.refId, title: `${item.subject} → ${item.object} · ${item.predicate}`, detail: `${item.source} ${item.sourceVersion} / ${item.sourceRecordId}${item.evidenceText ? ` · ${item.evidenceText}` : ""}` })),
  ];

  return <>

      <div className="page-heading"><div className="page-heading-copy"><p className="page-kicker">Evidence-grounded assistant</p><h1 className="page-title">科研助手</h1><p className="page-description">选择本地证据问答，或按明确的疾病与方药组成生成本地研究计划；不会自动猜测实体或补造数据库结果。</p></div><Link to="/research" className="btn btn-secondary"><Search size={16} />浏览知识目录</Link></div>
      {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
      {restoring && <p className="notice-info workspace-notice" role="status">正在读取最近的助手任务…</p>}
      {restoreError && <div className="notice-error workspace-notice" role="alert"><p>最近任务读取失败：{restoreError}</p><button className="btn btn-secondary" type="button" disabled={restoring || busy} onClick={() => setRestoreAttempt((value) => value + 1)}>重新读取历史任务</button></div>}
      <div className="case-workspace-grid">
        <section className="panel case-form">
          <label className="form-label" htmlFor="assistant-mode">任务方式<select className="field" id="assistant-mode" value={mode} disabled={busy || restoring} onChange={event => { setMode(event.target.value as "evidence" | "scientist_hypothesis"); setAllowModel(false); }}><option value="evidence">本地证据问答</option><option value="scientist_hypothesis">AI Scientist 本地研究计划</option></select></label>
          {mode === "scientist_hypothesis" ? <div className="case-form-fields">
            <h2 className="section-title-sm">研究计划输入</h2>
            <p className="section-help">明确填写疾病及逐味中药组成；后台查询完整来源证据。本模式不调用模型。</p>
            <label className="form-label" htmlFor="scientist-disease">疾病<input id="scientist-disease" className="field" maxLength={160} value={disease} onChange={event => setDisease(event.target.value)} placeholder="例如：肺纤维化" /></label>
            <label className="form-label" htmlFor="scientist-formula">方药组成<textarea id="scientist-formula" className="field case-textarea" maxLength={2400} value={formula} onChange={event => setFormula(event.target.value)} placeholder="逐味填写，如：石榴皮、白茅根。最多 12 项，不从方剂名猜组成。" /></label>
            <label className="form-label" htmlFor="scientist-focus">研究重点<input id="scientist-focus" className="field" maxLength={300} value={focus} onChange={event => setFocus(event.target.value)} /></label>
          </div> : <>
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
          </>}
        </section>
        <section className="case-list">
          <form className="panel case-form" onSubmit={(event) => void submitQuestion(event)}>
            <div className="panel-header"><div><h2 className="section-title-sm">提出研究问题</h2><p className="section-help">问题和任务结果会归属于当前账号，保留任务号及引用的数据来源版本。</p></div><span className="page-heading-icon"><Bot size={19} /></span></div>
            <label className="form-label" htmlFor="assistant-question">问题<textarea className="field case-textarea" id="assistant-question" maxLength={2000} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：本地记录中有哪些黄芪—成分—靶点关系？证据来自哪些版本？" required /></label>
            {mode === "evidence" && <label className="proteomics-consent"><input type="checkbox" checked={allowModel} onChange={(event) => setAllowModel(event.target.checked)} /><span><strong>同意将本次问题和已选本地证据发送给平台配置的本机/内网模型</strong><small>默认不调用模型；只会发送这次问题和页面列出的目录记录，不发送医案或上传文件。模型生成内容仍需人工核对。</small></span></label>}
            <div className="case-form-footer"><p>{mode === "evidence" ? "未勾选时只保存并返回本地目录证据，不生成模型回答。" : "只生成本地证据报告与待验证计划，不执行外部分析或实验。"}</p><button className="btn btn-primary" type="submit" disabled={busy || restoring || (mode === "evidence" ? !selected.length : !disease.trim() || !formula.trim() || !focus.trim()) || !question.trim()}>{busy ? <LoaderCircle size={15} className="spin" /> : <Bot size={15} />}{busy ? "正在提交…" : mode === "evidence" ? "检索并分析" : "生成本地研究计划"}</button></div>
          </form>
          {!task && <div className="panel empty-state"><CircleHelp size={25} /><strong>等待问题</strong><p>先选实体，再提交问题。需要模型时，提交前可以单独同意本次发送。</p></div>}
          {task && <section className="panel assistant-task-result" aria-live="polite">
            <Link className="btn btn-secondary" to={`/assistant?assistantTask=${task.id}`}>此任务固定地址</Link>
            <div className="case-list-heading"><div><p className="page-kicker">Task #{task.id}</p><h2 className="section-title-sm">{task.status === "queued" || task.status === "running" ? "正在整理证据" : task.status === "succeeded" ? "证据与回答" : "任务未完成"}</h2></div><span className={`status-badge ${task.status === "succeeded" ? "status-success" : task.status === "failed" ? "status-warning" : ""}`}>{task.status}{["queued", "running"].includes(task.status) ? ` · ${task.progress}%` : ""}</span></div>
            {task.status === "failed" && <div className="notice-error" role="alert">{task.error_summary}</div>}
            {pollError && <div className="notice-error" role="alert"><p>暂时无法读取任务进度：{pollError} 任务未重新提交。</p><button className="btn btn-secondary" type="button" onClick={() => { setPollError(null); setPollAttempt((value) => value + 1); }}>重新读取任务</button></div>}
            {result?.analysisKind === "scientist_hypothesis" ? <ScientistReport key={task.id} taskId={task.id} result={task.result as unknown as ScientistReportResult} /> : result && <>
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

  </>;
}
