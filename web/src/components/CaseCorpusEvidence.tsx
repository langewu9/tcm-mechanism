import type { ReferenceCase } from "../api/caseCorpus";
import "../styles/case-library.css";

export function CaseCorpusEvidence({ records, citations = [] }: { records: ReferenceCase[]; citations?: string[] }) {
  return <div className="case-corpus-evidence">{records.map(record => <details className="case-reference-evidence" key={record.refId}>
    <summary>{citations.includes(record.refId) && <span className="status-badge status-success">已引用</span>}{record.title}</summary>
    <p className="section-help">{record.recordStatus || "未标注人工核校状态"}</p>
    <dl className="case-reference-fields">{Object.entries(record.clinicalFeatures ?? {}).map(([field, value]) => <div key={field} className={value.length > 100 ? "case-reference-wide" : undefined}><dt>{field}</dt><dd>{value}</dd></div>)}</dl>
    {record.originalExcerpt && <div><h4 className="section-title-sm">原案摘录</h4><p className="case-reference-text">{record.originalExcerpt}</p></div>}
    <dl className="case-reference-fields"><div><dt>出处</dt><dd>{record.source || "原表未提供出处"}</dd></div><div><dt>来源医生</dt><dd>{record.sourceDoctor || "未登记"}</dd></div>
      <div><dt>原表编号</dt><dd>{record.caseId}</dd></div><div><dt>工作表</dt><dd>{record.sourceSheet}</dd></div>
      <div><dt>版本</dt><dd>{record.sourceVersion}</dd></div>{record.sourceLink && <div><dt>文献标识 / 链接</dt><dd>{record.sourceLink}</dd></div>}</dl>
  </details>)}</div>;
}
