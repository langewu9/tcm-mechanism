import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, Navigate, useOutletContext } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Database, RefreshCw } from "lucide-react";
import { logout, type Session } from "../api/auth";
import { getAdminDataSources, getSyncRuns, previewDataSourceSync, applySyncPreview, type AdminDataSource, type SyncRun } from "../api/sources";
import { ApiError } from "../api/client";

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "请求未完成，请稍后重试。";
}

function runStatus(status: SyncRun["status"]) {
  return ({ pending: "排队中", running: "同步中", succeeded: "已完成", failed: "失败" })[status];
}

function dateTime(value: string | null) {
  return value ? new Date(value).toLocaleString("zh-CN") : "尚无记录";
}

export function SourcesPage() {
  const user = useOutletContext<NonNullable<Session["user"]>>();
  const [sources, setSources] = useState<AdminDataSource[]>([]);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [sourcePage, runPage] = await Promise.all([getAdminDataSources(), getSyncRuns()]);
    setSources(sourcePage.results);
    setRuns(runPage.results);
  }, []);

  useEffect(() => {
    let active = true;
    Promise.all([getAdminDataSources(), getSyncRuns()])
      .then(([sourcePage, runPage]) => {
        if (!active) return;
        setSources(sourcePage.results);
        setRuns(runPage.results);
      })
      .catch((cause: unknown) => { if (active) setError(errorMessage(cause)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const hasActiveRuns = runs.some((run) => run.status === "pending" || run.status === "running");
  useEffect(() => {
    if (!hasActiveRuns) return;
    const timer = window.setInterval(() => { void refresh().catch((cause: unknown) => setError(errorMessage(cause))); }, 1600);
    return () => window.clearInterval(timer);
  }, [hasActiveRuns, refresh]);

  const activeApplyBases = useMemo(() => new Set(runs
    .filter((run) => run.preview_summary.mode === "apply" && run.status !== "failed")
    .map((run) => run.preview_summary.basedOn)), [runs]);

  if (!user.isSuperuser) return <Navigate to="/cases" replace />;

  async function signOut() {
    try { await logout(); window.location.assign("/login"); }
    catch (cause) { setError(errorMessage(cause)); }
  }

  async function startPreview(source: AdminDataSource) {
    setBusy(source.id);
    setError(null);
    setNotice(null);
    try {
      const response = await previewDataSourceSync(source.id);
      setNotice(`Reactome 目录预览任务 #${response.run.id} 已进入后台队列。`);
      await refresh();
    } catch (cause) {
      setError(errorMessage(cause));
      void refresh().catch((refreshError: unknown) => setError(errorMessage(refreshError)));
    }
    finally { setBusy(null); }
  }

  async function applyPreview(run: SyncRun) {
    setBusy(run.source);
    setError(null);
    setNotice(null);
    try {
      const response = await applySyncPreview(run.id);
      setNotice(`目录应用任务 #${response.run.id} 已进入后台队列。应用前会重新下载并核对文件校验值。`);
      await refresh();
    } catch (cause) {
      setError(errorMessage(cause));
      void refresh().catch((refreshError: unknown) => setError(errorMessage(refreshError)));
    }
    finally { setBusy(null); }
  }

  return <main className="workspace-page">
    <header className="workspace-nav">
      <Link to="/" className="site-brand" aria-label="远志 AI Scientist 首页">
        <img src="/images/yuanzhi-mark.png" alt="" width={42} height={42} className="brand-mark" />
        <span><strong>远志 AI Scientist</strong><small>平台管理</small></span>
      </Link>
      <nav className="workspace-module-nav" aria-label="研究模块">
        <Link to="/cases">医案管理</Link><Link to="/datasets">研究数据集</Link><Link to="/proteomics">蛋白组学</Link><Link to="/admin/sources" aria-current="page">数据源同步</Link>
      </nav>
      <div className="workspace-nav-actions"><span className="workspace-user">{user.username} · 平台管理员</span>
        <button className="btn btn-secondary" type="button" onClick={() => void signOut()}>退出</button></div>
    </header>

    <div className="app-main workspace-main"><div className="app-main-inner">
      <div className="page-heading"><div className="page-heading-copy"><p className="page-kicker">Source catalogue</p><h1 className="page-title">数据源同步</h1>
        <p className="page-description">先试运行并检查差异，确认后再应用到本地知识目录。每次操作都会记录管理员、Reactome 版本和文件校验值。</p></div>
        <Link to="/proteomics" className="btn btn-secondary"><ArrowLeft size={16} />返回研究工作区</Link>
      </div>

      {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
      {notice && <div className="notice-success workspace-notice" role="status">{notice}</div>}

      <section className="source-sync-layout" aria-labelledby="source-list-heading">
        <div className="case-list">
          <div className="case-list-heading"><div><p className="page-kicker">Connected providers</p><h2 id="source-list-heading" className="section-title-sm">已登记的数据源</h2></div></div>
          {loading ? <div className="panel empty-state" role="status">正在读取数据源…</div> : sources.length ? <div className="case-list-items">
            {sources.map((source) => <article className="panel source-record" key={source.id}>
              <div className="case-record-top"><div><h3>{source.name}</h3><time>{source.slug} · {source.access_mode === "download" ? "版本文件" : source.access_mode}</time></div>
                <span className={`status-badge ${source.enabled ? "status-success" : "status-warning"}`}>{source.enabled ? "已启用" : "已停用"}</span></div>
              <p className="dataset-description">{source.description}</p>
              {source.slug === "reactome" ? <>
                <p className="source-last-success">最近一次成功应用：{dateTime(source.last_success_at)}</p>
                <div className="source-record-actions">
                  <button className="btn btn-primary" type="button" disabled={!source.enabled || busy === source.id}
                    onClick={() => void startPreview(source)}>
                    {busy === source.id ? <RefreshCw size={15} className="spin" /> : <Database size={15} />}
                    {busy === source.id ? "正在提交…" : "检查目录变更"}
                  </button>
                  {source.documentation_url && <a className="btn btn-secondary" href={source.documentation_url} target="_blank" rel="noreferrer">接口与来源说明</a>}
                </div>
                <p className="section-help">{source.license_note}</p>
              </> : <p className="section-help">此来源连接器将在后续计划阶段接入。</p>}
            </article>)}
          </div> : <div className="panel empty-state">没有已登记的数据源。</div>}
        </div>

        <div className="case-list">
          <div className="case-list-heading"><div><p className="page-kicker">Auditable operations</p><h2 className="section-title-sm">同步历史</h2></div>
            {hasActiveRuns && <span className="status-badge status-warning">自动刷新中</span>}
          </div>
          {runs.length ? <div className="case-list-items">
            {runs.map((run) => {
              const summary = run.preview_summary;
              const canApply = summary.mode === "preview" && run.status === "succeeded" && !activeApplyBases.has(run.id);
              return <article className="panel source-run-record" key={run.id}>
                <div className="case-record-top"><div><h3>{run.source_name} · {summary.mode === "apply" ? "应用目录" : "预览目录"} #{run.id}</h3>
                  <time>{dateTime(run.created_at)} · 操作者：{run.requested_by_username ?? "未知"}</time></div>
                  <span className={`status-badge ${run.status === "succeeded" ? "status-success" : run.status === "failed" ? "status-error" : "status-warning"}`}>{runStatus(run.status)}</span></div>
                {run.status === "failed" && <div className="notice-error source-run-error" role="alert">{run.error_summary}</div>}
                {summary.mode === "preview" && run.status === "succeeded" && <>
                  <div className="proteomics-metrics source-sync-metrics">
                    <Metric label="通路总数" value={summary.totalRecords ?? run.records_seen} />
                    <Metric label="新增" value={summary.wouldCreate ?? 0} />
                    <Metric label="更新" value={summary.wouldUpdate ?? 0} />
                    <Metric label="停用" value={summary.wouldRetire ?? 0} />
                  </div>
                  <p className="source-release-line">Reactome 版本 {summary.sourceVersion ?? "未知"} · 发布记录 {summary.releaseVersion ?? run.release_version ?? "—"}</p>
                  <code className="source-checksum">SHA-256：{summary.checksumSha256 ?? run.release_checksum ?? "—"}</code>
                  <p className="section-help">预览只会保存版本与变更统计，不会修改知识目录。应用时将再次下载并核对校验值。</p>
                  {canApply && <button className="btn btn-primary source-apply-button" type="button" disabled={busy === run.source}
                    onClick={() => void applyPreview(run)}><CheckCircle2 size={15} />应用此预览</button>}
                  {!canApply && activeApplyBases.has(run.id) && <p className="section-help">此预览已有待处理或成功的应用记录。</p>}
                </>}
                {summary.mode === "apply" && run.status === "succeeded" && <p className="source-release-line">本次导入 {run.records_seen} 项，新增 {run.records_created} 项，更新 {run.records_updated} 项，停用 {run.records_retired} 项。</p>}
                {(run.status === "pending" || run.status === "running") && <p className="source-release-line">任务正在后台执行；页面会自动刷新状态。</p>}
              </article>;
            })}
          </div> : <div className="panel empty-state"><Database size={26} /><strong>暂无同步记录</strong><p>点击“检查目录变更”创建一次只读预览。</p></div>}
        </div>
      </section>
    </div></div>
  </main>;
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div className="proteomics-metric"><span>{label}</span><strong>{value.toLocaleString("zh-CN")}</strong></div>;
}
