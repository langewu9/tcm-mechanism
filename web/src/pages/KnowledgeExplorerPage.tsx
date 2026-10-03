import { WorkspaceModuleNav } from "../components/WorkspaceModuleNav";
import { useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useOutletContext } from "react-router-dom";
import { ArrowLeft, Download, Search } from "lucide-react";
import { logout, type Session } from "../api/auth";
import { ApiError } from "../api/client";
import { BatchHerbEvidenceLookup } from "../components/BatchHerbEvidenceLookup";
import { ComponentComparisonResults } from "../components/ComponentComparisonResults";
import { getEntityNeighborhood, searchCatalogEntities, type EntityNeighborhood, type KnowledgeEntity, type KnowledgeSearchPage } from "../api/catalog";
import { compareComponents, searchChemblActivities, searchChemblMolecules, type ChemblActivitySearch, type ChemblMoleculeSearch, type ComponentComparison } from "../api/chembl";

const entityTypes = [
  ["", "全部实体"], ["disease", "疾病"], ["herb", "中药"], ["formula", "方剂"], ["compound", "成分"],
  ["syndrome", "证候"], ["gene", "基因"], ["protein", "蛋白"], ["pathway", "通路"],
];
const entityTypeLabel = Object.fromEntries(entityTypes.filter(([value]) => value).map(([value, label]) => [value, label]));

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "请求未完成，请稍后重试。";
}

function downloadNeighborhood(data: EntityNeighborhood) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${data.entity.stable_id.replace(/[^a-zA-Z0-9_-]+/g, "_")}-evidence.json`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function KnowledgeExplorerPage() {
  const user = useOutletContext<NonNullable<Session["user"]>>();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [entityType, setEntityType] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [activeType, setActiveType] = useState("");
  const [pageNumber, setPageNumber] = useState(1);
  const [entityPage, setEntityPage] = useState<KnowledgeSearchPage | null>(null);
  const [selected, setSelected] = useState<KnowledgeEntity | null>(null);
  const [neighborhood, setNeighborhood] = useState<EntityNeighborhood | null>(null);
  const [busy, setBusy] = useState(false);
  const [detailBusy, setDetailBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chemblQuery, setChemblQuery] = useState("");
  const [chemblConsent, setChemblConsent] = useState(false);
  const [chemblSearch, setChemblSearch] = useState<ChemblMoleculeSearch | null>(null);
  const [chemblActivity, setChemblActivity] = useState<ChemblActivitySearch | null>(null);
  const [chemblBusy, setChemblBusy] = useState(false);
  const [chemblBusyId, setChemblBusyId] = useState<string | null>(null);
  const [chemblError, setChemblError] = useState<string | null>(null);
  const [detectedComponents, setDetectedComponents] = useState("");
  const [referenceComponents, setReferenceComponents] = useState("");
  const [componentComparison, setComponentComparison] = useState<ComponentComparison | null>(null);
  const [componentCompareBusy, setComponentCompareBusy] = useState(false);
  const [componentCompareError, setComponentCompareError] = useState<string | null>(null);
  const detailRequest = useRef(0);

  async function loadEntities(search: string, type: string, page: number) {
    setBusy(true);
    setError(null);
    try {
      setEntityPage(await searchCatalogEntities(search, type, page));
      setPageNumber(page);
    } catch (cause) {
      setError(errorMessage(cause));
      setEntityPage(null);
    } finally {
      setBusy(false);
    }
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedQuery = query.trim();
    if (!normalizedQuery) {
      setError("请输入疾病、中药、方剂、成分、基因或通路名称。");
      return;
    }
    setActiveQuery(normalizedQuery);
    setActiveType(entityType);
    setSelected(null);
    setNeighborhood(null);
    detailRequest.current += 1;
    void loadEntities(normalizedQuery, entityType, 1);
  }

  async function submitChemblSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedQuery = chemblQuery.trim();
    if (!normalizedQuery) {
      setChemblError("请输入化合物名称或 ChEMBL 编号。");
      return;
    }
    if (!chemblConsent) {
      setChemblError("请先阅读并勾选外部查询同意项。");
      return;
    }
    setChemblBusy(true);
    setChemblError(null);
    setChemblActivity(null);
    try {
      setChemblSearch(await searchChemblMolecules(normalizedQuery, true));
    } catch (cause) {
      setChemblSearch(null);
      setChemblError(errorMessage(cause));
    } finally {
      setChemblBusy(false);
    }
  }

  async function loadChemblActivities(chemblId: string) {
    if (!chemblConsent) {
      setChemblError("请先勾选同意项，再查询该化合物的活性数据。");
      return;
    }
    setChemblBusyId(chemblId);
    setChemblError(null);
    setChemblActivity(null);
    try {
      setChemblActivity(await searchChemblActivities(chemblId, true));
    } catch (cause) {
      setChemblError(errorMessage(cause));
    } finally {
      setChemblBusyId(null);
    }
  }

  async function submitComponentCompare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setComponentCompareBusy(true);
    setComponentCompareError(null);
    try {
      setComponentComparison(await compareComponents(detectedComponents, referenceComponents));
    } catch (cause) {
      setComponentComparison(null);
      setComponentCompareError(errorMessage(cause));
    } finally {
      setComponentCompareBusy(false);
    }
  }

  async function selectEntity(entity: KnowledgeEntity) {
    const requestId = ++detailRequest.current;
    setSelected(entity);
    setNeighborhood(null);
    setDetailBusy(true);
    setError(null);
    try {
      const data = await getEntityNeighborhood(entity.id);
      if (detailRequest.current === requestId) setNeighborhood(data);
    } catch (cause) {
      if (detailRequest.current === requestId) setError(errorMessage(cause));
    } finally {
      if (detailRequest.current === requestId) setDetailBusy(false);
    }
  }

  async function signOut() {
    try { await logout(); navigate("/login", { replace: true }); }
    catch (cause) { setError(errorMessage(cause)); }
  }

  return <main className="workspace-page">
    <header className="workspace-nav">
      <Link to="/" className="site-brand" aria-label="远志 AI Scientist 首页"><img src="/images/yuanzhi-mark.png" alt="" width={42} height={42} className="brand-mark" /><span><strong>远志 AI Scientist</strong><small>研究者工作区</small></span></Link>
      <WorkspaceModuleNav isSuperuser={user.isSuperuser} />
      <div className="workspace-nav-actions"><span className="workspace-user">{user.username}{user.isSuperuser ? " · 平台管理员" : " · 研究者"}</span><button className="btn btn-secondary" type="button" onClick={() => void signOut()}>退出</button></div>
    </header>
    <div className="app-main workspace-main"><div className="app-main-inner">
      <div className="page-heading"><div className="page-heading-copy"><p className="page-kicker">Research knowledge catalogue</p><h1 className="page-title">科研知识检索</h1><p className="page-description">页面分开提供两类功能：本地目录只查询已导入知识；ChEMBL 外部查询仅在你主动勾选同意后才会发送查询词。</p></div><Link to="/" className="btn btn-secondary"><ArrowLeft size={16} />返回首页</Link></div>
      <section className="panel chembl-panel">
        <div className="panel-header"><div><p className="page-kicker">External evidence · ChEMBL</p><h2 className="section-title-sm">化合物与生物活性检索</h2><p className="section-help">借鉴 main 分支的 ChEMBL 化合物/活性查询。通过 ChEMBL 官方服务获取化合物编号、结构摘要、实验测定值和靶点信息。</p></div><a href="https://www.ebi.ac.uk/chembl/" target="_blank" rel="noreferrer">ChEMBL 官方数据</a></div>
        <form className="chembl-search-form" onSubmit={(event) => void submitChemblSearch(event)}>
          <label className="form-label" htmlFor="chembl-query">化合物名称或 ChEMBL 编号（多个名称可用逗号、顿号分隔）<input className="field" id="chembl-query" value={chemblQuery} maxLength={120} onChange={(event) => setChemblQuery(event.target.value)} placeholder="例如：槲皮素、quercetin、CHEMBL50" required /></label>
          <button className="btn btn-primary" type="submit" disabled={chemblBusy}>{chemblBusy ? "正在查询…" : "查询 ChEMBL"}</button>
          <label className="chembl-consent"><input type="checkbox" checked={chemblConsent} onChange={(event) => setChemblConsent(event.target.checked)} /><span>我同意将输入的查询词、系统按 main 内置别名展开出的英文检索词，以及我选择的 ChEMBL 编号用于后续活性查询，发送到 ChEMBL 官方服务。不会发送医案正文、上传文件或账号标识。</span></label>
        </form>
        {chemblError && <div className="notice-error workspace-notice" role="alert">{chemblError}</div>}
        {chemblSearch && <section className="chembl-results" aria-live="polite">
          <div className="case-list-heading"><div><p className="page-kicker">{chemblSearch.source} · {chemblSearch.sourceVersion}</p><h3 className="section-title-sm">化合物结果</h3></div><div className="case-list-actions"><span>{chemblSearch.results.length} / {chemblSearch.totalCount} 条</span><button className="btn btn-secondary" type="button" onClick={() => downloadJson(`chembl-molecules-${chemblSearch.sourceVersion}.json`, chemblSearch)}><Download size={14} />导出 JSON</button></div></div>
          <p className="knowledge-evidence-source">数据版本 {chemblSearch.sourceVersion}{chemblSearch.releaseDate ? `（${chemblSearch.releaseDate}）` : ""} · 查询时间 {new Date(chemblSearch.retrievedAt).toLocaleString()} · <a href="https://chembl.gitbook.io/chembl-interface-documentation/web-services/chembl-data-web-services" target="_blank" rel="noreferrer">官方 API 说明</a></p>
          {chemblSearch.nameMatches.length > 0 && <p className="notice-info">项目内置名称对应：{chemblSearch.nameMatches.map((item) => `${item.query} → ${item.english}${item.latin ? ` / ${item.latin}` : ""}（命中 ${item.hitCount}）`).join("；")}。别名源自 {chemblSearch.aliasSource} @ {chemblSearch.aliasSourceCommit}，只用于扩展检索词，尚未以当前项目的药物标准库核实。</p>}
          <p className="knowledge-evidence-source">发送到 ChEMBL 的检索词：{chemblSearch.resolvedQueries.join("、") || "无"}{chemblSearch.truncated ? ` · 结果已截断至 ${chemblSearch.resultLimit} 条` : ""}</p>
          {chemblSearch.failedQueries.length > 0 && <p className="notice-warning">部分别名查询未能连通，已展示成功返回的子查询：{chemblSearch.failedQueries.join("、")}</p>}
          {!chemblSearch.results.length ? <div className="empty-state"><strong>ChEMBL 没有返回匹配的化合物</strong><p>可以尝试英文通用名、其他别名或化合物编号。</p></div> : <div className="chembl-molecule-list">{chemblSearch.results.map((molecule) => <article className="chembl-molecule-card" key={molecule.chemblId}>
            <div className="chembl-molecule-copy"><h4>{molecule.preferredName || molecule.chemblId}</h4><p><a href={molecule.recordUrl} target="_blank" rel="noreferrer">{molecule.chemblId}</a>{molecule.moleculeType ? ` · ${molecule.moleculeType}` : ""}{molecule.maxPhase ? ` · 最高研发阶段 ${molecule.maxPhase}` : ""}{molecule.naturalProduct === 1 ? " · 天然产物" : molecule.naturalProduct === 0 ? " · 非天然产物" : " · 天然产物分类未标注"}</p>{molecule.canonicalSmiles && <details><summary>查看 canonical SMILES</summary><code>{molecule.canonicalSmiles}</code></details>}</div>
            <button className="btn btn-secondary" type="button" disabled={chemblBusyId === molecule.chemblId || !chemblConsent} onClick={() => void loadChemblActivities(molecule.chemblId)}>{chemblBusyId === molecule.chemblId ? "正在查询…" : "查看活性与靶点"}</button>
          </article>)}</div>}
        </section>}
        {chemblActivity && <section className="chembl-results" aria-live="polite">
          <div className="case-list-heading"><div><p className="page-kicker">{chemblActivity.chemblId} · {chemblActivity.sourceVersion}</p><h3 className="section-title-sm">实验活性与靶点</h3></div><div className="case-list-actions"><span>{chemblActivity.results.length} / {chemblActivity.totalCount} 条</span><button className="btn btn-secondary" type="button" onClick={() => downloadJson(`chembl-activities-${chemblActivity.chemblId}-${chemblActivity.sourceVersion}.json`, chemblActivity)}><Download size={14} />导出 JSON</button></div></div>
          <p className="knowledge-evidence-source">显示上限 {chemblActivity.resultLimit} 条 · 查询时间 {new Date(chemblActivity.retrievedAt).toLocaleString()} · 来源 <a href={`https://www.ebi.ac.uk/chembl/compound_report_card/${chemblActivity.chemblId}/`} target="_blank" rel="noreferrer">ChEMBL {chemblActivity.chemblId}</a></p>
          {!chemblActivity.results.length ? <div className="empty-state"><strong>没有可显示的实验活性记录</strong></div> : <div className="chembl-table-scroll"><table className="chembl-activity-table"><thead><tr><th>测定类型</th><th>标准化结果</th><th>pChEMBL</th><th>靶点</th><th>实验</th><th>文献</th></tr></thead><tbody>{chemblActivity.results.map((activity, index) => <tr key={activity.activityId ?? index}><td>{activity.standardType || "未标注"}</td><td>{activity.relation} {activity.value} {activity.units}</td><td>{activity.pchemblValue || "—"}</td><td>{activity.targetName || "未标注"}{activity.targetId && <small>{activity.targetId}</small>}</td><td>{activity.assayType || "—"} · {activity.assayDescription || activity.assayId || "未标注"}</td><td>{activity.documentId || "—"}</td></tr>)}</tbody></table></div>}
          {chemblActivity.truncated && <p className="notice-warning">记录总数超过单次上限：先按 pChEMBL 值由高到低显示有该值的记录，再补充有标准化测量值的记录。</p>}
          <p className="notice-warning">活性值受实验条件、测定类型和靶点物种影响；这些记录不等于临床疗效，也不会自动推断为中药作用机制。</p>
        </section>}
      </section>
      <section className="panel component-compare-panel">
        <div className="panel-header"><div><p className="page-kicker">Local name normalization · main aliases</p><h2 className="section-title-sm">检测成分与参考列表对照</h2><p className="section-help">比较检测列表和你提供的参考列表；仅根据 main 中的中英文/拉丁名表进行标准化，不会调用外部服务，也不会核验检测值或参考数据的真实性。</p></div></div>
        <form className="component-compare-form" onSubmit={(event) => void submitComponentCompare(event)}>
          <label className="form-label" htmlFor="detected-components">检测成分<textarea className="field" id="detected-components" value={detectedComponents} maxLength={6000} onChange={(event) => setDetectedComponents(event.target.value)} placeholder="例如：槲皮素；黄芩素；Ginsenoside Rg2" required /></label>
          <label className="form-label" htmlFor="reference-components">参考成分列表<textarea className="field" id="reference-components" value={referenceComponents} maxLength={6000} onChange={(event) => setReferenceComponents(event.target.value)} placeholder="例如：Quercetinum；Ginsenoside Rg1" required /></label>
          <button className="btn btn-primary" type="submit" disabled={componentCompareBusy}>{componentCompareBusy ? "正在对照…" : "开始对照"}</button>
        </form>
        <p className="knowledge-evidence-source">名称可用逗号、分号、顿号或换行分隔；每侧最多 100 项。完全同名的标准化匹配计为精确交集；同家族只标候选，不计入命中率。</p>
        {componentCompareError && <div className="notice-error workspace-notice" role="alert">{componentCompareError}</div>}
        {componentComparison && <ComponentComparisonResults data={componentComparison} />}
      </section>
      <BatchHerbEvidenceLookup />
      {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
      <div className="knowledge-explorer-grid">
        <section className="case-list">
          <form className="panel case-form" onSubmit={submitSearch}>
            <div className="panel-header"><div><h2 className="section-title-sm">检索本地知识目录</h2><p className="section-help">搜索实体名称或稳定标识；结果由管理员导入的数据源决定。</p></div><Search size={20} /></div>
            <div className="case-form-fields">
              <label className="form-label" htmlFor="catalog-query">关键词<input className="field" id="catalog-query" value={query} maxLength={120} onChange={(event) => setQuery(event.target.value)} placeholder="例如：肺纤维化、麦冬、甘草酸、TP53" required /></label>
              <label className="form-label" htmlFor="catalog-type">实体类型<select className="field" id="catalog-type" value={entityType} onChange={(event) => setEntityType(event.target.value)}>{entityTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            </div>
            <div className="case-form-footer"><p>未导入的名称会明确返回空结果，不会生成推测记录。</p><button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "正在检索…" : "检索"}</button></div>
          </form>
          {entityPage && <section className="panel knowledge-search-results" aria-live="polite">
            <div className="case-list-heading"><div><p className="page-kicker">Local catalogue</p><h2 className="section-title-sm">匹配结果</h2></div><span>{entityPage.count} 条</span></div>
            {activeType === "disease" && entityPage.expandedQueries && <p className="notice-info">main 疾病别名表 {entityPage.aliasSourceCommit} 展开的本地检索词：{entityPage.expandedQueries.join("、")}。这些词只帮助查找已导入记录；别名本身不表示疾病术语等价，也不构成研究证据。</p>}
            {!entityPage.results.length ? <div className="empty-state"><strong>没有匹配的已导入实体</strong><p>请检查名称，或联系平台管理员确认来源目录是否已同步。</p></div> : <div className="knowledge-entity-list">{entityPage.results.map((entity) => <button className="knowledge-entity-option" key={entity.id} type="button" aria-pressed={selected?.id === entity.id} onClick={() => void selectEntity(entity)}>
              <span><strong>{entity.label}</strong><small>{entityTypeLabel[entity.entity_type] ?? entity.entity_type} · {entity.stable_id}</small>{entity.matchedQueries?.length ? <small>匹配检索词：{entity.matchedQueries.join("、")}</small> : null}</span><small>{entity.source_slug ? `${entity.source_slug} ${entity.source_version ?? ""}` : "来源版本未登记"}</small>
            </button>)}</div>}
            {(entityPage.previous || entityPage.next) && <div className="case-pagination"><button className="btn btn-secondary" type="button" disabled={!entityPage.previous || busy} onClick={() => void loadEntities(activeQuery, activeType, pageNumber - 1)}>上一页</button><span>第 {pageNumber} 页</span><button className="btn btn-secondary" type="button" disabled={!entityPage.next || busy} onClick={() => void loadEntities(activeQuery, activeType, pageNumber + 1)}>下一页</button></div>}
          </section>}
        </section>
        <section className="case-list" aria-live="polite">
          {!selected ? <div className="panel empty-state"><Search size={27} /><strong>选择一个实体查看关系</strong><p>每条关系会并列展示来源及版本；不同来源记录不会被自动合并。</p></div> : detailBusy ? <div className="panel workspace-loading" role="status">正在载入「{selected.label}」的来源证据…</div> : !neighborhood ? <div className="panel empty-state"><strong>来源证据加载失败</strong><p>可以重试查询当前实体。</p><button className="btn btn-primary" type="button" onClick={() => void selectEntity(selected)}>重试</button></div> : <>
            <article className="panel knowledge-entity-detail">
              <div className="case-list-heading"><div><p className="page-kicker">{entityTypeLabel[neighborhood.entity.entity_type] ?? neighborhood.entity.entity_type}</p><h2 className="section-title-sm">{neighborhood.entity.label}</h2></div><button className="btn btn-secondary" type="button" onClick={() => downloadNeighborhood(neighborhood)}><Download size={15} />导出 JSON</button></div>
              <dl className="dataset-provenance"><div><dt>稳定标识</dt><dd>{neighborhood.entity.stable_id}</dd></div><div><dt>物种</dt><dd>{neighborhood.entity.organism || "未指定"}</dd></div><div><dt>实体来源</dt><dd>{neighborhood.entity.source_slug ?? "未登记"}</dd></div><div><dt>来源版本</dt><dd>{neighborhood.entity.source_version ?? "未登记"}</dd></div></dl>
            </article>
            <section className="knowledge-evidence-list"><div className="case-list-heading"><div><p className="page-kicker">Versioned provenance</p><h2 className="section-title-sm">关系证据</h2></div><span>{neighborhood.relations.length}{neighborhood.truncated ? "+" : ""} 条</span></div>
              {!neighborhood.relations.length ? <div className="panel empty-state"><strong>当前实体没有可展示的关系记录</strong><p>实体已存在于目录中，但可能尚未导入关联证据。</p></div> : neighborhood.relations.map((relation) => <article className="panel knowledge-evidence-card" key={relation.id}>
                <p className="knowledge-evidence-edge"><strong>{relation.subject_label}</strong><span>{relation.relation_type}</span><strong>{relation.object_label}</strong></p>
                <p className="knowledge-evidence-source">{relation.source_slug} · {relation.source_version} · {relation.evidence_type}{relation.organism ? ` · ${relation.organism}` : ""}{relation.score ? ` · 分值 ${relation.score}` : ""}</p>
                {relation.evidence_text && <p className="knowledge-evidence-text">{relation.evidence_text}</p>}
              </article>)}
              {neighborhood.truncated && <p className="notice-warning">关系数超过单次展示上限，当前显示前 200 条，请进一步缩小数据源或联系管理员导出。</p>}
            </section>
          </>}
        </section>
      </div>
    </div></div>
  </main>;
}
