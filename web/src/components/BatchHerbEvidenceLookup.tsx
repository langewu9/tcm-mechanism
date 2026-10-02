import { useState, type FormEvent } from "react";
import { Search } from "lucide-react";
import { ApiError } from "../api/client";
import { searchHerbComponentEvidence, type HerbEvidenceSearch } from "../api/catalog";

function splitNames(value: string) {
  return [...new Set(value.split(/[,，、;；|/\n\r]+/).map((item) => item.trim()).filter(Boolean))];
}

function showNames(names: Array<{ label: string }>) {
  return names.length ? names.map((item) => item.label).join("、") : "无已导入关联";
}

export function BatchHerbEvidenceLookup() {
  const [queryType, setQueryType] = useState<HerbEvidenceSearch["queryType"]>("herb");
  const [queryText, setQueryText] = useState("");
  const [result, setResult] = useState<HerbEvidenceSearch | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const queries = splitNames(queryText);
    if (!queries.length) {
      setError("请输入至少一个名称。");
      return;
    }
    if (queries.length > 12) {
      setError("每次最多查询 12 个名称。");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await searchHerbComponentEvidence(queryType, queries));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "请求未完成，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  return <section className="panel batch-evidence-panel">
    <div className="panel-header"><div><p className="page-kicker">Evidence lookup · adapted from main</p><h2 className="section-title-sm">批量中药 / 成分关系查询</h2><p className="section-help">借鉴 main 的中药、成分关系检索，改为查询当前已导入且启用的版本化知识目录；只做精确名称匹配，不会连接旧电脑的 Excel 或 SQLite 文件。</p></div><Search size={20} /></div>
    <form className="batch-evidence-form" onSubmit={(event) => void submit(event)}>
      <label className="form-label" htmlFor="batch-evidence-type">检索对象<select className="field" id="batch-evidence-type" value={queryType} onChange={(event) => { setQueryType(event.target.value as HerbEvidenceSearch["queryType"]); setResult(null); }}><option value="herb">中药 → 成分 → 靶点</option><option value="compound">成分 → 来源中药 / 靶点</option></select></label>
      <label className="form-label" htmlFor="batch-evidence-names">名称列表<textarea className="field" id="batch-evidence-names" value={queryText} maxLength={1800} onChange={(event) => setQueryText(event.target.value)} placeholder={queryType === "herb" ? "例如：黄芩、丹参、麦冬" : "例如：黄芩苷、丹参酮 IIA"} required /></label>
      <div className="case-form-footer"><p>支持逗号、分号、顿号、竖线或换行分隔；每次最多 12 项。每条关系展示来源版本和原始记录号。</p><button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "正在查询…" : "查询本地证据"}</button></div>
    </form>
    {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
    {result && <div className="batch-evidence-results" aria-live="polite">{result.results.map((item, index) => <article className="batch-evidence-item" key={`${item.query}-${index}`}>
      <div className="case-list-heading"><div><h3 className="section-title-sm">{item.query}</h3><p className="section-help">{item.matches.length ? `精确匹配 ${item.matches.length} 条目录实体` : "没有匹配的启用目录实体"}</p></div><span>{item.relations.length} 条关系证据</span></div>
      {item.ambiguous && <p className="notice-warning">同名实体对应多个稳定标识；结果并列展示，不会自动合并，请核对目录来源。</p>}
      {item.matches.length > 0 && <p className="knowledge-evidence-source">匹配实体：{item.matches.map((entity) => `${entity.label} [${entity.stableId}] · ${entity.sourceSlug ?? "未登记来源"} ${entity.sourceVersion ?? ""}`).join("；")}</p>}
      <div className="batch-evidence-summary"><p><strong>中药：</strong>{showNames(item.herbs)}</p><p><strong>成分：</strong>{showNames(item.compounds)}</p><p><strong>靶点：</strong>{showNames(item.targets)}</p></div>
      {item.relations.length > 0 && <ul className="proteomics-pathways batch-evidence-relations">{item.relations.slice(0, 30).map((relation, relationIndex) => <li key={`${relation.sourceSlug}-${relation.sourceRecordId}-${relationIndex}`}><strong>{relation.subject} —{relation.relationType}→ {relation.object}</strong><span>{relation.sourceSlug} · {relation.sourceVersion} · {relation.evidenceType} · 记录 {relation.sourceRecordId}{relation.score === null ? "" : ` · 分值 ${relation.score}`}</span></li>)}</ul>}
      {(item.truncated || item.relations.length > 30) && <p className="notice-warning">为保持页面可读，结果有截断：接口最多返回每类关系 1,200 条，页面最多展示 30 条。可拆分查询或进入单实体详情查看来源证据。</p>}
    </article>)}</div>}
  </section>;
}
