import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, Navigate, useOutletContext } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Database, RefreshCw } from "lucide-react";
import { logout, type Session } from "../api/auth";
import {
  getAdminDataSources,
  getSyncRuns,
  previewDataSourceSync,
  applySyncPreview,
  createSQLiteDataSource,
  testSQLiteDataSource,
  type AdminDataSource,
  type SyncRun,
} from "../api/sources";
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

const emptySQLiteSource = {
  name: "",
  description: "",
  databaseFile: "data_cache.db",
  table: "herb_component_target",
  herbColumn: "herb",
  compoundColumn: "component",
  targetColumn: "target",
};

export function SourcesPage() {
  const user = useOutletContext<NonNullable<Session["user"]>>();
  const [sources, setSources] = useState<AdminDataSource[]>([]);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [sqliteForm, setSQLiteForm] = useState(emptySQLiteSource);
  const [testingSourceId, setTestingSourceId] = useState<number | null>(null);
  const [testResults, setTestResults] = useState<Record<number, { rowCount: number; checksum: string }>>({});

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
      setNotice(`数据源预览任务 #${response.run.id} 已进入后台队列。`);
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
      setNotice(`数据源应用任务 #${response.run.id} 已进入后台队列。应用前会重新读取来源并核对 SHA-256。`);
      await refresh();
    } catch (cause) {
      setError(errorMessage(cause));
      void refresh().catch((refreshError: unknown) => setError(errorMessage(refreshError)));
    }
    finally { setBusy(null); }
  }

  async function addSQLiteSource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(-1);
    setError(null);
    setNotice(null);
    try {
      const source = await createSQLiteDataSource(sqliteForm);
      setSQLiteForm(emptySQLiteSource);
      setNotice(`SQLite 来源“${source.name}”已登记。请先测试连接，再预览导入差异。`);
      await refresh();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally { setBusy(null); }
  }

  async function testSource(source: AdminDataSource) {
    setTestingSourceId(source.id);
    setError(null);
    setNotice(null);
    try {
      const result = await testSQLiteDataSource(source.id);
      setTestResults((current) => ({ ...current, [source.id]: { rowCount: result.rowCount, checksum: result.checksumSha256 } }));
      setNotice(`连接成功：${result.rowCount.toLocaleString()} 行；SHA-256 ${result.checksumSha256.slice(0, 12)}…`);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setTestingSourceId(null); }
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
              {source.connector_type === "reactome-catalog" || source.slug === "reactome" ? <>
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
              </> : source.connector_type === "sqlite-herb-compound-target" ? <>
                <p className="source-last-success">最近一次成功导入：{dateTime(source.last_success_at)}</p>
                <p className="section-help">服务器只读打开受控目录中的 SQLite 文件。浏览器不会提交绝对路径；同步前请确认文件许可和列映射。</p>
                <div className="source-record-actions">
                  <button className="btn btn-secondary" type="button" disabled={!source.enabled || testingSourceId === source.id}
                    onClick={() => void testSource(source)}>
                    {testingSourceId === source.id ? <RefreshCw size={15} className="spin" /> : <CheckCircle2 size={15} />}
                    {testingSourceId === source.id ? "正在测试…" : "测试连接"}
                  </button>
                  <button className="btn btn-primary" type="button" disabled={!source.enabled || busy === source.id}
                    onClick={() => void startPreview(source)}>
                    {busy === source.id ? <RefreshCw size={15} className="spin" /> : <Database size={15} />}
                    {busy === source.id ? "正在预览…" : "预览导入差异"}
                  </button>
                </div>
                {testResults[source.id] && <p className="source-release-line">最近测试 {testResults[source.id].rowCount.toLocaleString()} 行 · SHA-256 {testResults[source.id].checksum.slice(0, 16)}…</p>}
              </> : <p className="section-help">此来源连接器将在后续计划阶段接入。</p>}
            </article>)}
          </div> : <div className="panel empty-state">没有已登记的数据源。</div>}

          <form className="panel source-create-form" onSubmit={(event) => void addSQLiteSource(event)}>
            <div className="panel-header"><div><h2 className="section-title-sm">登记旧版 SQLite 数据库</h2>
              <p className="section-help">将数据库文件放在服务器的 <code>SQLITE_SOURCE_ROOT</code> 目录内，再填写相对文件名。</p></div></div>
            <div className="source-create-grid">
              <label className="form-label">数据源名称<input className="field" required maxLength={160} value={sqliteForm.name} onChange={(event) => setSQLiteForm((form) => ({ ...form, name: event.target.value }))} placeholder="中药-成分-靶点数据库" /></label>
              <label className="form-label">相对文件名<input className="field" required value={sqliteForm.databaseFile} onChange={(event) => setSQLiteForm((form) => ({ ...form, databaseFile: event.target.value }))} placeholder="data_cache.db" /></label>
              <label className="form-label">数据表<input className="field" required value={sqliteForm.table} onChange={(event) => setSQLiteForm((form) => ({ ...form, table: event.target.value }))} /></label>
              <label className="form-label">中药列<input className="field" required value={sqliteForm.herbColumn} onChange={(event) => setSQLiteForm((form) => ({ ...form, herbColumn: event.target.value }))} /></label>
              <label className="form-label">成分列<input className="field" required value={sqliteForm.compoundColumn} onChange={(event) => setSQLiteForm((form) => ({ ...form, compoundColumn: event.target.value }))} /></label>
              <label className="form-label">靶点列<input className="field" required value={sqliteForm.targetColumn} onChange={(event) => setSQLiteForm((form) => ({ ...form, targetColumn: event.target.value }))} /></label>
            </div>
            <div className="case-form-footer"><p>只允许受控目录的相对路径；导入前会核对校验值并保留来源记录。</p>
              <button className="btn btn-primary" type="submit" disabled={busy === -1 || !sqliteForm.name.trim()}>
                {busy === -1 ? <RefreshCw size={15} className="spin" /> : <Database size={15} />}
                {busy === -1 ? "正在登记…" : "登记 SQLite 来源"}
              </button></div>
          </form>
        </div>

        <div className="case-list">
          <div className="case-list-heading"><div><p className="page-kicker">Auditable operations</p><h2 className="section-title-sm">同步历史</h2></div>
            {hasActiveRuns && <span className="status-badge status-warning">自动刷新中</span>}
          </div>
          {runs.length ? <div className="case-list-items">
            {runs.map((run) => {
              const summary = run.preview_summary;
              const isSQLite = summary.connector === "sqlite-herb-compound-target";
              const syncLabel = isSQLite ? "SQLite 关系数据" : "Reactome 通路目录";
              const canApply = summary.mode === "preview" && run.status === "succeeded" && !activeApplyBases.has(run.id);
              return <article className="panel source-run-record" key={run.id}>
                <div className="case-record-top"><div><h3>{run.source_name} · {summary.mode === "apply" ? "应用数据" : "预览数据"} #{run.id}</h3>
                  <time>{dateTime(run.created_at)} · 操作者：{run.requested_by_username ?? "未知"}</time></div>
                  <span className={`status-badge ${run.status === "succeeded" ? "status-success" : run.status === "failed" ? "status-error" : "status-warning"}`}>{runStatus(run.status)}</span></div>
                {run.status === "failed" && <div className="notice-error source-run-error" role="alert">{run.error_summary}</div>}
                {summary.mode === "preview" && run.status === "succeeded" && <>
                  <div className={`proteomics-metrics source-sync-metrics ${isSQLite ? "source-sync-metrics-sqlite" : ""}`}>
                    {isSQLite ? <>
                      <Metric label="输入行数" value={summary.totalRows ?? run.records_seen} />
                      <Metric label="中药实体" value={summary.uniqueHerbs ?? 0} />
                      <Metric label="成分实体" value={summary.uniqueCompounds ?? 0} />
                      <Metric label="靶点实体" value={summary.uniqueTargets ?? 0} />
                      <Metric label="关系记录" value={summary.relationships ?? 0} />
                      <Metric label="将新增实体" value={summary.wouldCreate ?? 0} />
                      <Metric label="将更新实体" value={summary.wouldUpdate ?? 0} />
                      <Metric label="将停用旧实体" value={summary.wouldRetire ?? 0} />
                    </> : <>
                      <Metric label="通路总数" value={summary.totalRecords ?? run.records_seen} />
                      <Metric label="新增" value={summary.wouldCreate ?? 0} />
                      <Metric label="更新" value={summary.wouldUpdate ?? 0} />
                      <Metric label="停用" value={summary.wouldRetire ?? 0} />
                    </>}
                  </div>
                  <p className="source-release-line">{isSQLite ? `${summary.databaseFile ?? "SQLite 文件"} · ${summary.table ?? "数据表"} · ` : `Reactome v${summary.sourceVersion ?? "未知"} · `}来源版本 {summary.releaseVersion ?? run.release_version ?? "—"}</p>
                  <code className="source-checksum">SHA-256：{summary.checksumSha256 ?? run.release_checksum ?? "—"}</code>
                  <p className="section-help">{syncLabel}预览只保存来源版本与变更统计，不会修改知识目录。应用时会重新读取来源并核对校验值。</p>
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
