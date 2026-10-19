import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { ArrowLeft, FileHeart, Save, Sparkles, Stethoscope, Archive, RotateCcw } from "lucide-react";
import { approveMedicalCase, createMedicalCase, deleteMedicalCase, getMedicalCaseAnalysis, getMedicalCaseAudit, getMedicalCases, restoreMedicalCase, reviewMedicalCaseCandidate, startMedicalCaseAnalysis, type CaseAuditEvent, type CaseEvidence, type CaseKnowledgeEvidence, type MedicalCase, type MedicalCaseCandidate, type MedicalCaseAnalysis, type Page } from "../api/cases";
import { getAnalysisTask, type AnalysisTask } from "../api/datasets";
import { type Session } from "../api/auth";
import { ApiError } from "../api/client";

function valueOf(data: Record<string, unknown>, key: string) {
  const value = data[key];
  return typeof value === "string" && value.trim() ? value : "未填写";
}

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "请求未完成，请稍后重试。";
}

type CaseAnalysisResult = {
  model?: { name?: string; version?: string };
  observations?: Array<{ type: string; value: string; evidence: CaseEvidence[] }>;
  warnings?: string[];
  retrievalContext?: {
    entities: CaseKnowledgeEvidence[];
    relations: CaseKnowledgeEvidence[];
    sources: Array<{ id: number; source: string; sourceSlug: string; version: string }>;
    truncated?: boolean;
  };
  evidenceChain?: {
    nodes: Array<{ id: number; label: string; entityType: string; stableId: string }>;
    links: Array<{ id: number; source: number; target: number; relationType: string; evidenceType: string; sourceName: string; sourceVersion: string; sourceRecordId: string; evidenceText: string }>;
    sources: Array<{ id: number; source: string; version: string }>;
    truncated?: boolean;
  };
};

const observationLabels: Record<string, string> = { symptom: "症状", tongue: "舌象", pulse: "脉象", course: "病程", diagnosis: "已有诊断" };
const evidenceFieldLabels: Record<string, string> = {
  deidentified_text: "脱敏正文",
  "structured_data.tongue_pulse": "舌脉资料",
  "structured_data.diagnosis": "已有诊断",
};
const candidateMatchLabels: Record<MedicalCaseCandidate["match_status"], string> = {
  exact: "已关联本地规范实体",
  unmatched: "本地知识库暂未收录",
  ambiguous: "本地存在多个同名实体",
};
const candidateReviewLabels: Record<MedicalCaseCandidate["review_status"], string> = {
  pending: "待研究者确认",
  accepted: "已确认",
  rejected: "已驳回",
};

function caseResult(task: AnalysisTask | null): CaseAnalysisResult {
  return task?.result && typeof task.result === "object" ? task.result as CaseAnalysisResult : {};
}

function taskStatusLabel(task: AnalysisTask | null) {
  if (!task) return "尚未分析";
  if (task.status === "queued") return "排队中";
  if (task.status === "running") return `分析中 · ${task.progress}%`;
  if (task.status === "succeeded") return "分析完成";
  if (task.status === "failed") return "分析失败";
  return "任务已取消";
}

export function CasesPage() {
  const user = useOutletContext<NonNullable<Session["user"]>>();
  const mounted = useRef(false);
  const mutationInFlight = useRef(false);
  const casesRequestSequence = useRef(0);
  const auditRequestSequence = useRef(0);
  const activeAuditCaseId = useRef<number | null>(null);
  const analysisRequestSequence = useRef(0);
  const [page, setPage] = useState<Page<MedicalCase> | null>(null);
  const [archived, setArchived] = useState(false);
  const [pageNumber, setPageNumber] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [auditCaseId, setAuditCaseId] = useState<number | null>(null);
  const [auditEvents, setAuditEvents] = useState<CaseAuditEvent[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [reviewingId, setReviewingId] = useState<number | null>(null);
  const [analysisCaseId, setAnalysisCaseId] = useState<number | null>(null);
  const [analysisTask, setAnalysisTask] = useState<AnalysisTask | null>(null);
  const [analysisCandidates, setAnalysisCandidates] = useState<MedicalCaseCandidate[]>([]);
  const [analysisStale, setAnalysisStale] = useState(false);
  const [analysisModelConfiguration, setAnalysisModelConfiguration] = useState<MedicalCaseAnalysis["modelConfiguration"]>({ configured: false, name: null, version: null });
  const [analysisLoadingId, setAnalysisLoadingId] = useState<number | null>(null);
  const [analysisPollFailures, setAnalysisPollFailures] = useState(0);
  const [analysisConsent, setAnalysisConsent] = useState(false);
  const [candidateReviewId, setCandidateReviewId] = useState<number | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      casesRequestSequence.current += 1;
      auditRequestSequence.current += 1;
      analysisRequestSequence.current += 1;
    };
  }, []);

  const loadCases = useCallback(async () => {
    const requestSequence = ++casesRequestSequence.current;
    setLoading(true);
    setListError(null);
    try {
      const response = await getMedicalCases(pageNumber, archived);
      if (!mounted.current || requestSequence !== casesRequestSequence.current) return;
      setPage(response);
    } catch (cause) {
      if (!mounted.current || requestSequence !== casesRequestSequence.current) return;
      setListError(errorMessage(cause));
    } finally {
      if (!mounted.current || requestSequence !== casesRequestSequence.current) return;
      setLoading(false);
    }
  }, [pageNumber, archived]);

  useEffect(() => {
    void loadCases();
    return () => { casesRequestSequence.current += 1; };
  }, [loadCases, refresh]);

  useEffect(() => {
    if (analysisCaseId === null || !analysisTask || !["queued", "running"].includes(analysisTask.status)) return;
    const requestSequence = analysisRequestSequence.current;
    const delay = Math.min(1500 * (2 ** analysisPollFailures), 12000);
    const timer = window.setTimeout(() => {
      void getAnalysisTask(analysisTask.id).then(async (latest) => {
        if (requestSequence !== analysisRequestSequence.current) return;
        setAnalysisPollFailures(0);
        setAnalysisTask(latest);
        if (!["queued", "running"].includes(latest.status)) {
          const current = await getMedicalCaseAnalysis(analysisCaseId);
          if (requestSequence !== analysisRequestSequence.current) return;
          setAnalysisTask(current.task ?? latest);
          setAnalysisCandidates(current.candidates);
          setAnalysisStale(current.stale);
          setAnalysisModelConfiguration(current.modelConfiguration);
        }
      }).catch((cause: unknown) => {
        if (requestSequence !== analysisRequestSequence.current) return;
        setError(errorMessage(cause));
        setAnalysisPollFailures((count) => count + 1);
      });
    }, delay);
    return () => window.clearTimeout(timer);
  }, [analysisCaseId, analysisTask, analysisPollFailures]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutationInFlight.current) return;
    mutationInFlight.current = true;
    const formElement = event.currentTarget;
    setSaving(true);
    setError(null);
    setNotice(null);
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim();
    try {
      await createMedicalCase({
        title: text("title"),
        deidentified_text: text("symptoms"),
        structured_data: {
          patient_info: text("patient_info"),
          tongue_pulse: text("tongue_pulse"),
          diagnosis: text("diagnosis"),
        },
        source_reference: text("source_reference"),
        research_notes: text("research_notes"),
      });
      if (!mounted.current) return;
      formElement.reset();
      setNotice("医案已保存，来源和提交账号已记录。");
      setArchived(false);
      if (pageNumber !== 1) setPageNumber(1);
      else setRefresh((value) => value + 1);
    } catch (cause) {
      if (mounted.current) setError(errorMessage(cause));
    } finally {
      mutationInFlight.current = false;
      if (mounted.current) setSaving(false);
    }
  }

  async function removeCase(item: MedicalCase) {
    if (mutationInFlight.current) return;
    if (!window.confirm(item.archived_at ? `恢复医案“${item.title}”？` : `归档医案“${item.title}”？正文、来源和分析记录将保留，已提交任务继续运行。`)) return;
    mutationInFlight.current = true;
    setDeletingId(item.id);
    setError(null);
    setNotice(null);
    try {
      if (item.archived_at) await restoreMedicalCase(item.id);
      else await deleteMedicalCase(item.id);
      if (!mounted.current) return;
      setNotice(item.archived_at ? "医案已恢复。" : "医案已归档，正文、来源和分析记录均已保留。");
      if (pageNumber > 1 && page?.results.length === 1) setPageNumber((value) => value - 1);
      else setRefresh((value) => value + 1);
    } catch (cause) {
      if (mounted.current) setError(errorMessage(cause));
    } finally {
      mutationInFlight.current = false;
      if (mounted.current) setDeletingId(null);
    }
  }

  async function loadAudit(caseId: number) {
    const requestSequence = ++auditRequestSequence.current;
    setAuditLoading(true);
    setAuditError(null);
    try {
      const response = await getMedicalCaseAudit(caseId);
      if (!mounted.current || requestSequence !== auditRequestSequence.current || activeAuditCaseId.current !== caseId) return;
      setAuditEvents(response.results);
    } catch (cause) {
      if (!mounted.current || requestSequence !== auditRequestSequence.current || activeAuditCaseId.current !== caseId) return;
      setAuditError(errorMessage(cause));
    } finally {
      if (mounted.current && requestSequence === auditRequestSequence.current && activeAuditCaseId.current === caseId) setAuditLoading(false);
    }
  }

  async function toggleAudit(item: MedicalCase) {
    if (activeAuditCaseId.current === item.id) {
      auditRequestSequence.current += 1;
      activeAuditCaseId.current = null;
      setAuditCaseId(null);
      setAuditEvents([]);
      setAuditLoading(false);
      setAuditError(null);
      return;
    }
    activeAuditCaseId.current = item.id;
    setAuditCaseId(item.id);
    setAuditEvents([]);
    setError(null);
    await loadAudit(item.id);
  }

  async function approveCase(item: MedicalCase) {
    if (mutationInFlight.current) return;
    if (!window.confirm(`确认审核通过“${item.title}”？这会记录审核账号和时间。`)) return;
    mutationInFlight.current = true;
    setReviewingId(item.id);
    setError(null);
    setNotice(null);
    try {
      await approveMedicalCase(item.id);
      if (!mounted.current) return;
      setNotice("医案已审核，审核账号和时间已写入审计记录。");
      setRefresh((value) => value + 1);
      if (activeAuditCaseId.current === item.id) await loadAudit(item.id);
    } catch (cause) {
      if (!mounted.current) return;
      setError(errorMessage(cause));
    } finally {
      mutationInFlight.current = false;
      if (mounted.current) setReviewingId(null);
    }
  }

  async function toggleCaseAnalysis(item: MedicalCase) {
    if (analysisCaseId === item.id) {
      analysisRequestSequence.current += 1;
      setAnalysisCaseId(null);
      setAnalysisTask(null);
      setAnalysisCandidates([]);
      setAnalysisStale(false);
      setAnalysisModelConfiguration({ configured: false, name: null, version: null });
      setAnalysisPollFailures(0);
      setAnalysisConsent(false);
      return;
    }
    const requestSequence = analysisRequestSequence.current + 1;
    analysisRequestSequence.current = requestSequence;
    setAnalysisCaseId(item.id);
    setAnalysisTask(null);
    setAnalysisCandidates([]);
    setAnalysisStale(false);
    setAnalysisModelConfiguration({ configured: false, name: null, version: null });
    setAnalysisPollFailures(0);
    setAnalysisConsent(false);
    setAnalysisLoadingId(item.id);
    setError(null);
    try {
      const response = await getMedicalCaseAnalysis(item.id);
      if (requestSequence !== analysisRequestSequence.current) return;
      setAnalysisTask(response.task);
      setAnalysisCandidates(response.candidates);
      setAnalysisStale(response.stale);
      setAnalysisModelConfiguration(response.modelConfiguration);
    } catch (cause) {
      if (requestSequence !== analysisRequestSequence.current) return;
      setAnalysisCaseId(null);
      setError(errorMessage(cause));
    } finally {
      if (requestSequence === analysisRequestSequence.current) setAnalysisLoadingId(null);
    }
  }

  async function runCaseAnalysis(item: MedicalCase) {
    const requestSequence = analysisRequestSequence.current;
    setAnalysisLoadingId(item.id);
    setError(null);
    setNotice(null);
    try {
      const task = await startMedicalCaseAnalysis(item.id);
      if (requestSequence !== analysisRequestSequence.current) return;
      setAnalysisTask(task);
      setAnalysisCandidates([]);
      setAnalysisStale(false);
      setAnalysisConsent(false);
      setNotice("医案分析任务已提交到平台配置的本地模型。");
    } catch (cause) {
      if (requestSequence !== analysisRequestSequence.current) return;
      setError(errorMessage(cause));
    } finally {
      if (requestSequence === analysisRequestSequence.current) setAnalysisLoadingId(null);
    }
  }

  async function decideCandidate(item: MedicalCase, candidate: MedicalCaseCandidate, decision: "accept" | "reject") {
    const requestSequence = analysisRequestSequence.current;
    setCandidateReviewId(candidate.id);
    setError(null);
    setNotice(null);
    try {
      await reviewMedicalCaseCandidate(item.id, candidate.id, decision);
      const refreshed = await getMedicalCaseAnalysis(item.id);
      if (requestSequence !== analysisRequestSequence.current) return;
      setAnalysisTask(refreshed.task);
      setAnalysisCandidates(refreshed.candidates);
      setAnalysisStale(refreshed.stale);
      setAnalysisModelConfiguration(refreshed.modelConfiguration);
      setNotice(decision === "accept" ? "候选已确认，并已更新带来源版本的证据链。" : "候选已驳回，审计记录已保存。");
    } catch (cause) {
      if (requestSequence !== analysisRequestSequence.current) return;
      setError(errorMessage(cause));
    } finally {
      if (requestSequence === analysisRequestSequence.current) setCandidateReviewId(null);
    }
  }

  const mutating = saving || deletingId !== null || reviewingId !== null;

  return <>
      <div className="page-heading">
        <div className="page-heading-copy">
          <p className="page-kicker">Medical cases</p>
          <div className="flex items-center gap-3"><span className="page-heading-icon"><FileHeart size={20} /></span><h1 className="page-title">结构化医案库</h1></div>
          <p className="page-description">沉淀症状、舌脉、诊断与来源，为证候和网络药理分析提供上下文。</p>
        </div>
        <div className="page-heading-action"><span className="status-badge status-success">{loading ? "…" : listError ? "—" : page?.count ?? "—"} 条医案</span></div>
      </div>

      {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
      {notice && <div className="notice-success workspace-notice" role="status">{notice}</div>}

      <div className="grid gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
        <form className="panel space-y-3 p-5" onSubmit={submit} aria-label="新增医案">
          <div><h2 className="section-title-sm">新增医案</h2><p className="section-help">录入结构化医案，后续可直接用于智能分析。</p></div>
          <label className="form-label" htmlFor="case-title">医案标题<input className="field mt-2" id="case-title" name="title" maxLength={200} placeholder="例如：麦门冬汤干预肺纤维化研究医案" required /></label>
          <label className="form-label" htmlFor="case-patient">患者信息<input className="field mt-2" id="case-patient" name="patient_info" placeholder="年龄、性别等脱敏信息" /></label>
          <label className="form-label" htmlFor="case-symptoms">症状与主诉<textarea className="field mt-2 min-h-24" id="case-symptoms" name="symptoms" placeholder="主要症状、现病史与伴随表现" required /></label>
          <label className="form-label" htmlFor="case-tongue-pulse">舌脉<input className="field mt-2" id="case-tongue-pulse" name="tongue_pulse" placeholder="舌质、舌苔、脉象" /></label>
          <label className="form-label" htmlFor="case-diagnosis">诊断或证候<input className="field mt-2" id="case-diagnosis" name="diagnosis" placeholder="中医证候或西医诊断" /></label>
          <label className="form-label" htmlFor="case-source">资料来源<input className="field mt-2" id="case-source" name="source_reference" maxLength={500} placeholder="病例集、文献或门诊记录" /></label>
          <p className="section-help">请仅提交已去标识化的研究资料，勿填写姓名、电话或证件号。来源和提交账号将随记录保存，普通研究者只能查看自己的医案。</p>
          <details>
            <summary className="section-help">补充研究备注</summary>
            <div className="mt-3"><label className="form-label" htmlFor="case-notes">研究备注<textarea className="field mt-2 min-h-24" id="case-notes" name="research_notes" placeholder="补充研究背景、数据处理说明等" /></label></div>
          </details>
          <button className="btn btn-primary" type="submit" disabled={mutating}><Save size={17} />{saving ? "正在保存…" : "保存医案"}</button>
        </form>

        <section className="space-y-4" aria-label="已保存医案">
          <label className="form-label">显示范围<select className="field mt-2" value={String(archived)} disabled={mutating} onChange={(event) => { casesRequestSequence.current += 1; setPage(null); setLoading(true); setArchived(event.target.value === "true"); setPageNumber(1); }}><option value="false">使用中的医案</option><option value="true">已归档的医案</option></select></label>
          {loading ? <div className="panel empty-state" role="status">正在读取医案…</div>
            : listError ? <div className="panel empty-state" role="alert"><FileHeart size={26} /><strong>医案读取失败</strong><p>{listError}</p><button className="btn btn-secondary" type="button" onClick={() => setRefresh((value) => value + 1)} disabled={mutating}>重新读取</button></div>
            : page?.results.length ? page.results.map((item) => <article key={item.id} className="case-record panel p-5">
              <div className="flex items-start justify-between gap-3">
                <div><h2 className="text-lg font-black">{item.title}</h2><p className="mt-2 text-sm leading-6 text-ink/65">{item.deidentified_text}</p></div>
                <button className="btn btn-secondary px-2 py-1 text-xs text-cinnabar" type="button" onClick={() => void removeCase(item)} disabled={mutating} aria-label={`${item.archived_at ? "恢复" : "归档"}医案：${item.title}`} title={item.archived_at ? "恢复医案" : "归档并保留正文"}>{item.archived_at ? <RotateCcw size={14} /> : <Archive size={14} />}{deletingId === item.id ? "处理中" : item.archived_at ? "恢复" : "归档"}</button>
              </div>
              <div className="case-record-meta">
                <p><span>舌脉</span>{valueOf(item.structured_data, "tongue_pulse")}</p>
                <p><span>诊断</span>{valueOf(item.structured_data, "diagnosis")}</p>
                <p><span>来源</span>{item.source_reference || "未填写"}</p>
              </div>
              <details className="case-notes">
                <summary>研究详情、审核与分析</summary>
                <div className="mt-3 space-y-3">
                  <p><span className={`status-badge ${item.review_status === "reviewed" ? "status-success" : "status-warning"}`}>{item.review_status === "reviewed" ? `已审核 · ${item.reviewed_by_username ?? "平台管理员"}` : "待审核"}</span></p>
                  <p>脱敏患者信息：{valueOf(item.structured_data, "patient_info")}</p>
                  <p>提交研究者：{item.owner_username}</p>
                  <p><time dateTime={item.updated_at}>更新于 {new Date(item.updated_at).toLocaleString("zh-CN")}</time></p>
                  {item.reviewed_at && <p><time dateTime={item.reviewed_at}>审核于 {new Date(item.reviewed_at).toLocaleString("zh-CN")}</time></p>}
                  {item.research_notes && <div><h3 className="section-title-sm">研究备注</h3><p>{item.research_notes}</p></div>}
                  <div className="source-record-actions">
                    <button className="btn btn-secondary" type="button" onClick={() => void toggleAudit(item)} disabled={mutating}>{auditCaseId === item.id ? "收起审计记录" : "查看审计记录"}</button>
                    <button className="btn btn-secondary" type="button" onClick={() => void toggleCaseAnalysis(item)} disabled={mutating}>{analysisCaseId === item.id ? "收起分析" : "证候与方剂分析"}</button>
                    {user.isSuperuser && item.review_status !== "reviewed" && <button className="btn btn-primary" type="button" onClick={() => void approveCase(item)} disabled={mutating || !!item.archived_at}>{reviewingId === item.id ? "正在审核…" : "审核通过"}</button>}
                  </div>
                  {analysisCaseId === item.id && <fieldset disabled={mutating || !!item.archived_at} className="min-w-0"><CaseAnalysisPanel
                    task={analysisTask}
                    candidates={analysisCandidates}
                    stale={analysisStale}
                    modelConfiguration={analysisModelConfiguration}
                    caseId={item.id}
                    disease={valueOf(item.structured_data, "diagnosis") === "未填写" ? "" : valueOf(item.structured_data, "diagnosis")}
                    loading={analysisLoadingId === item.id}
                    consent={analysisConsent}
                    reviewingCandidateId={candidateReviewId}
                    onConsentChange={setAnalysisConsent}
                    onAnalyze={() => void runCaseAnalysis(item)}
                    onDecision={(candidate, decision) => void decideCandidate(item, candidate, decision)}
                  /></fieldset>}
                  {auditCaseId === item.id && <div className="panel case-audit-history"><h4>操作记录</h4>{auditLoading ? <p className="section-help" role="status">正在读取操作记录…</p> : auditError ? <div className="notice-error" role="alert"><p>{auditError}</p><button className="btn btn-secondary" type="button" onClick={() => void loadAudit(item.id)} disabled={mutating}>重新读取</button></div> : auditEvents.length ? <ul className="proteomics-pathways">{auditEvents.map((event) => <li key={event.id}><strong>{event.actor_username ?? "账号已删除"} · {event.action === "created" ? "创建" : event.action === "updated" ? "修改" : event.action === "reviewed" ? "审核" : event.action === "candidate" ? "候选审核" : event.action === "analyzed" ? "启动分析" : event.action === "archived" ? "归档" : event.action === "restored" ? "恢复" : "历史删除"}</strong><span>{new Date(event.created_at).toLocaleString("zh-CN")} · {event.changed_fields.join("、") || "无字段变化"}</span></li>)}</ul> : <p className="section-help">尚无操作记录。</p>}</div>}
                </div>
              </details>
            </article>)
            : page?.count === 0 ? <div className="panel empty-state"><Stethoscope size={26} /><strong>暂无医案</strong><p>录入第一条脱敏医案后，可在智能分析中选择。证据关联依赖真实目录记录，模型候选需可用服务并由研究者逐条确认。</p></div>
            : <div className="panel empty-state"><Stethoscope size={26} /><strong>本页暂无医案</strong><p>请返回上一页或重新读取医案。</p><button className="btn btn-secondary" type="button" onClick={() => { setPageNumber(1); setRefresh((value) => value + 1); }} disabled={mutating}>返回第一页</button></div>}
          {page && page.count > 0 && !listError && <div className="case-pagination"><button className="btn btn-secondary" type="button" disabled={!page.previous || loading || mutating} onClick={() => setPageNumber((value) => Math.max(1, value - 1))}>上一页</button>
            <span>第 {pageNumber} 页</span><button className="btn btn-secondary" type="button" disabled={!page.next || loading || mutating} onClick={() => setPageNumber((value) => value + 1)}>下一页</button></div>}
        </section>
      </div>
      <div className="workspace-actions mt-6"><Link to="/" className="btn btn-secondary"><ArrowLeft size={16} />返回首页</Link></div>
  </>;
}

function CaseAnalysisPanel({
  task,
  candidates,
  stale,
  modelConfiguration,
  caseId,
  disease,
  loading,
  consent,
  reviewingCandidateId,
  onConsentChange,
  onAnalyze,
  onDecision,
}: {
  task: AnalysisTask | null;
  candidates: MedicalCaseCandidate[];
  stale: boolean;
  modelConfiguration: MedicalCaseAnalysis["modelConfiguration"];
  caseId: number;
  disease: string;
  loading: boolean;
  consent: boolean;
  reviewingCandidateId: number | null;
  onConsentChange: (value: boolean) => void;
  onAnalyze: () => void;
  onDecision: (candidate: MedicalCaseCandidate, decision: "accept" | "reject") => void;
}) {
  const result = caseResult(task);
  const pending = Boolean(task && ["queued", "running"].includes(task.status));
  const nodes = result.evidenceChain?.nodes ?? [];
  const nodeNames = new Map(nodes.map((node) => [node.id, node.label]));
  return <section className="panel case-analysis-panel" aria-label="证候与方剂分析">
    <div className="case-analysis-heading"><div><h4>证候与方剂候选分析</h4><p className="section-help">{taskStatusLabel(task)}{task?.id ? ` · 任务 #${task.id}` : ""}</p></div>
      {result.model && <span className="status-badge status-success">{result.model.name ?? "本地模型"} · {result.model.version ?? "版本未记录"}</span>}
    </div>
    {loading && !task ? <p className="section-help">正在读取分析记录…</p> : <>
      <label className="proteomics-consent case-analysis-consent">
        <input type="checkbox" checked={consent} onChange={(event) => onConsentChange(event.target.checked)} disabled={pending || loading} />
        <span><strong>我确认医案已脱敏，并同意发送至平台配置的本地/内网模型</strong><small>{modelConfiguration.configured ? `本次模型：${modelConfiguration.name} · ${modelConfiguration.version}。` : "尚未配置可用的本地/内网模型。"}仅提交症状正文、舌脉和现有诊断；医案标题、患者信息栏、来源和研究备注不会发送。模型候选仅供科研整理，不能作为临床诊断。</small></span>
      </label>
      <div className="source-record-actions"><button className="btn btn-primary" type="button" onClick={onAnalyze} disabled={!consent || !modelConfiguration.configured || pending || loading}><Sparkles size={15} />{loading ? "正在提交…" : pending ? "后台分析中…" : task ? "重新分析" : "开始分析"}</button></div>
      {task?.status === "failed" && <div className="notice-error" role="alert">{task.error_summary || "医案分析失败。"}</div>}
      {stale && <div className="notice-warning" role="alert">医案的分析字段已改变，当前结果保留作历史追溯但不能确认候选；请重新分析。</div>}
      {result.warnings?.map((warning) => <p className="notice-warning" key={warning}>{warning}</p>)}
      {task?.status === "succeeded" && result.observations && <div className="case-analysis-section"><h5>原文观察</h5>
        {result.observations.length ? <ul className="proteomics-pathways">{result.observations.map((observation, index) => <li key={`${observation.type}-${index}`}><strong>{observationLabels[observation.type] ?? observation.type}：{observation.value}</strong>{observation.evidence.map((evidence, evidenceIndex) => <span key={`${evidence.field}-${evidenceIndex}`}>{evidenceFieldLabels[evidence.field] ?? evidence.field}：“{evidence.quote}”</span>)}</li>)}</ul> : <p className="section-help">未找到可由原文核验的结构化观察。</p>}
      </div>}
      {task?.status === "succeeded" && <div className="case-analysis-section"><h5>证候 / 方剂候选 · 请逐条确认</h5>
        {candidates.length ? <div className="case-candidate-list">{candidates.map((candidate) => <article className="case-candidate" key={candidate.id}>
          <div className="case-analysis-heading"><div><strong>{candidate.candidate_type === "syndrome" ? "证候" : "方剂"}：{candidate.label}</strong><p className="section-help">{candidateMatchLabels[candidate.match_status]}{candidate.entity_label ? ` · ${candidate.entity_label}` : ""}</p></div><span className={`status-badge ${candidate.review_status === "accepted" ? "status-success" : candidate.review_status === "pending" ? "status-warning" : ""}`}>{candidateReviewLabels[candidate.review_status]}</span></div>
          <p className="section-help">模型自评置信度 {Math.round(Number(candidate.confidence) * 100)}%（未经校准，不代表真实概率） · 排序 {candidate.rank}</p>
          <ul className="proteomics-pathways">{candidate.evidence.map((evidence, index) => <li key={`${evidence.field}-${index}`}><strong>{evidenceFieldLabels[evidence.field] ?? evidence.field}</strong><span>“{evidence.quote}”</span></li>)}</ul>
          {candidate.knowledge_evidence.length > 0 && <div className="case-candidate-knowledge"><strong>已核验的本地知识库引用</strong><ul className="proteomics-pathways">{candidate.knowledge_evidence.map((reference) => <li key={reference.refId}><strong>{reference.kind === "entity" ? `${reference.label} · ${reference.stableId}` : `${reference.subject} → ${reference.object} · ${reference.predicate}`}</strong><span>{reference.sourceName} {reference.sourceVersion}{reference.sourceRecordId ? ` / ${reference.sourceRecordId}` : ""}{reference.evidenceType ? ` · ${reference.evidenceType}` : ""}{reference.evidenceText ? ` · ${reference.evidenceText}` : ""}</span></li>)}</ul></div>}
          <div className="source-record-actions"><button className="btn btn-primary" type="button" disabled={stale || !candidate.entity_id || reviewingCandidateId === candidate.id} onClick={() => onDecision(candidate, "accept")}>{reviewingCandidateId === candidate.id ? "正在记录…" : candidate.review_status === "accepted" ? "再次确认" : "确认候选"}</button><button className="btn btn-secondary" type="button" disabled={reviewingCandidateId === candidate.id} onClick={() => onDecision(candidate, "reject")}>{candidate.review_status === "rejected" ? "再次驳回" : "驳回候选"}</button>
            {candidate.review_status === "accepted" && !stale && candidate.candidate_type === "formula" && candidate.entity_id && <Link className="btn btn-secondary" to="/network-pharmacology" state={{ herb: candidate.entity_label ?? candidate.label, disease, sourceCaseId: caseId, sourceCandidateId: candidate.id }}>用已确认方剂开展网络药理分析</Link>}
          </div>
        </article>)}</div> : <p className="section-help">模型未返回有逐字原文证据的证候或方剂候选。系统不会自动补选其他实体。</p>}
      </div>}
      {task?.status === "succeeded" && <div className="case-analysis-section"><h5>本地知识库检索上下文</h5>
        {result.retrievalContext && (result.retrievalContext.entities.length > 0 || result.retrievalContext.relations.length > 0) ? <>
          <p className="section-help">按医案中出现的规范实体检索，并保留各条来源记录及版本；不同来源的关联并列展示，不自动合并或裁决。候选只会显示模型引用且由系统核验过的记录。</p>
          <ul className="proteomics-pathways">{result.retrievalContext.entities.map((entity) => <li key={entity.refId}><strong>{entity.label} · {entity.stableId}</strong><span>{entity.sourceName} {entity.sourceVersion}</span></li>)}{result.retrievalContext.relations.map((relation) => <li key={relation.refId}><strong>{relation.subject} → {relation.object} · {relation.predicate}</strong><span>{relation.sourceName} {relation.sourceVersion} / {relation.sourceRecordId}{relation.evidenceType ? ` · ${relation.evidenceType}` : ""}{relation.evidenceText ? ` · ${relation.evidenceText}` : ""}</span></li>)}</ul>
          {result.retrievalContext.truncated && <p className="section-help">本地检索上下文达到显示上限，未全部提交给模型。</p>}
        </> : <p className="section-help">本地知识库中没有匹配到带启用来源版本的记录；此次候选只依据医案原文生成。</p>}
      </div>}
      {task?.status === "succeeded" && <div className="case-analysis-section"><h5>已确认的知识库证据链</h5>
        {result.evidenceChain?.links.length ? <><ul className="proteomics-pathways">{result.evidenceChain.links.map((link) => <li key={link.id}><strong>{nodeNames.get(link.source) ?? `实体 #${link.source}`} → {nodeNames.get(link.target) ?? `实体 #${link.target}`} · {link.relationType}</strong><span>{link.sourceName} {link.sourceVersion} / {link.sourceRecordId} · {link.evidenceType}{link.evidenceText ? ` · ${link.evidenceText}` : ""}</span></li>)}</ul>
          {result.evidenceChain.truncated && <p className="section-help">证据关系较多，页面按系统上限截取；完整结果需缩小关联范围。</p>}
          <p className="section-help">来源版本：{result.evidenceChain.sources.map((source) => `${source.source} ${source.version}`).join("；") || "未记录"}</p>
        </> : <p className="section-help">当前已确认候选还没有在本地知识目录中找到后续有来源版本支持的关系。</p>}
      </div>}
    </>}
  </section>;
}
