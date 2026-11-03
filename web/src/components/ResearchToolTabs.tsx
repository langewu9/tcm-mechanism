// Tabs, query/result layout and labels adapted from origin/main@078d374:
// src/components/ResearchWorkbench.tsx. Data and consent stay on the Django APIs.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Activity, Beaker, Database, Download, FileJson, GitCompareArrows, Leaf, Route, Search, Sparkles, Table2 } from "lucide-react";
import { ApiError } from "../api/client";
import { getEntityNeighborhood, searchCatalogEntities, searchDiseaseEvidence, searchHerbComponentEvidence, searchReactomeCatalog, type DiseaseEvidenceSearch, type EntityNeighborhood, type HerbEvidenceSearch, type KnowledgeEntity, type KnowledgeSearchPage, type ReactomeCatalogResult } from "../api/catalog";
import { compareComponents, searchChemblActivities, searchChemblMolecules, type ChemblActivitySearch, type ChemblMoleculeSearch, type ComponentComparison } from "../api/chembl";
import { runNetworkPharmacology, type NetworkPharmacologyResult } from "../api/network";
import { downloadText, encodeCsv } from "../utils/downloads";
import { ComponentComparisonResults } from "./ComponentComparisonResults";
import { DiseaseEvidenceResults } from "./DiseaseEvidenceResults";
import { NetworkResultDownloads } from "./NetworkResultDownloads";
import { PaginatedTable } from "./PaginatedTable";
import { CatalogEvidenceFigures } from "./CatalogEvidenceFigures";
import { reactomeCatalogueCsv } from "./ReactomePathwayLookup";
import { CatalogRVisualization } from "./CatalogRVisualization";
import { RAnalysisGallery } from "./RAnalysisGallery";
import { EvidenceEntityTables } from "./EvidenceEntityTables";
import { TargetIntersectionFigure, TargetIntersectionNotice, intersectionState } from "./TargetIntersectionFigure";

type Action = "disease" | "herb" | "component" | "chembl" | "intersection" | "pathway" | "compare" | "catalogue";
const tools = [
  { id: "disease" as const, label: "疾病检索", hint: "疾病 -> 中药与靶点", icon: Search },
  { id: "herb" as const, label: "中药检索", hint: "中药 -> 成分与靶点", icon: Leaf },
  { id: "component" as const, label: "成分检索", hint: "成分 -> 来源与靶点", icon: Beaker },
  { id: "chembl" as const, label: "ChEMBL", hint: "分子、结构与活性", icon: Database },
  { id: "intersection" as const, label: "靶点交集", hint: "中药靶点 ∩ 疾病靶点", icon: Activity },
  { id: "pathway" as const, label: "通路检索", hint: "Reactome 人类通路目录", icon: Route },
  { id: "compare" as const, label: "成分对照", hint: "检测列表与参考列表", icon: GitCompareArrows },
  { id: "catalogue" as const, label: "知识目录", hint: "实体与来源证据", icon: Table2 },
];
const examples: Partial<Record<Action, string>> = {
  disease: "肺纤维化", herb: "麦冬、半夏、人参、大枣、甘草、粳米", component: "甘草酸", chembl: "甘草酸", pathway: "Interleukin", catalogue: "",
};
const maxBatchItems = 12;
const maxBatchNameLength = 120;
const maxBatchQueryLength = maxBatchItems * maxBatchNameLength + maxBatchItems - 1;
const entityTypes = [["", "全部实体"], ["disease", "疾病"], ["herb", "中药"], ["formula", "方剂"], ["compound", "成分"], ["syndrome", "证候"], ["gene", "基因"], ["protein", "蛋白"], ["pathway", "通路"]];
const entityTypeLabel = Object.fromEntries(entityTypes.filter(([value]) => value));
const jsonDownload = (name: string, data: unknown) => downloadText(name, JSON.stringify(data, null, 2), "application/json;charset=utf-8");
const csvDownload = (name: string, headers: string[], rows: Parameters<typeof encodeCsv>[1]) => downloadText(name, encodeCsv(headers, rows), "text/csv;charset=utf-8");
const errorMessage = (cause: unknown) => cause instanceof ApiError ? cause.message : "请求未完成，请稍后重试。";

export function ResearchToolTabs() {
  const [pageParams] = useSearchParams();
  const [active, setActive] = useState<Action>("herb");
  const [query, setQuery] = useState(examples.herb ?? "");
  const [herbs, setHerbs] = useState(examples.herb ?? "");
  const [disease, setDisease] = useState(examples.disease ?? "");
  const [detected, setDetected] = useState("甘草酸、甘草苷、人参皂苷Rg1");
  const [reference, setReference] = useState("Glycyrrhizic acid, Liquiritin, Ginsenoside Rg1");
  const [entityType, setEntityType] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<HerbEvidenceSearch | null>(null);
  const [chembl, setChembl] = useState<ChemblMoleculeSearch | null>(null);
  const [chemblActivity, setChemblActivity] = useState<ChemblActivitySearch | null>(null);
  const [chemblBusyId, setChemblBusyId] = useState<string | null>(null);
  const [comparison, setComparison] = useState<ComponentComparison | null>(null);
  const [pathways, setPathways] = useState<ReactomeCatalogResult | null>(null);
  const [network, setNetwork] = useState<NetworkPharmacologyResult | null>(null);
  const [diseaseEvidence, setDiseaseEvidence] = useState<DiseaseEvidenceSearch | null>(null);
  const [entityPage, setEntityPage] = useState<KnowledgeSearchPage | null>(null);
  const [activeQuery, setActiveQuery] = useState("");
  const [activeType, setActiveType] = useState("");
  const [pageNumber, setPageNumber] = useState(1);
  const [selected, setSelected] = useState<KnowledgeEntity | null>(null);
  const [neighborhood, setNeighborhood] = useState<EntityNeighborhood | null>(null);
  const [detailBusy, setDetailBusy] = useState(false);
  const requestId = useRef(0);
  const detailRequest = useRef(0);
  const requestLock = useRef<number | null>(null);
  const detailLock = useRef<number | null>(null);
  const mounted = useRef(true);
  const consentCurrent = useRef(false);
  const toolGeneration = useRef(0);
  const generation = toolGeneration.current;
  const displayedRequest = requestId.current;
  const selectedTool = tools.find((tool) => tool.id === active)!;
  const hasResult = Boolean(evidence || chembl || comparison || pathways || network || diseaseEvidence || entityPage
    || ((active === "herb" || active === "component") && pageParams.has("catalogTask")));

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      requestId.current += 1; detailRequest.current += 1;
      requestLock.current = null; detailLock.current = null;
    };
  }, []);

  const currentTool = () => mounted.current && toolGeneration.current === generation;
  const currentRequest = (id: number) => mounted.current && requestId.current === id;
  const currentDetail = (id: number) => mounted.current && detailRequest.current === id;

  function updateConsent(value: boolean) {
    consentCurrent.current = value; setConsent(value);
  }

  function resetDetails() {
    detailRequest.current += 1; detailLock.current = null;
    setSelected(null); setNeighborhood(null); setChemblActivity(null);
    setChemblBusyId(null); setDetailBusy(false);
  }

  function resetResults() {
    setEvidence(null); setChembl(null); setComparison(null); setPathways(null); setNetwork(null); setDiseaseEvidence(null); setEntityPage(null);
    resetDetails();
  }

  function changeTool(action: Action) {
    toolGeneration.current += 1; requestId.current += 1; requestLock.current = null;
    setActive(action); updateConsent(false); setError(null); setBusy(false); resetResults();
    if (examples[action] !== undefined) setQuery(examples[action]!);
  }

  async function run<T>(request: () => Promise<T>, receive: (data: T) => void) {
    if (!currentTool() || requestLock.current !== null) return;
    const id = ++requestId.current;
    requestLock.current = id;
    setBusy(true); setError(null);
    try { const data = await request(); if (currentRequest(id)) receive(data); }
    catch (cause) { if (currentRequest(id)) setError(errorMessage(cause)); }
    finally {
      if (requestLock.current === id) requestLock.current = null;
      if (currentRequest(id)) setBusy(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!currentTool() || requestLock.current !== null) return;
    if (active === "chembl" && !consentCurrent.current) { setError("请先阅读并勾选外部查询同意项。"); return; }
    if ((active === "herb" || active === "component")) {
      const queries = [...new Set(query.split(/[,，、;；|/\n\r]+/).map((name) => name.trim()).filter(Boolean))];
      if (!queries.length || queries.length > maxBatchItems) { setError(queries.length ? `每次最多查询 ${maxBatchItems} 个名称。` : "请输入至少一个名称。"); return; }
      if (queries.some((name) => Array.from(name).length > maxBatchNameLength)) { setError(`每个名称最多 ${maxBatchNameLength} 个字符，请缩短超长项后重试。`); return; }
      resetResults();
      await run(() => searchHerbComponentEvidence(active === "herb" ? "herb" : "compound", queries), setEvidence);
    } else if (active === "chembl") {
      updateConsent(false); resetResults(); await run(() => searchChemblMolecules(query.trim(), true), setChembl);
    } else if (active === "compare") {
      resetResults(); await run(() => compareComponents(detected, reference), setComparison);
    } else if (active === "pathway") {
      resetResults(); await run(() => searchReactomeCatalog(query.trim()), setPathways);
    } else if (active === "intersection") {
      resetResults(); await run(() => runNetworkPharmacology({ herb: herbs, disease }), setNetwork);
    } else if (active === "disease") {
      resetResults(); await run(() => searchDiseaseEvidence(query.trim()), setDiseaseEvidence);
    } else {
      const type = entityType;
      resetResults(); setActiveQuery(query.trim()); setActiveType(type); setPageNumber(1);
      await run(() => searchCatalogEntities(query.trim(), type), setEntityPage);
    }
  }

  async function loadEntities(page: number) {
    if (!currentTool() || requestId.current !== displayedRequest || requestLock.current !== null) return;
    resetDetails();
    await run(() => searchCatalogEntities(activeQuery, activeType, page), (data) => { setEntityPage(data); setPageNumber(page); });
  }

  async function selectEntity(entity: KnowledgeEntity) {
    if (!currentTool() || requestId.current !== displayedRequest || requestLock.current !== null) return;
    const id = ++detailRequest.current;
    setSelected(entity); setNeighborhood(null); setDetailBusy(true); setError(null);
    try {
      const data = await getEntityNeighborhood(entity.id);
      if (data.entity.id !== entity.id) throw new ApiError("来源证据与所选实体不一致，请重新加载。", "EVIDENCE_SOURCE_MISMATCH", null, null, 502);
      if (currentDetail(id)) setNeighborhood(data);
    }
    catch (cause) { if (currentDetail(id)) setError(errorMessage(cause)); }
    finally { if (currentDetail(id)) setDetailBusy(false); }
  }

  async function loadChemblActivities(chemblId: string) {
    if (!currentTool() || requestId.current !== displayedRequest || requestLock.current !== null || detailLock.current !== null) return;
    if (!consentCurrent.current) { setError("请先勾选同意项，再查询该化合物的活性数据。"); return; }
    const id = ++detailRequest.current;
    detailLock.current = id; updateConsent(false);
    setChemblBusyId(chemblId); setChemblActivity(null); setError(null);
    try {
      const data = await searchChemblActivities(chemblId, true);
      if (data.chemblId !== chemblId) throw new ApiError("活性数据与所选 ChEMBL 化合物不一致，请重新查询。", "EVIDENCE_SOURCE_MISMATCH", null, null, 502);
      if (currentDetail(id)) setChemblActivity(data);
    }
    catch (cause) { if (currentDetail(id)) setError(errorMessage(cause)); }
    finally {
      if (detailLock.current === id) detailLock.current = null;
      if (currentDetail(id)) setChemblBusyId(null);
    }
  }

  return <div className="space-y-5 research-workbench">
    <div><h2 className="page-title">中医药理检索</h2><p className="page-description">统一检索本地中医药数据库与 ChEMBL，快速完成疾病、中药、成分和靶点关联查询。</p></div>
    <div className="tool-tabs" role="tablist" aria-label="检索类型">{tools.map((tool) => {
      const Icon = tool.icon;
      return <button key={tool.id} id={`research-tab-${tool.id}`} className={`tool-tab ${active === tool.id ? "is-active" : ""}`} type="button" role="tab" aria-selected={active === tool.id} aria-controls="research-tool-panel" tabIndex={active === tool.id ? 0 : -1} onClick={() => changeTool(tool.id)} onKeyDown={(event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const current = tools.findIndex((item) => item.id === active);
        const next = event.key === "Home" ? 0 : event.key === "End" ? tools.length - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + tools.length) % tools.length;
        changeTool(tools[next].id); document.getElementById(`research-tab-${tools[next].id}`)?.focus();
      }}><Icon size={17} /><span><strong>{tool.label}</strong><small>{tool.hint}</small></span></button>;
    })}</div>
    <div className="research-workbench-grid workspace-split workspace-split--search" id="research-tool-panel" role="tabpanel" aria-labelledby={`research-tab-${active}`}>
      <form className="panel research-query-form" onSubmit={(event) => void submit(event)}>
        <div><h3 className="section-title-sm">{selectedTool.label}</h3><p className="section-help">{selectedTool.hint}</p></div>
        <div className="case-form-fields">
          {active === "intersection" ? <>
            <label className="form-label" htmlFor="intersection-herbs">中药名称（可输入多个）<textarea id="intersection-herbs" className="field" value={herbs} maxLength={1200} onChange={(event) => setHerbs(event.target.value)} placeholder="例如：麦冬、半夏、人参、大枣、甘草、粳米" required /></label>
            <label className="form-label" htmlFor="intersection-disease">疾病名称（支持中文）<input id="intersection-disease" className="field" value={disease} maxLength={300} onChange={(event) => setDisease(event.target.value)} placeholder="例如：肺纤维化" required /></label>
          </> : active === "compare" ? <>
            <label className="form-label" htmlFor="detected-components">检测成分（中文 / 英文 / 拉丁，可多个）<textarea id="detected-components" className="field" value={detected} maxLength={6000} onChange={(event) => setDetected(event.target.value)} required /></label>
            <label className="form-label" htmlFor="reference-components">参考成分（中文 / 英文 / 拉丁，可多个）<textarea id="reference-components" className="field" value={reference} maxLength={6000} onChange={(event) => setReference(event.target.value)} required /></label>
          </> : active === "herb" ? <label className="form-label" htmlFor="research-query">中药名称（可输入多个）<textarea id="research-query" className="field" value={query} maxLength={maxBatchQueryLength} onChange={(event) => setQuery(event.target.value)} placeholder="例如：麦冬、半夏、人参、大枣、甘草、粳米" required /></label> : active === "component" ? <label className="form-label" htmlFor="research-query">成分名称（中文 / 英文 / 拉丁）<input id="research-query" className="field" value={query} maxLength={maxBatchQueryLength} onChange={(event) => setQuery(event.target.value)} placeholder="例如：甘草酸 / Glycyrrhizic acid" required /></label> : <label className="form-label" htmlFor="research-query">{active === "chembl" ? "分子名称（中文 / 英文 / 拉丁 / ChEMBL 规范名）" : active === "pathway" ? "通路名称或稳定 ID" : "检索词"}<input id="research-query" className="field" value={query} maxLength={active === "pathway" ? 160 : 120} onChange={(event) => { setQuery(event.target.value); if (active === "chembl") updateConsent(false); }} placeholder={active === "pathway" ? "例如：Interleukin 或 R-HSA-449147" : active === "chembl" ? "例如：甘草酸 / Glycyrrhizic acid" : `例如：${examples[active] || "肺纤维化、麦冬、TP53"}`} required={active !== "pathway" && (active !== "catalogue" || entityType === "disease")} /></label>}
          {active === "catalogue" && <label className="form-label" htmlFor="catalog-type">实体类型<select className="field" id="catalog-type" value={entityType} onChange={(event) => setEntityType(event.target.value)}>{entityTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>}
          {active === "chembl" && <label className="chembl-consent"><input type="checkbox" checked={consent} onChange={(event) => updateConsent(event.target.checked)} /><span>我同意将输入的查询词、别名展开的检索词，以及选中的 ChEMBL 编号发送到 ChEMBL 官方服务。不会发送医案正文、上传文件或账号标识。每次查询后同意项会清除；查看活性需重新勾选。</span></label>}
          {active === "herb" || active === "component" ? <p className="section-help">支持逗号、分号、顿号、竖线或换行分隔，每次最多 12 项。仅查询已导入并启用的数据库目录。</p> : active === "compare" ? <p className="section-help">每侧最多 100 项，按名称词表进行标准化；同家族只标候选，不计入精确交集。不会向外部服务发送名称。</p> : active === "pathway" ? <p className="section-help">检索已同步的本地目录；输入为空时展示按名称排序的前 100 项。</p> : active === "disease" ? <p className="section-help">按整词疾病别名检索已启用来源；同名来源记录分别保留，不自动扩大到疾病亚型。</p> : active === "catalogue" ? <p className="section-help">按名称或标识检索；常用成分支持中英文和拉丁文同义名。留空可浏览目录，疾病需输入名称。只展示已导入的来源证据。</p> : null}
          {error && <div className="notice-error" role="alert">{error}</div>}
          <button className="btn btn-primary" disabled={busy} type="submit"><Search size={17} />{busy ? "正在检索..." : "开始检索"}</button>
        </div>
      </form>
      <section className="panel research-workbench-results" aria-live="polite" aria-busy={busy}>
        {busy ? <><div className="panel-header"><h3 className="section-title-sm">检索结果</h3></div><div className="workspace-loading" role="status">正在检索…</div></> : !hasResult ? <><div className="panel-header"><div><h3 className="section-title-sm">检索结果</h3><p className="section-help">等待检索</p></div></div><div className="empty-state"><Sparkles size={28} /><strong>从左侧开始检索</strong><p>输入名称后点击“开始检索”。</p></div></> : <>
          {evidence && <EvidenceResults data={evidence} />}
          {comparison && <ComponentComparisonResults data={comparison} />}
          {pathways && <PathwayResults data={pathways} />}
          {chembl && <ChemblResults data={chembl} activities={chemblActivity} busyId={chemblBusyId} consent={consent} onActivities={(id) => void loadChemblActivities(id)} />}
          {network && <IntersectionResults data={network} onDiseaseSelect={(label) => {
            if (!currentTool() || requestId.current !== displayedRequest || requestLock.current !== null) return;
            setDisease(label); resetResults();
          }} />}
          {diseaseEvidence && <DiseaseEvidenceResults data={diseaseEvidence} />}
          {entityPage && <>
            <div className="panel-header"><div><h3 className="section-title-sm">匹配结果</h3><p className="section-help">{activeQuery} · {entityPage.count} 条</p></div><span className="status-badge status-success">查询完成</span></div>
            <div className="case-form-fields">
              {activeType === "disease" && entityPage.expandedQueries && <p className="notice-info">本次扩展检索词：{entityPage.expandedQueries.join("、")}。这些词只帮助查找已导入记录；不表示疾病术语等价，也不构成研究证据。</p>}
              {!entityPage.results.length ? <div className="empty-state"><strong>没有匹配的已导入实体</strong><p>请检查名称，或联系平台管理员确认来源目录是否已同步。</p></div> : <div className="knowledge-entity-list">{entityPage.results.map((entity) => <button className="knowledge-entity-option" key={entity.id} type="button" aria-pressed={selected?.id === entity.id} onClick={() => void selectEntity(entity)}><span><strong>{entity.label}</strong><small>{entityTypeLabel[entity.entity_type] ?? entity.entity_type} · {entity.stable_id}</small>{entity.matchedQueries?.length ? <small>匹配检索词：{entity.matchedQueries.join("、")}</small> : null}</span><small>{entity.source_slug ? `${entity.source_slug} ${entity.source_version ?? ""}` : "来源版本未登记"}</small></button>)}</div>}
              {(entityPage.previous || entityPage.next) && <div className="case-pagination"><button className="btn btn-secondary" type="button" disabled={!entityPage.previous || busy} onClick={() => void loadEntities(pageNumber - 1)}>上一页</button><span>第 {pageNumber} 页</span><button className="btn btn-secondary" type="button" disabled={!entityPage.next || busy} onClick={() => void loadEntities(pageNumber + 1)}>下一页</button></div>}
              {!selected ? null : detailBusy ? <div className="workspace-loading" role="status">正在载入「{selected.label}」的来源证据…</div> : !neighborhood ? <div className="empty-state"><strong>来源证据加载失败</strong><button className="btn btn-primary" type="button" onClick={() => void selectEntity(selected)}>重试</button></div> : <CatalogEvidence data={neighborhood} />}
            </div>
          </>}
        </>}
        {!busy && !evidence && (active === "herb" || active === "component") && <CatalogEvidenceFigures evidence={evidence} />}
      </section>
    </div>
  </div>;
}

function EvidenceResults({ data }: { data: HerbEvidenceSearch }) {
  const uniqueEntities = <T extends { id: number }>(items: T[]) => [...new Map(items.map((item) => [item.id, item])).values()];
  const matches = uniqueEntities(data.results.flatMap((item) => item.matches));
  const herbs = uniqueEntities(data.results.flatMap((item) => item.herbs));
  const compounds = uniqueEntities(data.results.flatMap((item) => item.compounds));
  const targets = uniqueEntities(data.results.flatMap((item) => item.targets));
  const relations = data.results.flatMap((item) => item.relations.map((row) => ({ query: item.query, ...row })));
  const label = data.queryType === "herb" ? "中药检索结果" : "成分检索结果";
  return <>
    <div className="panel-header"><div><h3 className="section-title-sm">{label}</h3><p className="section-help">{data.results.map((item) => item.query).join("、")}</p></div><span className={`status-badge ${matches.length ? "status-success" : "status-pending"}`}>{matches.length ? "查询完成" : "未找到匹配"}</span></div>
    <div className="case-form-fields">
      {data.dataQuality?.map((item) => <div className="notice-info" key={item.version}><p>{item.source.toUpperCase()}：已核验 {item.verifiedTargetIds.toLocaleString()} 个靶点编号，{item.quarantinedRows.toLocaleString()} 条来源记录待复核。</p><details><summary>数据范围与版本</summary><p>{item.message}</p><span style={{ overflowWrap: "anywhere" }}>{item.source} · {item.version}</span></details></div>)}
      {matches.length > 0 && <CatalogRVisualization key={data.evidenceSha256 ?? data.results.map(item => item.query).join("|")} query={{ queryType: data.queryType, queries: data.results.map(item => item.query), expectedSha256: data.evidenceSha256 }} />}
      <div className="np-metrics"><div><span>{data.queryType === "herb" ? "匹配中药" : "匹配成分记录"}</span><strong>{matches.length}</strong></div><div><span>{data.queryType === "herb" ? "关联成分" : "来源中药"}</span><strong>{data.queryType === "herb" ? compounds.length : herbs.length}</strong></div><div><span>作用靶点</span><strong>{targets.length}</strong></div><div><span>返回关系记录</span><strong>{relations.length}</strong></div></div>
      {!matches.length && <p className="notice-info" role="status">未在已启用数据库中匹配到该名称。请核对拼写，或尝试其规范名称；这不表示该成分不存在。</p>}
      {data.queryType === "herb" && <div className="table-scroll"><table className="data-table" aria-label="逐项中药检索汇总">
        <thead><tr><th>检索词</th><th>命中中药</th><th>成分数</th><th>靶点数</th><th>返回关系</th></tr></thead>
        <tbody>{data.results.map((item) => <tr key={item.query}><td>{item.query}</td><td>{item.matches.length ? `${uniqueEntities(item.matches).length} 条目录实体` : "未匹配"}</td><td>{uniqueEntities(item.compounds).length}</td><td>{uniqueEntities(item.targets).length}</td><td>{item.relations.length}{item.truncated ? "+" : ""}</td></tr>)}</tbody>
      </table></div>}
      <p className="section-help">成分和靶点清单按实体 ID 去重，同名不同标识并列保留。关系表按检索词保留返回证据，完整 JSON 包含各项查询与截断状态。</p>
      <div className="download-panel">
        <button type="button" onClick={() => csvDownload("herb-component-evidence.csv", ["检索词", "来源库", "来源版本", "原始记录号", "主体", "主体类型", "关系", "客体", "客体类型", "证据类型", "分值"], relations.map((row) => [row.query, row.sourceSlug, row.sourceVersion, row.sourceRecordId, row.subject, row.subjectType, row.relationType, row.object, row.objectType, row.evidenceType, row.score]))}><Table2 size={15} />导出成分-靶点表</button>
        <button type="button" onClick={() => csvDownload("herb-components.csv", ["成分", "稳定 ID", "来源", "版本"], compounds.map((row) => [row.label, row.stableId, row.sourceSlug, row.sourceVersion]))}><Download size={15} />导出成分清单</button>
        <button type="button" onClick={() => csvDownload("herb-targets.csv", ["靶点", "稳定 ID", "来源", "版本"], targets.map((row) => [row.label, row.stableId, row.sourceSlug, row.sourceVersion]))}><Download size={15} />导出靶点清单</button>
        <button type="button" onClick={() => jsonDownload("herb-component-search.json", data)}><FileJson size={15} />导出完整 JSON</button>
      </div>
      {data.results.map((item) => <article className="batch-evidence-item" key={item.query}><h4>{item.query}</h4>{item.searchedNames && item.searchedNames.length > 1 && <p className="notice-info">同义名检索：{item.searchedNames.join(" / ")}</p>}{item.ambiguous && <p className="notice-warning">{data.queryType === "herb" ? "匹配到多个中药来源记录，按标识分别展示，请核对目录来源。" : "匹配到多个来源目录记录，按标识分别保留；记录数不等于化合物种类数，请核对来源。"}</p>}<EvidenceEntityTables item={item} />{item.truncated && <p className="notice-warning">接口返回有截断：每类关系最多 1,200 条。导出同样只包含本次返回记录，请进一步拆分查询。</p>}</article>)}
    </div>
    {relations.length ? <PaginatedTable rows={relations} label="成分-靶点证据" headers={["检索词", "来源库", "版本", "主体", "关系", "客体", "原始记录号"]} rowKey={(row, index) => `${row.query}-${row.sourceSlug}-${row.sourceRecordId}-${index}`} renderCells={(row) => <><td>{row.query}</td><td>{row.sourceSlug}</td><td>{row.sourceVersion}</td><td>{row.subject}</td><td>{row.relationType}</td><td>{row.object}</td><td>{row.sourceRecordId}</td></>} /> : <div className="empty-state">当前名称没有已导入的关联证据，请更换关键词或确认来源目录已同步。</div>}
  </>;
}

function PathwayResults({ data }: { data: ReactomeCatalogResult }) {
  return <>
    <div className="panel-header"><div><h3 className="section-title-sm">通路检索结果</h3><p className="section-help">{data.query || "全部人类通路"}</p></div><span className={`status-badge ${data.catalogTotal ? "status-success" : "status-pending"}`}>{data.catalogTotal ? "已导入本地目录" : "目录待同步"}</span></div>
    {data.items.length > 0 && <CatalogRVisualization query={{ queryType: "pathway", queries: [data.query], expectedSha256: data.evidenceSha256 }} />}
    <div className="case-form-fields"><p className="section-help">人类通路目录 {data.catalogTotal} 条，本次匹配 {data.matchedTotal} 条，显示 {data.items.length} 条。</p>{data.warnings.map((warning) => <p className="notice-info" key={warning}>{warning}</p>)}{data.truncated && <p className="notice-warning">匹配超过 {data.maxItems} 条，页面和 CSV/JSON 均只包含前 {data.maxItems} 条。请缩小查询范围。</p>}<div className="download-panel"><button type="button" disabled={!data.items.length} onClick={() => downloadText("reactome-pathways.csv", reactomeCatalogueCsv(data), "text/csv;charset=utf-8")}><Table2 size={15} />导出通路目录 CSV</button><button type="button" onClick={() => jsonDownload("reactome-pathways.json", data)}><FileJson size={15} />导出结果 JSON</button></div></div>
    {data.items.length ? <PaginatedTable rows={data.items} label="Reactome 人类通路" headers={["稳定 ID", "通路名称", "物种", "本地靶点注释", "历史富集记录", "来源版本", "最近同步", "Reactome"]} rowKey={(row) => row.stableId} renderCells={(row) => <><td>{row.stableId}</td><td>{row.name}</td><td>{row.species}</td><td>{row.targetAnnotations}{row.annotationSources.length > 0 && <small style={{ display: "block" }}>{row.annotationSources.map((source) => `${source.sourceSlug}:${source.sourceVersion}`).join("；")}</small>}</td><td>{row.enrichmentRecords ?? "未登记"}</td><td>{row.sourceVersion}</td><td>{new Date(row.lastSyncedAt).toLocaleDateString("zh-CN")}</td><td><a href={row.sourceUrl} target="_blank" rel="noreferrer">打开</a></td></>} /> : <div className="empty-state"><strong>{data.catalogTotal ? "未找到匹配通路" : "尚无启用的 Reactome 人类目录"}</strong><p>{data.catalogTotal ? "请换用通路名称或 R-HSA 稳定 ID。" : "平台管理员可在数据源同步页预览并应用 Reactome 目录。"}</p></div>}
    <details className="raw-details"><summary>本次目录来源与校验值</summary>{data.sources.map((source) => <p className="section-help" style={{ overflowWrap: "anywhere" }} key={`${source.sourceSlug}-${source.sourceVersion}`}>{source.sourceSlug} · {source.sourceVersion} · SHA-256 {source.checksumSha256 || "尚未登记"}</p>)}</details>
  </>;
}

function ChemblResults({ data, activities, busyId, consent, onActivities }: { data: ChemblMoleculeSearch; activities: ChemblActivitySearch | null; busyId: string | null; consent: boolean; onActivities: (id: string) => void }) {
  return <>
    <div className="panel-header"><div><h3 className="section-title-sm">ChEMBL 检索结果</h3><p className="section-help">{data.results.length} / {data.totalCount} 条 · {data.source} {data.sourceVersion}</p></div><span className="status-badge status-success">查询完成</span></div>
    <div className="case-form-fields"><p className="knowledge-evidence-source">数据版本 {data.sourceVersion}{data.releaseDate ? `（${data.releaseDate}）` : ""} · 查询时间 {new Date(data.retrievedAt).toLocaleString()} · <a href="https://chembl.gitbook.io/chembl-interface-documentation/web-services/chembl-data-web-services" target="_blank" rel="noreferrer">官方 API 说明</a></p>{data.nameMatches.length > 0 && <p className="notice-info">项目内置名称对应：{data.nameMatches.map((item) => `${item.query} → ${item.english}${item.latin ? ` / ${item.latin}` : ""}（命中 ${item.hitCount}）`).join("；")}。别名源自 {data.aliasSource} @ {data.aliasSourceCommit}，只用于扩展检索词，尚未以当前项目的药物标准库核实。</p>}<p className="knowledge-evidence-source">发送到 ChEMBL 的检索词：{data.resolvedQueries.join("、") || "无"}{data.truncated ? ` · 结果已截断至 ${data.resultLimit} 条` : ""}</p>{data.failedQueries.length > 0 && <p className="notice-warning">部分别名查询未能连通，已展示成功返回的子查询：{data.failedQueries.join("、")}</p>}<div className="download-panel"><button type="button" onClick={() => jsonDownload(`chembl-molecules-${data.sourceVersion}.json`, data)}><FileJson size={15} />导出 JSON</button></div>
      {!data.results.length ? <div className="empty-state"><strong>ChEMBL 没有返回匹配的化合物</strong><p>可以尝试英文通用名、其他别名或化合物编号。</p></div> : <div className="chembl-molecule-list">{data.results.map((molecule) => <article className="chembl-molecule-card" key={molecule.chemblId}><div className="chembl-molecule-copy"><h4>{molecule.preferredName || molecule.chemblId}</h4><p><a href={molecule.recordUrl} target="_blank" rel="noreferrer">{molecule.chemblId}</a>{molecule.moleculeType ? ` · ${molecule.moleculeType}` : ""}{molecule.maxPhase ? ` · 最高研发阶段 ${molecule.maxPhase}` : ""}{molecule.naturalProduct === 1 ? " · 天然产物" : molecule.naturalProduct === 0 ? " · 非天然产物" : " · 天然产物分类未标注"}</p>{molecule.canonicalSmiles && <details><summary>查看 canonical SMILES</summary><code>{molecule.canonicalSmiles}</code></details>}</div><button className="btn btn-secondary" type="button" disabled={busyId !== null || !consent} onClick={() => onActivities(molecule.chemblId)}>{busyId === molecule.chemblId ? "正在查询…" : "查看活性与靶点"}</button></article>)}</div>}
    </div>
    {activities && <section aria-live="polite"><div className="panel-header"><div><h3 className="section-title-sm">实验活性与靶点</h3><p className="section-help">{activities.chemblId} · {activities.sourceVersion} · {activities.results.length} / {activities.totalCount} 条</p></div><button className="btn btn-secondary" type="button" onClick={() => jsonDownload(`chembl-activities-${activities.chemblId}-${activities.sourceVersion}.json`, activities)}><Download size={15} />导出 JSON</button></div>{activities.results.length ? <PaginatedTable rows={activities.results} label="ChEMBL 活性" headers={["测定类型", "标准化结果", "pChEMBL", "靶点", "实验", "文献"]} rowKey={(row, index) => String(row.activityId ?? index)} renderCells={(row) => <><td>{row.standardType || "未标注"}</td><td>{row.relation} {row.value} {row.units}</td><td>{row.pchemblValue || "—"}</td><td>{row.targetName || "未标注"}{row.targetId && <small>{row.targetId}</small>}</td><td>{row.assayType || "—"} · {row.assayDescription || row.assayId || "未标注"}</td><td>{row.documentId || "—"}</td></>} /> : <div className="empty-state"><strong>没有可显示的实验活性记录</strong></div>}<div className="case-form-fields"><p className="knowledge-evidence-source">显示上限 {activities.resultLimit} 条 · 查询时间 {new Date(activities.retrievedAt).toLocaleString()} · 来源 <a href={`https://www.ebi.ac.uk/chembl/compound_report_card/${activities.chemblId}/`} target="_blank" rel="noreferrer">ChEMBL {activities.chemblId}</a></p>{activities.truncated && <p className="notice-warning">记录总数超过单次上限：先按 pChEMBL 值由高到低显示有该值的记录，再补充有标准化测量值的记录。</p>}<p className="notice-warning">活性值受实验条件、测定类型和靶点物种影响；这些记录不等于临床疗效，也不会自动推断为中药作用机制。</p></div></section>}
  </>;
}

function IntersectionResults({ data, onDiseaseSelect }: { data: NetworkPharmacologyResult; onDiseaseSelect: (label: string) => void }) {
  const strictRows = data.targets.filter((row) => row.matchType === "严格交集");
  const state = intersectionState(data);
  return <>
    <div className="panel-header"><div><h3 className="section-title-sm">靶点交集结果</h3><p className="section-help">{data.summary.herb} ∩ {data.summary.disease}</p></div><span className={`status-badge ${state.comparable && !state.partial ? "status-success" : "status-pending"}`}>{state.badge}</span></div>
    <div className="case-form-fields">
      {data.dataQuality?.map((item) => <div className="notice-info" key={item.version}><p>{item.source.toUpperCase()}：已核验 {item.verifiedTargetIds.toLocaleString()} 个靶点编号，{item.quarantinedRows.toLocaleString()} 条来源记录待复核。</p><details><summary>数据范围与版本</summary><p>{item.message}</p><span style={{ overflowWrap: "anywhere" }}>{item.source} · {item.version}</span></details></div>)}
      <TargetIntersectionNotice result={data} onDiseaseSelect={onDiseaseSelect} />
      <TargetIntersectionFigure result={data} />
      <div className="np-metrics"><div><span>已返回中药靶点</span><strong>{data.summary.herbTargetCount.toLocaleString()}</strong></div><div><span>已返回疾病靶点</span><strong>{data.summary.unmatchedDiseases.length ? "待匹配" : data.summary.diseaseTargetCount.toLocaleString()}</strong></div><div><span>已核验标准基因交集</span><strong>{data.targetIdentity?.available ? (data.targetIdentity.verifiedGeneIntersectionCount ?? 0).toLocaleString() : "待核验"}</strong></div><div><span>已返回关联成分</span><strong>{data.summary.componentCount.toLocaleString()}</strong></div></div>
      <div className="download-panel"><button type="button" disabled={!strictRows.length} onClick={() => csvDownload("strict-intersection.csv", ["当前返回结果实体 ID 交集靶点", "相关成分", "对应通路", "中药证据", "疾病证据", "来源版本"], strictRows.map((row) => [row.target, row.components.join("; "), row.pathways.join("; "), row.herbEvidenceCount, row.diseaseEvidenceCount, row.sources.map((source) => `${source.sourceSlug}:${source.sourceVersion}`).join("; ")]))}><Table2 size={15} />导出当前结果中的实体 ID 交集表</button></div>
      <NetworkResultDownloads result={data} />
      {(data.limits.targetsTruncated || data.limits.linksTruncated) && <p className="notice-warning">本次结果达到接口上限，展示和导出均只包含已返回的记录；请缩小检索范围。</p>}
      <RAnalysisGallery taskId={data.taskId} />
      <Link className="btn btn-secondary" to="/network-pharmacology" state={{ herb: data.summary.herb, disease: data.summary.disease }}>继续网络药理分析</Link>
    </div>
    {strictRows.length ? <PaginatedTable rows={strictRows} label="当前返回结果中的实体 ID 交集靶点" headers={["当前结果交集靶点", "相关成分", "对应通路", "中药证据", "疾病证据", "来源"]} rowKey={(row, index) => `${row.normalizedTarget}-${index}`} renderCells={(row) => <><td>{row.target}</td><td>{row.components.join("、") || "—"}</td><td>{row.pathways.join("、") || "待富集"}</td><td>{row.herbEvidenceCount}</td><td>{row.diseaseEvidenceCount}</td><td>{row.sources.map((source) => `${source.sourceSlug}:${source.sourceVersion}`).join("；")}</td></>} /> : <div className="empty-state">{data.targetIdentity?.entityIdComparison?.intersectionCount ? `当前返回结果子集未包含完整关系集中的交集行；完整交集 ${data.targetIdentity.entityIdComparison.intersectionCount} 项见上方“同一实体 ID 的完整交集”。` : state.message}</div>}
  </>;
}

function CatalogEvidence({ data }: { data: EntityNeighborhood }) {
  return <>
    <CatalogRVisualization query={{ queryType: "entity", entityId: data.entity.id, expectedSha256: data.evidenceSha256 }} />
    <article className="knowledge-entity-detail"><div className="case-list-heading"><div><p className="section-help">{entityTypeLabel[data.entity.entity_type] ?? data.entity.entity_type}</p><h3 className="section-title-sm">{data.entity.label}</h3></div><button className="btn btn-secondary" type="button" onClick={() => jsonDownload(`${data.entity.stable_id.replace(/[^a-zA-Z0-9_-]+/g, "_")}-evidence.json`, data)}><Download size={15} />导出 JSON</button></div><dl className="dataset-provenance"><div><dt>稳定标识</dt><dd>{data.entity.stable_id}</dd></div><div><dt>物种</dt><dd>{data.entity.organism || "未指定"}</dd></div><div><dt>实体来源</dt><dd>{data.entity.source_slug ?? "未登记"}</dd></div><div><dt>来源版本</dt><dd>{data.entity.source_version ?? "未登记"}</dd></div></dl></article>
    {data.compoundProperties && <section className="case-form-fields"><h4>化合物属性 · {data.compoundProperties.sourceCompoundId}</h4><p className="section-help">{data.compoundProperties.note}</p><div className="table-scroll"><table className="data-table" aria-label="化合物来源属性"><thead><tr><th>属性</th><th>来源值</th><th>状态</th><th>原始记录号</th></tr></thead><tbody>{Object.entries(data.compoundProperties.values).map(([field, value]) => <tr key={field}><td>{({ ob: "OB（%）", mw: "分子量（Da）", alogp: "AlogP", caco2: "Caco-2", bbb: "BBB", halflife: "半衰期", hdon: "氢键供体", hacc: "氢键受体", dl: "DL", FASA: "FASA" } as Record<string, string>)[field] ?? field}</td><td>{value ?? "—"}</td><td>{data.compoundProperties!.conflicts.includes(field) ? "属性冲突，待核验" : value === null ? "来源缺失" : "来源记录值"}</td><td>{data.compoundProperties!.fieldSourceRecords[field] ?? "—"}</td></tr>)}</tbody></table></div><details><summary>属性来源版本</summary><span style={{ overflowWrap: "anywhere" }}>{data.compoundProperties.source} · {data.compoundProperties.sourceVersion}</span></details></section>}
    <section className="knowledge-evidence-list"><div className="case-list-heading"><h3 className="section-title-sm">关系证据</h3><span>{data.relations.length}{data.truncated ? "+" : ""} 条</span></div>{!data.relations.length ? <div className="empty-state"><strong>当前实体没有可展示的关系记录</strong><p>实体已存在于目录中，但可能尚未导入关联证据。</p></div> : data.relations.map((relation) => <article className="knowledge-evidence-card" key={relation.id}><p className="knowledge-evidence-edge"><strong>{relation.subject_label}</strong><span>{relation.relation_type}</span><strong>{relation.object_label}</strong></p><p className="knowledge-evidence-source">{relation.source_slug} · {relation.source_version} · {relation.evidence_type}{relation.organism ? ` · ${relation.organism}` : ""}{relation.score ? ` · 分值 ${relation.score}` : ""}</p>{relation.evidence_text && <p className="knowledge-evidence-text">{relation.evidence_text}</p>}</article>)}{data.truncated && <p className="notice-warning">关系数超过单次展示上限，当前显示前 200 条，请进一步缩小数据源或联系管理员导出。</p>}</section>
  </>;
}
