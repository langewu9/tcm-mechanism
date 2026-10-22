import { SnapshotEvidence } from "./SnapshotEvidence";
import { snapshotDownloadUrl, type EvidenceSnapshot } from "../api/complete-evidence";

export type ScientistReportResult = {
  analysisKind: "scientist_hypothesis";
  paper_title: string;
  paper_abstract: string;
  problem_statement: string;
  input: { question: string; disease: string; formula: string[]; focus: string };
  rationale: string[];
  methods: Array<{ step: string; status: string; detail: string }>;
  results: { disease_target_count: number; formula_target_count: number; intersection_count: number;
    direct_association_count: number; component_count: number; top_intersection_targets: string[];
    intersection_display_truncated?: boolean };
  evidence: { herb_summaries: Array<{ herb: string; stableId: string; sourceSlug: string; sourceVersion: string;
    component_count: number; target_count: number }> };
  references: Array<{ sourceReleaseId: number; sourceSlug: string; sourceVersion: string; sourceChecksumSha256: string }>;
  uncertainties: string[];
  snapshot: EvidenceSnapshot;
};

export function ScientistReport({ taskId, result }: { taskId: number; result: ScientistReportResult }) {
  return <>
    <p className="notice-info">本地证据整理与研究计划模板；没有调用模型、外部检索或执行实验。</p>
    <h3 className="section-title-sm">{result.paper_title}</h3>
    <p className="section-help">研究重点：{result.input.focus}。方药组成：{result.input.formula.join("、")}。</p>
    <p className="assistant-answer">{result.paper_abstract}</p>
    <p>{result.problem_statement}</p>
    <ul className="proteomics-pathways">{result.rationale.map((item, index) => <li key={index}>{item}</li>)}</ul>
    <div className="table-scroll"><table className="data-table" aria-label="方药逐来源汇总">
      <thead><tr><th>中药</th><th>来源版本</th><th>来源成分数</th><th>来源靶点数</th></tr></thead>
      <tbody>{result.evidence.herb_summaries.map(item => <tr key={item.stableId}><td>{item.herb}</td><td>{item.sourceSlug} / {item.sourceVersion}</td><td>{item.component_count}</td><td>{item.target_count}</td></tr>)}</tbody>
    </table></div>
    <h3 className="section-title-sm">同一来源实体身份的严格交集：{result.results.intersection_count}</h3>
    <p>{result.results.top_intersection_targets.length ? result.results.top_intersection_targets.join("、") : "没有严格交集记录；未使用其他方药靶点回填。"}</p>
    {result.results.intersection_display_truncated && <p className="notice-info">此处展示前 30 条严格交集，完整记录保留在下方证据快照的候选靶点表中。</p>}
    <h3 className="section-title-sm">已执行与待接步骤</h3>
    <ul className="proteomics-pathways">{result.methods.map(item => <li key={item.step}><strong>{item.step} · {item.status === "completed" ? "已执行" : item.status === "pending" ? "待核实" : "未执行"}</strong><span>{item.detail}</span></li>)}</ul>
    <h3 className="section-title-sm">实际来源 · {result.references.length} 个版本</h3>
    {result.references.length ? <ul className="proteomics-pathways">{result.references.map(item => <li key={item.sourceReleaseId}><strong>{item.sourceSlug} / {item.sourceVersion}</strong><span style={{ overflowWrap: "anywhere" }}>SHA-256：{item.sourceChecksumSha256 || "来源未登记校验值"}</span></li>)}</ul> : <p className="section-help">本次没有可用来源版本，不生成论文引用。</p>}
    {result.uncertainties.map((item, index) => <p className="notice-info" key={index}>{item}</p>)}
    <a className="btn btn-secondary" href={snapshotDownloadUrl(taskId, "reportSections", "csv")} download>下载报告章节 CSV</a>
    <SnapshotEvidence taskId={taskId} snapshot={result.snapshot} />
  </>;
}
