import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { Bot, CircleHelp, LoaderCircle, Search, X } from "lucide-react";
import { ApiError } from "../api/client";
import { createResearchAssistantTask } from "../api/assistant";
import { getAnalysisTask, type AnalysisTask } from "../api/datasets";
import { restoreLatestAssistantTask } from "../api/task-restoration";
import { searchCatalogEntities, type KnowledgeEntity, type KnowledgeSearchPage } from "../api/catalog";
import { getCaseCorpusSummary, type CaseCategory, type CaseCorpusSummary, type ReferenceCase } from "../api/caseCorpus";
import { CaseCorpusEvidence } from "../components/CaseCorpusEvidence";

const entityTypes = [
  ["", "全部实体"], ["disease", "疾病"], ["herb", "中药"], ["formula", "方剂"],
  ["compound", "成分"], ["syndrome", "证候"], ["gene", "基因"], ["protein", "蛋白"], ["pathway", "通路"],
];
const entityLabels = Object.fromEntries(entityTypes.filter(([value]) => value).map(([value, label]) => [value, label]));
const caseCategoryLabels: Record<string, string> = {
  pulmonary: "肺系",
  stroke: "中风",
  stomach: "胃病",
  pharyngitis: "咽炎",
  general: "综合",
};
const taskStatusLabels: Record<AnalysisTask["status"], string> = { queued: "排队中", running: "运行中", succeeded: "已完成", failed: "失败", cancelled: "已取消" };

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
    cases?: ReferenceCase[];
    caseCorpus?: CaseCorpusSummary & { matchedCount: number; truncated: boolean };
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
  const [allowModel, setAllowModel] = useState(false);
  const [task, setTask] = useState<AnalysisTask | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [corpus, setCorpus] = useState<CaseCorpusSummary | null>(null);
  const [caseCategory, setCaseCategory] = useState<CaseCategory>("");
  const [referenceCases, setReferenceCases] = useState<Array<{ id: number; title: string }>>([]);
  const mounted = useRef(true);
  const submitting = useRef(false);
  const searchSequence = useRef(0);

  useEffect(() => {
    mounted.current = true;
    getCaseCorpusSummary().then(data => { if (mounted.current) setCorpus(data); }).catch(() => {});
    return () => { mounted.current = false; searchSequence.current += 1; };
  }, []);
  const [restoring, setRestoring] = useState(true);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const [pollError, setPollError] = useState<string | null>(null);
  const [pollAttempt, setPollAttempt] = useState(0);
  const taskGeneration = useRef(0);

  useEffect(() => {
    let active = true;
    const generation = taskGeneration.current;
    setRestoring(true); setRestoreError(null);
    void restoreLatestAssistantTask().then((saved) => {
      if (!active || generation !== taskGeneration.current || !saved) return;
      setTask(saved);
      // Restoration never restores model consent or resubmits a saved question.
      const question = saved.input_parameters.question;
      if (typeof question === "string") setQuestion((current) => current || question.slice(0, 2000));
    }).catch((cause: unknown) => {
      if (active && generation === taskGeneration.current) setRestoreError(errorMessage(cause));
    }).finally(() => { if (active) setRestoring(false); });
    return () => { active = false; };
  }, [restoreAttempt]);

  useEffect(() => {
    const draft = (location.state as { draftQuestion?: unknown } | null)?.draftQuestion;
    if (typeof draft === "string") setQuestion(draft.slice(0, 2000));
    const references = (location.state as { referenceCases?: unknown } | null)?.referenceCases;
    setReferenceCases(Array.isArray(references) ? references.filter((item): item is { id: number; title: string } =>
      item && typeof item === "object" && Number.isSafeInteger(item.id) && item.id > 0 && typeof item.title === "string").slice(0, 4) : []);
    setAllowModel(false);
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
    if (!search.trim() || submitting.current) return;
    const sequence = ++searchSequence.current;
    setError(null);
    setBusy(true);
    try { const data = await searchCatalogEntities(search.trim(), searchType); if (mounted.current && sequence === searchSequence.current) setResults(data); }
    catch (cause) { if (mounted.current && sequence === searchSequence.current) setError(errorMessage(cause)); }
    finally { if (mounted.current && sequence === searchSequence.current) setBusy(false); }
  }

  function addEntity(entity: KnowledgeEntity) {
    setAllowModel(false);
    setSelected((items) => items.some((item) => item.id === entity.id) || items.length >= 8 ? items : [...items, entity]);
  }

  async function submitQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim() || submitting.current || busy || restoring) return;
    submitting.current = true;
    taskGeneration.current += 1;
    setRestoreError(null); setPollError(null);
    searchSequence.current += 1;
    setError(null);
    setTask(null);
    setBusy(true);
    try {
      const created = await createResearchAssistantTask({
        question: question.trim(),
        entityIds: selected.map((entity) => entity.id),
        useModel: allowModel,
        confirmModelSharing: allowModel,
        caseIds: referenceCases.map(record => record.id),
        caseCategory,
      });
      if (mounted.current) { setTask(created); setAllowModel(false); }
    } catch (cause) { if (mounted.current) setError(errorMessage(cause)); }
    finally { submitting.current = false; if (mounted.current) setBusy(false); }
  }

  const result = task?.status === "succeeded" ? task.result as AssistantResult : null;
  const citedEvidence = new Set(result?.citations ?? []);
  const allEvidence = [
    ...(result?.evidence?.entities ?? []).map((item) => ({ refId: item.refId, title: `${item.label} · ${item.stableId}`, detail: `${item.source ?? "来源未登记"} ${item.sourceVersion ?? ""}` })),
    ...(result?.evidence?.relations ?? []).map((item) => ({ refId: item.refId, title: `${item.subject} → ${item.object} · ${item.predicate}`, detail: `${item.source} ${item.sourceVersion} / ${item.sourceRecordId}${item.evidenceText ? ` · ${item.evidenceText}` : ""}` })),
  ];

  return <>

      <div className="page-heading"><div className="page-heading-copy"><h1 className="page-title">科研助手</h1><p className="page-description">选择本地数据，查询相关研究问题。</p></div><Link to="/research" className="btn btn-secondary"><Search size={16} />浏览知识目录</Link></div>
      {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
      {restoring && <p className="notice-info workspace-notice" role="status">正在读取最近的助手任务…</p>}
      {restoreError && <div className="notice-error workspace-notice" role="alert"><p>最近任务读取失败：{restoreError}</p><button className="btn btn-secondary" type="button" disabled={restoring || busy} onClick={() => setRestoreAttempt((value) => value + 1)}>重新读取历史任务</button></div>}
      <div className="case-workspace-grid workspace-split">
        <section className="panel case-form">
          <div className="panel-header"><div><h2 className="section-title-sm">补充知识目录（可选）</h2><p className="section-help">提交问题后会检索参考医案库；也可选 1–8 个实体补充关系证据。</p></div><span className="page-heading-icon"><Search size={19} /></span></div>
          <form className="case-form-fields" onSubmit={(event) => void searchKnowledge(event)}>
            <label className="form-label">名称<input className="field" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="例如：黄芪、肺纤维化、槲皮素" required /></label>
            <label className="form-label">实体类型<select className="field" value={searchType} onChange={(event) => setSearchType(event.target.value)}>{entityTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <button className="btn btn-secondary" type="submit" disabled={busy}><Search size={15} />搜索本地目录</button>
          </form>
          {results && <div className="knowledge-entity-list assistant-entity-results">{results.results.map((entity) => {
            const hasVersionedSource = Boolean(entity.source_slug && entity.source_version);
            return <button className="knowledge-entity-option" key={entity.id} type="button" disabled={!hasVersionedSource || selected.some((item) => item.id === entity.id) || selected.length >= 8} onClick={() => addEntity(entity)}><span><strong>{entity.label}</strong><small>{entityLabels[entity.entity_type] ?? entity.entity_type} · {entity.stable_id}</small></span><small>{hasVersionedSource ? `${entity.source_slug} ${entity.source_version}` : "来源版本未登记，不能用于助手"}</small></button>;
          })}{!results.results.length && <p className="section-help">没有匹配的启用目录记录。</p>}</div>}
          <div className="case-list-items assistant-selected-list"><h3 className="section-title-sm">已选择 {selected.length}/8</h3>{selected.length ? selected.map((entity) => <div className="panel assistant-selected-item" key={entity.id}><span><strong>{entity.label}</strong><small>{entity.source_slug ?? "来源未登记"} {entity.source_version ?? ""}</small></span><button className="btn btn-secondary" type="button" aria-label={`移除${entity.label}`} onClick={() => { setSelected((items) => items.filter((item) => item.id !== entity.id)); setAllowModel(false); }}><X size={15} /></button></div>) : <p className="section-help">无需选择实体也能直接检索医案库。</p>}</div>
        </section>
        <section className="case-list">
          <form className="panel case-form" onSubmit={(event) => void submitQuestion(event)}>
            <div className="panel-header"><div><h2 className="section-title-sm">提出研究问题</h2><p className="section-help">问题和任务结果会归属于当前账号，保留任务号及引用的数据来源版本。</p></div><span className="page-heading-icon"><Bot size={19} /></span></div>
            {referenceCases.length > 0 && <div className="assistant-reference-selection"><strong>已选参考医案</strong>{referenceCases.map(record => <p key={record.id}>{record.title}</p>)}<button type="button" className="btn btn-secondary" onClick={() => { setReferenceCases([]); setAllowModel(false); }}>清除选择</button></div>}
            <div className="case-form-fields"><label className="form-label">医案范围<select className="field" value={caseCategory} onChange={event => { setCaseCategory(event.target.value as CaseCategory); setAllowModel(false); }}><option value="">全部类别</option>{Object.entries(caseCategoryLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <label className="form-label" htmlFor="assistant-question">问题<textarea className="field case-textarea" id="assistant-question" maxLength={2000} value={question} onChange={(event) => { setQuestion(event.target.value); setAllowModel(false); }} placeholder="例如：检索咳嗽伴咳痰的医案，并查看证型与方药原文。" required /></label>
            <p className="section-help">{corpus?.available ? `参考医案 ${corpus.recordCount.toLocaleString("zh-CN")} 条 · 关键词检索` : "参考医案库连接待核验"}{corpus?.modelConfiguration?.configured ? ` · 模型配置：${corpus.modelConfiguration.name}` : " · 生成模型未配置，可正常检索原案"}</p>
            <label className="proteomics-consent"><input type="checkbox" checked={allowModel} disabled={!corpus?.modelConfiguration?.configured} onChange={(event) => setAllowModel(event.target.checked)} /><span><strong>使用本机 / 内网模型整理本次证据</strong><small>发送本次问题、所选知识记录和参考医案片段；不发送个人医案或附件。</small></span></label></div>
            <div className="case-form-footer"><p>未勾选时只检索并保存本地目录及医案出处，不生成模型回答。</p><button className="btn btn-primary" type="submit" disabled={busy || restoring || !question.trim()}>{busy ? <LoaderCircle size={15} className="spin" /> : <Bot size={15} />}{busy ? "正在提交…" : allowModel ? "检索并分析" : "检索证据"}</button></div>
          </form>
          {!task && <div className="panel empty-state"><CircleHelp size={25} /><strong>等待问题</strong><p>提交问题即可检索参考医案；需要模型回答时，再单独同意本次发送。</p></div>}
          {task && <section className="panel assistant-task-result" aria-live="polite">
            <div className="case-list-heading"><div><p className="section-help">任务 #{task.id}</p><h2 className="section-title-sm">{task.status === "queued" || task.status === "running" ? "正在整理证据" : task.status === "succeeded" ? "证据与回答" : "任务未完成"}</h2></div><span className={`status-badge ${task.status === "succeeded" ? "status-success" : task.status === "failed" ? "status-warning" : ""}`}>{taskStatusLabels[task.status]}{["queued", "running"].includes(task.status) ? ` · ${task.progress}%` : ""}</span></div>
            {task.status === "failed" && <div className="notice-error" role="alert">{task.error_summary}</div>}
            {pollError && <div className="notice-error" role="alert"><p>暂时无法读取任务进度：{pollError} 任务未重新提交。</p><button className="btn btn-secondary" type="button" onClick={() => { setPollError(null); setPollAttempt((value) => value + 1); }}>重新读取任务</button></div>}
            {result && <>
              {result.answer && <><h3 className="section-title-sm">模型回答</h3><p className="assistant-answer">{result.answer}</p><p className="section-help">模型：{result.model?.name ?? "未知"} · 版本：{result.model?.version ?? "未知"}。内容为研究假设，须回看引用记录。</p></>}
              <p className="section-help">检索问题：{String(task.input_parameters.question ?? "")}</p>
              {!result.answer && <p className="section-help">检索完成，以下为本次参考记录。</p>}
              {result.uncertainties?.map((item, index) => <p className="notice-info" key={index}>{item}</p>)}
              {result.evidence?.caseCorpus && (result.evidence.caseCorpus.available ? <p className="section-help">医案库共 {result.evidence.caseCorpus.recordCount} 条 · 本次关键词命中 {result.evidence.caseCorpus.matchedCount} 条，展示 {(result.evidence.cases ?? []).length} 条（包含主动选择）。</p> : <p className="notice-info">参考医案库暂不可用，本次仅展示知识目录记录。</p>)}
              {result.evidence?.truncated && <p className="notice-info">命中记录超过本次展示上限，当前展示相关度最高的医案与关系记录。</p>}
              <h3 className="section-title-sm">参考医案 · {(result.evidence?.cases ?? []).length} 条</h3>
              <CaseCorpusEvidence records={result.evidence?.cases ?? []} citations={result.citations} />
              {!(result.evidence?.cases ?? []).length && <p className="section-help">没有命中参考医案，可以更换症状、证型或分类。</p>}
              {allEvidence.length > 0 && <><h3 className="section-title-sm">知识目录证据 · {allEvidence.length} 条</h3><ul className="proteomics-pathways">{allEvidence.map((item) => <li key={item.refId}><strong>{citedEvidence.has(item.refId) ? "模型已引用 · " : ""}{item.title}</strong><span>{item.detail}</span></li>)}</ul></>}
            </>}
          </section>}
        </section>
      </div>

  </>;
}
