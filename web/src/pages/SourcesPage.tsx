import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, Navigate, useOutletContext } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Database, RefreshCw, Trash2 } from "lucide-react";
import { type Session } from "../api/auth";
import {
  getAdminDataSources,
  getSyncRuns,
  previewDataSourceSync,
  applySyncPreview,
  createSQLiteDataSource,
  testSQLiteDataSource,
  deleteDataSource,
  type AdminDataSource,
  type SyncRun,
} from "../api/sources";
import { ApiError } from "../api/client";
import { SourceSettingsForm } from "../components/SourceSettingsForm";

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
  targetCellMode: "list" as "single" | "list",
  diseaseTargetTable: "disease_target",
  diseaseColumn: "disease",
  diseaseTargetColumn: "target",
  diseaseSourceColumn: "source_file",
  diseaseHerbTargetTable: "disease_herb_target",
  diseaseHerbColumn: "disease",
  diseaseHerbHerbColumn: "herb",
  diseaseHerbTargetColumn: "target",
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
  const [deletingSourceId, setDeletingSourceId] = useState<number | null>(null);
  const [testResults, setTestResults] = useState<Record<number, { rowCount: number; checksum: string; tableRowCounts: Record<string, number> }>>({});
  const mounted = useRef(false);
  const readVersion = useRef(0);

  const refresh = useCallback(async () => {
    const version = ++readVersion.current;
    try {
      const [sourcePage, runPage] = await Promise.all([getAdminDataSources(), getSyncRuns()]);
      if (!mounted.current || version !== readVersion.current) return;
      setSources(sourcePage.results);
      setRuns(runPage.results);
    } catch (cause) {
      if (mounted.current && version === readVersion.current) throw cause;
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refresh()
      .catch((cause: unknown) => { if (mounted.current) setError(errorMessage(cause)); })
      .finally(() => { if (mounted.current) setLoading(false); });
    return () => { mounted.current = false; readVersion.current++; };
  }, [refresh]);

  const hasActiveRuns = runs.some((run) => run.status === "pending" || run.status === "running");
  useEffect(() => {
    if (!hasActiveRuns) return;
    const timer = window.setInterval(() => { void refresh().catch((cause: unknown) => setError(errorMessage(cause))); }, 1600);
    return () => window.clearInterval(timer);
  }, [hasActiveRuns, refresh]);

  const activeApplyBases = useMemo(() => new Set(runs
    .filter((run) => run.preview_summary.mode === "apply" && run.status !== "failed")
    .map((run) => run.preview_summary.basedOn)), [runs]);
  const activeSourceIds = useMemo(() => new Set(runs
    .filter((run) => run.status === "pending" || run.status === "running")
    .map((run) => run.source)), [runs]);

  if (!user.isSuperuser) return <Navigate to="/cases" replace />;

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
      setTestResults((current) => ({ ...current, [source.id]: { rowCount: result.rowCount, checksum: result.checksumSha256, tableRowCounts: result.tableRowCounts } }));
      setNotice(`连接成功：${result.rowCount.toLocaleString()} 行，已识别 ${Object.keys(result.tableRowCounts).length} 张数据表；SHA-256 ${result.checksumSha256.slice(0, 12)}…`);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setTestingSourceId(null); }
  }

  async function removeSource(source: AdminDataSource) {
    if (!window.confirm(`删除数据源“${source.name}”的登记？已有来源版本或同步历史的登记将保留，服务器原文件和知识记录不受影响。`)) return;
    setDeletingSourceId(source.id);
    setError(null);
    setNotice(null);
    try {
      await deleteDataSource(source.id);
      setNotice(`数据源“${source.name}”的登记已删除。`);
      setTestResults((current) => {
        const next = { ...current };
        delete next[source.id];
        return next;
      });
      await refresh();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setDeletingSourceId(null); }
  }

  return <>

      <div className="page-heading"><div className="page-heading-copy"><p className="page-kicker">Source catalogue</p><h1 className="page-title">数据源同步</h1>
        <p className="page-description">先试运行并检查差异，确认后再应用到本地知识目录。每次操作都会记录管理员、来源版本和文件校验值。</p></div>
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
                <div className="source-record-actions"><span className={`status-badge ${source.enabled ? "status-success" : "status-warning"}`}>{source.enabled ? "已启用" : "已停用"}</span>
                  <button className="btn btn-secondary" type="button" aria-label={`删除数据源：${source.name}`} title="删除未使用的数据源登记"
                    disabled={deletingSourceId !== null || busy !== null || testingSourceId !== null}
                    onClick={() => void removeSource(source)}>
                    {deletingSourceId === source.id ? <RefreshCw size={15} className="spin" /> : <Trash2 size={15} />}
                  </button></div></div>
              <p className="dataset-description">{source.description}</p>
              <SourceSettingsForm source={source} onSaved={(saved) => {
                readVersion.current++;
                setSources((current) => current.map((item) => item.id === saved.id ? { ...item, ...saved } : item));
              }} />
              {activeSourceIds.has(source.id) && <p className="section-help" role="status">此数据源已有同步任务，请等待完成后再提交。</p>}
              <p className="section-help">
                定时预览：{!source.enabled ? "数据源已停用" : !source.scheduled_previews_enabled ? "部署开关未开启" :
                  source.refresh_interval_hours && source.refresh_interval_hours > 0 ? `每 ${source.refresh_interval_hours} 小时检查` : "未设置刷新间隔"}
                {source.last_preview_requested_at ? ` · 最近调度：${dateTime(source.last_preview_requested_at)}` : ""}
                。预览不会自动入库，仍需管理员审核确认。
              </p>
              {source.connector_type === "reactome-catalog" || source.slug === "reactome" || source.connector_type === "uniprot-human-catalog" || source.connector_type === "pubchem-compound-catalog" || source.connector_type === "string-human-identifier-crosswalk" ? <>
                <p className="source-last-success">最近一次成功应用：{dateTime(source.last_success_at)}</p>
                {source.connector_type === "uniprot-human-catalog" && <p className="section-help">只同步人类 reviewed 蛋白条目。系统将先按基因符号尝试关联已有靶点；多重匹配会保留为歧义，应用前请检查预览。</p>}
                {source.connector_type === "pubchem-compound-catalog" && <p className="section-help">PubChem 只补充已登记成分的化学属性。请先在 Django 管理后台核对并配置 CID 到本地成分 stableId 的映射；系统不会按名称猜测或自动改绑。配置格式：<code>{'{"connector":"pubchem-compound-catalog","mappings":[{"stableId":"本地成分stable_id","cid":"5280343"}]}'}</code></p>}
                {source.connector_type === "string-human-identifier-crosswalk" && <p className="section-help">只为已明确标注为人类的本地基因/蛋白补充 STRING ID，不下载完整蛋白目录、不创建或合并实体。STRING 返回最佳匹配，重名、冲突和未匹配记录会在预览中单独统计；应用前请检查样例。</p>}
                <div className="source-record-actions">
                  <button className="btn btn-primary" type="button" disabled={!source.enabled || busy === source.id || deletingSourceId === source.id || activeSourceIds.has(source.id)}
                    onClick={() => void startPreview(source)}>
                    {busy === source.id ? <RefreshCw size={15} className="spin" /> : <Database size={15} />}
                    {busy === source.id ? "正在提交…" : source.connector_type === "uniprot-human-catalog" ? "预览 UniProt 目录" : source.connector_type === "pubchem-compound-catalog" ? "预览 PubChem 属性" : source.connector_type === "string-human-identifier-crosswalk" ? "预览 STRING 标识映射" : "检查目录变更"}
                  </button>
                  {source.connector_type === "pubchem-compound-catalog" && <a className="btn btn-secondary" href="/django-admin/core/datasource/">配置 CID 映射</a>}
                  {source.documentation_url && <a className="btn btn-secondary" href={source.documentation_url} target="_blank" rel="noreferrer">接口与来源说明</a>}
                </div>
                <p className="section-help">{source.license_note}</p>
              </> : source.connector_type === "sqlite-herb-compound-target" ? <>
                <p className="source-last-success">最近一次成功导入：{dateTime(source.last_success_at)}</p>
                <p className="section-help">服务器只读打开受控目录中的 SQLite 文件。浏览器不会提交绝对路径；同步前请确认文件许可和列映射。</p>
                <div className="source-record-actions">
                  <button className="btn btn-secondary" type="button" disabled={!source.enabled || testingSourceId === source.id || deletingSourceId === source.id}
                    onClick={() => void testSource(source)}>
                    {testingSourceId === source.id ? <RefreshCw size={15} className="spin" /> : <CheckCircle2 size={15} />}
                    {testingSourceId === source.id ? "正在测试…" : "测试连接"}
                  </button>
                  <button className="btn btn-primary" type="button" disabled={!source.enabled || busy === source.id || deletingSourceId === source.id || activeSourceIds.has(source.id)}
                    onClick={() => void startPreview(source)}>
                    {busy === source.id ? <RefreshCw size={15} className="spin" /> : <Database size={15} />}
                    {busy === source.id ? "正在预览…" : "预览导入差异"}
                  </button>
                </div>
                {testResults[source.id] && <><p className="source-release-line">最近测试 {testResults[source.id].rowCount.toLocaleString()} 行 · SHA-256 {testResults[source.id].checksum.slice(0, 16)}…</p><ul className="proteomics-pathways source-table-counts">{Object.entries(testResults[source.id].tableRowCounts).map(([table, count]) => <li key={table}><strong>{table}</strong><span>{count.toLocaleString()} 行</span></li>)}</ul></>}
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
              <label className="form-label">靶点单元格内容<select className="field" value={sqliteForm.targetCellMode} onChange={(event) => setSQLiteForm((form) => ({ ...form, targetCellMode: event.target.value as "single" | "list" }))}><option value="list">多个标识，以分隔符拆分（旧缓存默认）</option><option value="single">单个名称或标识（保留名称内标点）</option></select></label>
              <label className="form-label">疾病—靶点表<input className="field" value={sqliteForm.diseaseTargetTable} onChange={(event) => setSQLiteForm((form) => ({ ...form, diseaseTargetTable: event.target.value }))} /></label>
              <label className="form-label">疾病列<input className="field" value={sqliteForm.diseaseColumn} onChange={(event) => setSQLiteForm((form) => ({ ...form, diseaseColumn: event.target.value }))} /></label>
              <label className="form-label">疾病靶点列<input className="field" value={sqliteForm.diseaseTargetColumn} onChange={(event) => setSQLiteForm((form) => ({ ...form, diseaseTargetColumn: event.target.value }))} /></label>
              <label className="form-label">来源文件列<input className="field" value={sqliteForm.diseaseSourceColumn} onChange={(event) => setSQLiteForm((form) => ({ ...form, diseaseSourceColumn: event.target.value }))} /></label>
              <label className="form-label">疾病—中药—靶点表<input className="field" value={sqliteForm.diseaseHerbTargetTable} onChange={(event) => setSQLiteForm((form) => ({ ...form, diseaseHerbTargetTable: event.target.value }))} /></label>
              <label className="form-label">疾病列<input className="field" value={sqliteForm.diseaseHerbColumn} onChange={(event) => setSQLiteForm((form) => ({ ...form, diseaseHerbColumn: event.target.value }))} /></label>
              <label className="form-label">中药列<input className="field" value={sqliteForm.diseaseHerbHerbColumn} onChange={(event) => setSQLiteForm((form) => ({ ...form, diseaseHerbHerbColumn: event.target.value }))} /></label>
              <label className="form-label">靶点列<input className="field" value={sqliteForm.diseaseHerbTargetColumn} onChange={(event) => setSQLiteForm((form) => ({ ...form, diseaseHerbTargetColumn: event.target.value }))} /></label>
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
              const isUniProt = summary.connector === "uniprot-human-catalog";
              const isPubChem = summary.connector === "pubchem-compound-catalog";
              const isString = summary.connector === "string-human-identifier-crosswalk";
              const syncLabel = isSQLite ? "SQLite 关系数据" : isUniProt ? "UniProt 人类审核蛋白目录" : isPubChem ? "PubChem 化合物属性" : isString ? "STRING 人类标识映射" : "Reactome 通路目录";
              const identityBlocked = isUniProt && (!summary.identityPlanSha256 || (summary.identifierConflicts ?? 0) > 0);
              const canApply = summary.mode === "preview" && run.status === "succeeded" && !activeApplyBases.has(run.id) && !identityBlocked;
              return <article className="panel source-run-record" key={run.id}>
                <div className="case-record-top"><div><h3>{run.source_name} · {summary.mode === "apply" ? "应用数据" : "预览数据"} #{run.id}</h3>
                  <time>{dateTime(run.created_at)} · {run.trigger === "scheduled" ? "定时预览" : "人工触发"} · 操作者：{run.requested_by_username ?? (run.trigger === "scheduled" ? "系统调度" : "未知")}</time></div>
                  <span className={`status-badge ${run.status === "succeeded" ? "status-success" : run.status === "failed" ? "status-error" : "status-warning"}`}>{runStatus(run.status)}</span></div>
                {run.status === "failed" && <div className="notice-error source-run-error" role="alert">{run.error_summary}</div>}
                {summary.mode === "preview" && run.status === "succeeded" && <>
                  <div className={`proteomics-metrics source-sync-metrics ${isSQLite ? "source-sync-metrics-sqlite" : ""}`}>
                    {isSQLite ? <>
                      <Metric label="输入行数" value={summary.totalRows ?? run.records_seen} />
                      <Metric label="中药实体" value={summary.uniqueHerbs ?? 0} />
                      <Metric label="成分实体" value={summary.uniqueCompounds ?? 0} />
                      <Metric label="靶点实体" value={summary.uniqueTargets ?? 0} />
                      <Metric label="疾病实体" value={summary.uniqueDiseases ?? 0} />
                      <Metric label="关系记录" value={summary.relationships ?? 0} />
                      <Metric label="将新增实体" value={summary.wouldCreate ?? 0} />
                      <Metric label="将更新实体" value={summary.wouldUpdate ?? 0} />
                      <Metric label="将停用旧实体" value={summary.wouldRetire ?? 0} />
                    </> : isUniProt ? <>
                      <Metric label="审核蛋白条目" value={summary.totalRecords ?? run.records_seen} />
                      <Metric label="新增 accession" value={summary.wouldCreate ?? 0} />
                      <Metric label="将更新关联" value={summary.wouldUpdate ?? 0} />
                      <Metric label="无需变化" value={summary.unchanged ?? 0} />
                      <Metric label="将停用旧 accession" value={summary.wouldRetire ?? 0} />
                      <Metric label="可关联现有靶点符号" value={summary.geneSymbolsMappedToExistingTargets ?? 0} />
                      <Metric label="本地符号冲突" value={summary.ambiguousLocalGeneSymbols ?? 0} />
                      <Metric label="物种未知的候选" value={summary.unknownSpeciesLocalTargets ?? 0} />
                      <Metric label="其他物种的候选" value={summary.otherSpeciesLocalTargets ?? 0} />
                      <Metric label="符号未核实的候选" value={summary.unverifiedLocalTargets ?? 0} />
                      <Metric label="沿用已有编号归属" value={summary.preservedAccessionMappings ?? 0} />
                      <Metric label="编号归属冲突" value={summary.identifierConflicts ?? 0} />
                    </> : isPubChem ? <>
                      <Metric label="已配置成分映射" value={summary.totalRecords ?? run.records_seen} />
                      <Metric label="新增 CID 关联" value={summary.wouldCreate ?? 0} />
                      <Metric label="将更新属性" value={summary.wouldUpdate ?? 0} />
                      <Metric label="无需变化" value={summary.unchanged ?? 0} />
                      <Metric label="将停用旧 CID" value={summary.wouldRetire ?? 0} />
                    </> : isString ? <>
                      <Metric label="本地人类实体" value={summary.localHumanEntityCount ?? 0} />
                      <Metric label="STRING 映射" value={summary.totalRecords ?? run.records_seen} />
                      <Metric label="新增标识" value={summary.wouldCreate ?? 0} />
                      <Metric label="将更新标识" value={summary.wouldUpdate ?? 0} />
                      <Metric label="未匹配查询" value={summary.unmappedQueries ?? 0} />
                      <Metric label="本地重名冲突" value={summary.ambiguousLocalEntities ?? 0} />
                      <Metric label="归属冲突" value={summary.identifierConflicts ?? 0} />
                      <Metric label="将停用旧标识" value={summary.wouldRetire ?? 0} />
                    </> : <>
                      <Metric label="通路总数" value={summary.totalRecords ?? run.records_seen} />
                      <Metric label="新增" value={summary.wouldCreate ?? 0} />
                      <Metric label="更新" value={summary.wouldUpdate ?? 0} />
                      <Metric label="停用" value={summary.wouldRetire ?? 0} />
                    </>}
                  </div>
                  <p className="source-release-line">{isSQLite ? `${summary.databaseFile ?? "SQLite 文件"} · ${summary.table ?? "数据表"} · ` : isUniProt ? `UniProt ${summary.sourceVersion ?? "未知版本"} · ${summary.pageCount ?? 0} 页 · ` : isPubChem ? `PubChem ${summary.sourceVersion ?? "快照"} · ${summary.pageCount ?? 0} 批 · ` : isString ? `STRING ${summary.sourceVersion ?? "未知版本"} · ${summary.submittedQueryCount ?? 0} 个查询 · ` : `Reactome v${summary.sourceVersion ?? "未知"} · `}来源版本 {summary.releaseVersion ?? run.release_version ?? "—"}</p>
                  <code className="source-checksum">SHA-256：{summary.checksumSha256 ?? run.release_checksum ?? "—"}</code>
                  {isPubChem && summary.previewRecords?.length ? <><ul className="proteomics-pathways source-table-counts">{summary.previewRecords.map((record) => <li key={record.cid}><strong>{record.compound} · CID {record.cid}</strong><span>{record.molecularFormula || "无分子式"} · {record.molecularWeight || "无分子量"} · {record.inchiKey || "无 InChIKey"}</span></li>)}</ul>{summary.previewRecordsTruncated && <p className="section-help">这里只展示前 20 条，完整映射数见上方统计。</p>}</> : null}
                  {isString && summary.previewRecords?.length ? <><ul className="proteomics-pathways source-table-counts">{summary.previewRecords.map((record) => <li key={record.entityStableId}><strong>{record.entityStableId} · {record.query}</strong><span>{record.stringId} · {record.preferredName || "无首选名称"} · {record.annotation || "无注释"}</span></li>)}</ul>{summary.previewRecordsTruncated && <p className="section-help">这里只展示前 20 条映射样例，完整数量见上方统计。</p>}</> : null}
                  <p className="section-help">{syncLabel}预览只保存来源版本与变更统计，不会修改知识目录。应用时会重新读取来源并核对校验值。</p>
                  {isUniProt && <p className="section-help">仅将物种明确为人类、符号未标记为待核实且无同名歧义的本地实体关联到目录。其余候选保留独立身份；已有编号不会仅因同名而转移归属。候选分类可能重叠，不能相加作为总数。</p>}
                  {isUniProt && identityBlocked && <p className="notice-error" role="alert">{!summary.identityPlanSha256 ? "这份旧预览没有身份核对依据，请重新预览。" : "已有编号归属冲突，请先核对物种与符号，再重新预览；本次不能应用。"}</p>}
                  {canApply && <button className="btn btn-primary source-apply-button" type="button" disabled={busy === run.source || activeSourceIds.has(run.source)}
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

  </>;
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div className="proteomics-metric"><span>{label}</span><strong>{value.toLocaleString("zh-CN")}</strong></div>;
}
