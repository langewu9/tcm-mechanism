import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useOutletContext } from "react-router-dom";
import { ArrowLeft, BookOpen, FileHeart, LogOut, Plus, Trash2 } from "lucide-react";
import { approveMedicalCase, createMedicalCase, deleteMedicalCase, getMedicalCaseAudit, getMedicalCases, type CaseAuditEvent, type MedicalCase, type Page } from "../api/cases";
import { logout, type Session } from "../api/auth";
import { ApiError } from "../api/client";

function valueOf(data: Record<string, unknown>, key: string) {
  const value = data[key];
  return typeof value === "string" && value.trim() ? value : "未填写";
}

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "请求未完成，请稍后重试。";
}

export function CasesPage() {
  const user = useOutletContext<NonNullable<Session["user"]>>();
  const navigate = useNavigate();
  const [page, setPage] = useState<Page<MedicalCase> | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [auditCaseId, setAuditCaseId] = useState<number | null>(null);
  const [auditEvents, setAuditEvents] = useState<CaseAuditEvent[]>([]);
  const [reviewingId, setReviewingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadCases = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPage(await getMedicalCases(pageNumber));
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setLoading(false);
    }
  }, [pageNumber]);

  useEffect(() => { void loadCases(); }, [loadCases, refresh]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
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
      formElement.reset();
      setNotice("医案已保存，来源和提交账号已记录。");
      if (pageNumber !== 1) setPageNumber(1);
      else setRefresh((value) => value + 1);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setSaving(false);
    }
  }

  async function removeCase(item: MedicalCase) {
    if (!window.confirm(`确定删除“${item.title}”吗？`)) return;
    setDeletingId(item.id);
    setError(null);
    setNotice(null);
    try {
      await deleteMedicalCase(item.id);
      setNotice("医案已删除。");
      if (pageNumber > 1 && page?.results.length === 1) setPageNumber((value) => value - 1);
      else setRefresh((value) => value + 1);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setDeletingId(null);
    }
  }

  async function toggleAudit(item: MedicalCase) {
    if (auditCaseId === item.id) {
      setAuditCaseId(null);
      setAuditEvents([]);
      return;
    }
    setAuditCaseId(item.id);
    setError(null);
    try {
      const response = await getMedicalCaseAudit(item.id);
      setAuditEvents(response.results);
    } catch (cause) {
      setAuditCaseId(null);
      setError(errorMessage(cause));
    }
  }

  async function approveCase(item: MedicalCase) {
    if (!window.confirm(`确认审核通过“${item.title}”？这会记录审核账号和时间。`)) return;
    setReviewingId(item.id);
    setError(null);
    setNotice(null);
    try {
      await approveMedicalCase(item.id);
      setNotice("医案已审核，审核账号和时间已写入审计记录。");
      setRefresh((value) => value + 1);
      if (auditCaseId === item.id) setAuditEvents((await getMedicalCaseAudit(item.id)).results);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setReviewingId(null);
    }
  }

  async function signOut() {
    setError(null);
    try {
      await logout();
      navigate("/login", { replace: true });
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
      <nav className="workspace-module-nav" aria-label="研究模块"><Link to="/cases" aria-current="page">医案管理</Link><Link to="/datasets">研究数据集</Link><Link to="/proteomics">蛋白组学</Link><Link to="/network-pharmacology">网络药理</Link>{user.isSuperuser && <Link to="/admin/sources">数据源同步</Link>}</nav>
      <div className="workspace-nav-actions"><span className="workspace-user">{user.username}{user.isSuperuser ? " · 平台管理员" : " · 研究者"}</span>
        <button className="btn btn-secondary" type="button" onClick={signOut}><LogOut size={16} />退出</button>
      </div>
    </header>

    <div className="app-main workspace-main"><div className="app-main-inner">
      <div className="page-heading"><div className="page-heading-copy"><p className="page-kicker">Medical cases</p><h1 className="page-title">结构化医案库</h1>
        <p className="page-description">记录去标识化后的症状、舌脉、诊断与资料来源。每条记录都关联当前账号，普通研究者只能查看自己的医案。</p></div>
        <Link to="/" className="btn btn-secondary"><ArrowLeft size={16} />返回首页</Link>
      </div>

      {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
      {notice && <div className="notice-success workspace-notice" role="status">{notice}</div>}

      <div className="case-workspace-grid">
        <form className="panel case-form" onSubmit={submit} aria-label="新增医案">
          <div className="panel-header"><div><h2 className="section-title-sm">新增医案</h2><p className="section-help">来源和提交账号将随记录保存，便于后续核查。</p></div><span className="page-heading-icon"><Plus size={19} /></span></div>
          <div className="case-form-fields">
            <label className="form-label" htmlFor="case-title">医案标题<input className="field" id="case-title" name="title" maxLength={200} placeholder="例如：麦门冬汤干预肺纤维化研究医案" required /></label>
            <label className="form-label" htmlFor="case-patient">脱敏患者信息<input className="field" id="case-patient" name="patient_info" placeholder="例如：年龄段、性别；请勿填写姓名、电话、证件号" /></label>
            <label className="form-label" htmlFor="case-symptoms">症状与主诉<textarea className="field case-textarea" id="case-symptoms" name="symptoms" placeholder="记录去标识化后的症状、现病史与伴随表现" required /></label>
            <label className="form-label" htmlFor="case-tongue-pulse">舌象与脉象<input className="field" id="case-tongue-pulse" name="tongue_pulse" placeholder="舌质、舌苔、脉象" /></label>
            <label className="form-label" htmlFor="case-diagnosis">诊断或证候<input className="field" id="case-diagnosis" name="diagnosis" placeholder="中医证候或西医诊断" /></label>
            <label className="form-label" htmlFor="case-source">资料来源<input className="field" id="case-source" name="source_reference" maxLength={500} placeholder="文献题名、病例集编号或其他可核查出处" /></label>
            <label className="form-label" htmlFor="case-notes">研究备注<textarea className="field case-textarea case-textarea-short" id="case-notes" name="research_notes" placeholder="补充研究背景、数据处理说明等" /></label>
          </div>
          <div className="case-form-footer"><p>请仅提交已去标识化的研究资料。</p><button className="btn btn-primary" type="submit" disabled={saving}><BookOpen size={16} />{saving ? "正在保存…" : "保存医案"}</button></div>
        </form>

        <section className="case-list" aria-labelledby="case-list-heading">
          <div className="case-list-heading"><div><p className="page-kicker">Research records</p><h2 id="case-list-heading" className="section-title-sm">已保存医案</h2></div>
            <span className="status-badge status-success">{page?.count ?? 0} 条记录</span></div>
          {loading ? <div className="panel empty-state" role="status">正在读取医案…</div>
            : page?.results.length ? <div className="case-list-items">{page.results.map((item) => <article key={item.id} className="case-record panel">
              <div className="case-record-top"><div><h3>{item.title}</h3><time dateTime={item.updated_at}>更新于 {new Date(item.updated_at).toLocaleString("zh-CN")}</time></div>
                <button className="icon-button case-delete" type="button" onClick={() => void removeCase(item)} disabled={deletingId === item.id} aria-label={`删除医案：${item.title}`} title="删除医案"><Trash2 size={17} /></button></div>
              <p><span className={`status-badge ${item.review_status === "reviewed" ? "status-success" : "status-warning"}`}>{item.review_status === "reviewed" ? `已审核 · ${item.reviewed_by_username ?? "平台管理员"}` : "待审核"}</span></p>
              <p className="case-summary">{item.deidentified_text}</p>
              <div className="case-record-meta"><p><span>脱敏信息</span>{valueOf(item.structured_data, "patient_info")}</p><p><span>舌象与脉象</span>{valueOf(item.structured_data, "tongue_pulse")}</p>
                <p><span>诊断或证候</span>{valueOf(item.structured_data, "diagnosis")}</p><p><span>资料来源</span>{item.source_reference || "未填写"}</p>
                <p><span>提交研究者</span>{item.owner_username}</p></div>
              {item.research_notes && <details className="case-notes"><summary>研究备注</summary><p>{item.research_notes}</p></details>}
              <div className="source-record-actions">
                <button className="btn btn-secondary" type="button" onClick={() => void toggleAudit(item)}>{auditCaseId === item.id ? "收起审计记录" : "查看审计记录"}</button>
                {user.isSuperuser && item.review_status !== "reviewed" && <button className="btn btn-primary" type="button" onClick={() => void approveCase(item)} disabled={reviewingId === item.id}>{reviewingId === item.id ? "正在审核…" : "审核通过"}</button>}
              </div>
              {auditCaseId === item.id && <div className="panel case-audit-history"><h4>操作记录</h4>{auditEvents.length ? <ul className="proteomics-pathways">{auditEvents.map((event) => <li key={event.id}><strong>{event.actor_username ?? "账号已删除"} · {event.action === "created" ? "创建" : event.action === "updated" ? "修改" : event.action === "reviewed" ? "审核" : "删除"}</strong><span>{new Date(event.created_at).toLocaleString("zh-CN")} · {event.changed_fields.join("、") || "无字段变化"}</span></li>)}</ul> : <p className="section-help">尚无操作记录。</p>}</div>}
            </article>)}</div>
            : <div className="panel empty-state"><FileHeart size={27} /><strong>暂无医案</strong><p>可以在左侧录入第一条去标识化医案，并填写可核查的数据来源。</p></div>}
          {page && page.count > 0 && <div className="case-pagination"><button className="btn btn-secondary" type="button" disabled={!page.previous || loading} onClick={() => setPageNumber((value) => Math.max(1, value - 1))}>上一页</button>
            <span>第 {pageNumber} 页</span><button className="btn btn-secondary" type="button" disabled={!page.next || loading} onClick={() => setPageNumber((value) => value + 1)}>下一页</button></div>}
        </section>
      </div>
    </div></div>
  </main>;
}
