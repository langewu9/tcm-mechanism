import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { BookOpen, Search } from "lucide-react";
import { SubviewTabs } from "../components/SubviewTabs";
import { ApiError } from "../api/client";
import { getCaseCorpus, getReferenceCase, type CaseCategory, type CaseCorpusPage, type ReferenceCase } from "../api/caseCorpus";
import { CasesPage } from "./CasesPage";
import "../styles/case-library.css";

const message = (error: unknown) => error instanceof ApiError ? error.message : "医案读取失败，请重试。";

export function CaseLibraryPage() {
  const [view, setView] = useState("reference");
  return <section className="case-library-page"><div className="page-heading"><div className="page-heading-copy"><h1 className="page-title">医案库</h1></div><Link to="/assistant" className="btn btn-secondary">医案检索与问答</Link></div>
    <SubviewTabs value={view} onChange={setView} label="医案工作区" keepMounted={false} views={[
      { key: "reference", label: "参考医案库", content: <ReferenceCaseLibrary /> },
      { key: "personal", label: "我的医案", content: <CasesPage embedded /> },
    ]} />
  </section>;
}

function ReferenceCaseLibrary() {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState({ q: "", category: "" as CaseCategory, page: 1 });
  const [data, setData] = useState<CaseCorpusPage | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<ReferenceCase | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [detailRetry, setDetailRetry] = useState(0);
  const sequence = useRef(0);
  const detailPane = useRef<HTMLElement>(null);
  const resultsPane = useRef<HTMLElement>(null);

  useEffect(() => {
    const current = ++sequence.current; let active = true;
    resultsPane.current?.scrollTo({ top: 0 });
    setLoading(true); setError(null); setDetail(null); setSelected(null);
    getCaseCorpus(query.q, query.category, query.page).then(result => {
      if (!active || current !== sequence.current) return;
      setData(result); setSelected(result.results[0]?.id ?? null);
    }).catch(cause => { if (active && current === sequence.current) { setError(message(cause)); setData(null); } })
      .finally(() => { if (active && current === sequence.current) setLoading(false); });
    return () => { active = false; };
  }, [query, retry]);

  useEffect(() => {
    detailPane.current?.scrollTo({ top: 0 });
    if (selected === null) { setDetail(null); setDetailLoading(false); return; }
    let active = true; setDetailLoading(true); setDetailError(null); setDetail(null);
    getReferenceCase(selected).then(result => { if (active) setDetail(result); })
      .catch(cause => { if (active) setDetailError(message(cause)); })
      .finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [selected, detailRetry]);

  function submit(event: FormEvent) { event.preventDefault(); setQuery(previous => ({ ...previous, q: input.trim(), page: 1 })); }

  return <div className="case-library">
    {data?.summary.available && <div className="case-library-categories" aria-label="医案分类">
      <button className="btn btn-secondary" type="button" aria-pressed={!query.category} onClick={() => setQuery(previous => ({ ...previous, category: "", page: 1 }))}>全部 · {data.summary.recordCount.toLocaleString("zh-CN")}</button>
      {data.summary.categories.map(category => <button type="button" className="btn btn-secondary" aria-pressed={query.category === category.key} key={category.key} onClick={() => setQuery(previous => ({ ...previous, category: category.key, page: 1 }))}>{category.label} · {category.count}</button>)}
    </div>}
    <div className="workspace-split workspace-split--balanced case-library-workspace">
      <section ref={resultsPane} className="panel case-library-results" aria-label="参考医案检索" aria-busy={loading}>
        <div className="panel-header"><div><h2 className="section-title-sm">参考医案</h2><p className="section-help">按症状、证型、方剂或原表编号检索。</p></div></div>
        <form className="case-library-search" onSubmit={submit}><label className="form-label" htmlFor="reference-case-search">关键词<input id="reference-case-search" className="field" value={input} maxLength={160} onChange={event => setInput(event.target.value)} placeholder="例如：咳嗽、偏瘫、胃脘痛、咽干" /></label><button className="btn btn-primary" disabled={loading}><Search size={17} />检索</button></form>
        {loading ? <div className="workspace-loading" role="status">正在读取医案…</div> : error ? <div className="empty-state" role="alert"><p>{error}</p><button className="btn btn-secondary" onClick={() => setRetry(value => value + 1)}>重试</button></div> : !data?.summary.available ? <div className="empty-state"><strong>参考医案库暂不可用</strong><p>请联系管理员检查语料库连接。</p></div> : !data.results.length ? <div className="empty-state"><strong>没有匹配的参考医案</strong><p>可以更换关键词或分类。</p></div> : <>
          <div className="table-scroll"><table className="data-table case-library-table"><thead><tr><th>医案</th><th>类别</th><th>查看</th></tr></thead><tbody>{data.results.map(record => <tr key={record.id} data-selected={selected === record.id}><td><strong>{record.title}</strong><p>{record.originalExcerpt || Object.values(record.clinicalFeatures).filter(Boolean).slice(0, 2).join("；")}</p></td><td>{record.categoryLabel}</td><td><button type="button" className="btn btn-secondary" aria-pressed={selected === record.id} onClick={() => setSelected(record.id)} aria-label={`查看${record.title}`}>查看</button></td></tr>)}</tbody></table></div>
          <nav className="table-pager" aria-label="参考医案分页"><span>共 {data.count.toLocaleString("zh-CN")} 条 · 第 {data.page} / {Math.max(1, Math.ceil(data.count / data.pageSize))} 页</span><div><button disabled={data.page <= 1 || loading} onClick={() => setQuery(previous => ({ ...previous, page: previous.page - 1 }))}>上一页</button><button disabled={data.page * data.pageSize >= data.count || loading} onClick={() => setQuery(previous => ({ ...previous, page: previous.page + 1 }))}>下一页</button></div></nav>
        </>}
      </section>
      <section ref={detailPane} className="panel case-library-detail" aria-label="参考医案详情" aria-busy={detailLoading}>
        {detailLoading ? <div className="workspace-loading" role="status">正在读取详情…</div> : detailError ? <div className="empty-state" role="alert"><p>{detailError}</p><button className="btn btn-secondary" onClick={() => setDetailRetry(value => value + 1)}>重试</button></div> : detail ? <>
          <div className="panel-header"><div><h2 className="section-title-sm">{detail.title}</h2><p className="section-help">{detail.categoryLabel} · {detail.recordStatus}</p></div></div>
          <div className="case-library-detail-body"><Link className="btn btn-primary" to="/assistant" state={{ draftQuestion: `请整理这份${detail.categoryLabel}参考医案的症状、证型与方药记录，并注明原文依据和不确定性。`, referenceCases: [{ id: detail.id, title: detail.title }] }}>用于科研助手</Link>
            <dl className="case-reference-fields">{Object.entries(detail.clinicalFeatures).map(([field, value]) => <div key={field} className={value.length > 100 ? "case-reference-wide" : undefined}><dt>{field}</dt><dd>{value}</dd></div>)}</dl>
            <details className="case-reference-original"><summary>原始医案文本</summary><p className="case-reference-text">{detail.originalText || "该工作表未提供原始正文，以上为原表结构化字段。"}</p></details>
            <details className="case-reference-original"><summary>出处与来源版本</summary><dl className="case-reference-fields"><div><dt>出处</dt><dd>{detail.source || "原表未提供出处"}</dd></div><div><dt>来源医生</dt><dd>{detail.sourceDoctor || "未登记"}</dd></div><div><dt>文献标识 / 链接</dt><dd>{detail.sourceLink || "未登记"}</dd></div><div><dt>工作簿</dt><dd>{detail.workbookName}</dd></div><div><dt>工作表 / 编号</dt><dd>{detail.sourceSheet} / {detail.caseId}</dd></div><div><dt>版本</dt><dd>{detail.sourceVersion}</dd></div><div><dt>记录校验值</dt><dd><code>{detail.contentSha256}</code></dd></div></dl></details>
          </div>
        </> : <div className="empty-state"><BookOpen size={26} /><strong>选择一份医案查看详情</strong></div>}
      </section>
    </div>
  </div>;
}
