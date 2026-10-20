import { useState, type FormEvent } from "react";
import { Download, FileJson, Search } from "lucide-react";
import { ApiError } from "../api/client";
import { searchReactomeCatalog, type ReactomeCatalogResult } from "../api/catalog";
import { downloadText, encodeCsv } from "../utils/downloads";
import { PaginatedTable } from "./PaginatedTable";

export function reactomeCatalogueCsv(data: ReactomeCatalogResult) {
  return encodeCsv(["检索词", "稳定 ID", "通路名称", "物种", "本地靶点注释", "注释来源版本", "历史富集记录", "最近同步", "来源版本", "目录SHA-256", "Reactome", "结果截断"], data.items.map((row) => [
    data.query, row.stableId, row.name, row.species, row.targetAnnotations,
    row.annotationSources.map((source) => `${source.sourceSlug}:${source.sourceVersion}`).join("; "),
    row.enrichmentRecords ?? "未迁入", row.lastSyncedAt, row.sourceVersion, row.checksumSha256, row.sourceUrl, data.truncated,
  ]));
}

export function ReactomePathwayLookup() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<ReactomeCatalogResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError(null);
    try { setResult(await searchReactomeCatalog(query.trim())); }
    catch (cause) { setError(cause instanceof ApiError ? cause.message : "请求未完成，请稍后重试。"); }
    finally { setBusy(false); }
  }
  return <section className="panel chembl-panel reactome-panel" aria-label="Reactome 人类通路目录检索">
    <div className="panel-header"><div><p className="page-kicker">Local Reactome catalogue</p><h2 className="section-title-sm">Reactome 人类通路目录</h2><p className="section-help">按名称或 R-HSA 稳定 ID 检索已同步的本地目录；输入为空时展示按名称排序的前 100 项。</p></div></div>
    <form className="chembl-search-form" onSubmit={(event) => void submit(event)}>
      <label className="form-label" htmlFor="reactome-query">通路名称或稳定 ID<input id="reactome-query" className="field" maxLength={160} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如 Interleukin 或 R-HSA-449147" /></label>
      <button className="btn btn-primary" type="submit" disabled={busy}><Search size={16} />{busy ? "正在检索…" : "检索本地目录"}</button>
    </form>
    {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
    {result && <section className="chembl-results" aria-live="polite">
      <div className="case-list-heading"><h3 className="section-title-sm">通路检索结果</h3><span className={`status-badge ${result.catalogTotal ? "status-success" : "status-pending"}`}>{result.catalogTotal ? "已导入本地目录" : "目录待同步"}</span></div>
      <p className="section-help">人类通路目录 {result.catalogTotal} 条，本次匹配 {result.matchedTotal} 条，显示 {result.items.length} 条；查询：{result.query || "全部人类通路"}。</p>
      {result.warnings.map((warning) => <p className="notice-info" key={warning}>{warning}</p>)}
      {result.truncated && <p className="notice-warning">匹配超过 {result.maxItems} 条，页面和 CSV/JSON 均只包含前 {result.maxItems} 条。请缩小查询范围。</p>}
      <div className="source-record-actions"><button className="btn btn-secondary" type="button" disabled={!result.items.length} onClick={() => downloadText("reactome-pathways.csv", reactomeCatalogueCsv(result), "text/csv;charset=utf-8")}><Download size={15} />导出通路目录 CSV</button><button className="btn btn-secondary" type="button" onClick={() => downloadText("reactome-pathways.json", JSON.stringify(result, null, 2), "application/json;charset=utf-8")}><FileJson size={15} />导出结果 JSON</button></div>
      {result.items.length ? <PaginatedTable rows={result.items} label="Reactome 人类通路" headers={["稳定 ID", "通路名称", "物种", "本地靶点注释", "历史富集记录", "来源版本", "最近同步", "Reactome"]} rowKey={(row) => row.stableId} renderCells={(row) => <><td>{row.stableId}</td><td>{row.name}</td><td>{row.species}</td><td>{row.targetAnnotations}{row.annotationSources.length > 0 && <small style={{ display: "block" }}>{row.annotationSources.map((source) => `${source.sourceSlug}:${source.sourceVersion}`).join("；")}</small>}</td><td>{row.enrichmentRecords ?? "未迁入"}</td><td>{row.sourceVersion}</td><td>{new Date(row.lastSyncedAt).toLocaleDateString("zh-CN")}</td><td><a href={row.sourceUrl} target="_blank" rel="noreferrer">打开</a></td></>} /> : <div className="empty-state"><strong>{result.catalogTotal ? "未找到匹配通路" : "尚无启用的 Reactome 人类目录"}</strong><p>{result.catalogTotal ? "请换用通路名称或 R-HSA 稳定 ID。" : "平台管理员可在数据源同步页预览并应用 Reactome 目录。"}</p></div>}
      <details><summary>本次目录来源与校验值</summary>{result.sources.map((source) => <p className="section-help" style={{ overflowWrap: "anywhere" }} key={`${source.sourceSlug}-${source.sourceVersion}`}>{source.sourceSlug} · {source.sourceVersion} · SHA-256 {source.checksumSha256 || "尚未登记"}</p>)}</details>
    </section>}
  </section>;
}
