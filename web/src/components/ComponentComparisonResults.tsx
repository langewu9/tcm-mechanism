import { Download, FileJson, Table2 } from "lucide-react";
import type { ComponentCompareRow, ComponentComparison } from "../api/chembl";
import { downloadText, encodeCsv } from "../utils/downloads";
import { PaginatedTable } from "./PaginatedTable";
import { CatalogRVisualization } from "./CatalogRVisualization";

const count = (value: number) => value.toLocaleString("zh-CN");
const display = (value?: string) => value || "—";

// Set illustration only: circle area does not encode count.
export function ComponentComparisonVenn({ detectedCount, referenceCount, matchedCount }: {
  detectedCount: number; referenceCount: number; matchedCount: number;
}) {
  const detectedOnly = Math.max(detectedCount - matchedCount, 0);
  const referenceOnly = Math.max(referenceCount - matchedCount, 0);
  return <svg viewBox="0 0 640 300" role="img" aria-label={`检测成分与参考列表韦恩图：仅检测 ${detectedOnly}，精确交集 ${matchedCount}，仅参考 ${referenceOnly}`} style={{ display: "block", width: "100%" }}>
    <rect width="640" height="300" rx="8" fill="rgba(255,250,241,0.62)" />
    <circle cx="262" cy="152" r="108" fill="#4E6D9C" fillOpacity="0.23" stroke="#4E6D9C" strokeWidth="3" />
    <circle cx="378" cy="152" r="108" fill="#B65A50" fillOpacity="0.22" stroke="#B65A50" strokeWidth="3" />
    <text x="220" y="62" textAnchor="middle" fill="#4E6D9C" fontSize="15" fontWeight="900">检测成分</text>
    <text x="420" y="62" textAnchor="middle" fill="#B65A50" fontSize="15" fontWeight="900">参考列表</text>
    <text x="220" y="150" textAnchor="middle" fill="#4E6D9C" fontSize="13" fontWeight="900">仅检测</text>
    <text x="220" y="180" textAnchor="middle" fill="#2b1711" fontSize="30" fontWeight="900">{count(detectedOnly)}</text>
    <text x="320" y="136" textAnchor="middle" fill="#7d1d04" fontSize="13" fontWeight="900">交集</text>
    <text x="320" y="174" textAnchor="middle" fill="#2b1711" fontSize="36" fontWeight="900">{count(matchedCount)}</text>
    <text x="420" y="150" textAnchor="middle" fill="#B65A50" fontSize="13" fontWeight="900">仅参考</text>
    <text x="420" y="180" textAnchor="middle" fill="#2b1711" fontSize="30" fontWeight="900">{count(referenceOnly)}</text>
    <text x="320" y="258" textAnchor="middle" fill="rgba(43,23,17,0.62)" fontSize="12">检测 {count(detectedCount)} 个，参考 {count(referenceCount)} 个</text>
  </svg>;
}

export function componentComparisonCsv(data: ComponentComparison, kind: "matches" | "all" | "normalized") {
  const provenance = [data.aliasSource, data.aliasSourceCommit];
  if (kind === "normalized") {
    return encodeCsv(["输入来源", "原始名称", "中文名", "英文/规范名", "拉丁/规范名", "同义名", "比对键", "别名表来源", "来源提交"],
      [...data.detected, ...data.reference].map((row) => [row.side === "detected" ? "检测成分" : "参考列表", row.input, row.chinese, row.english, row.latin, row.matchedTerms, row.normalizedKey, ...provenance]));
  }
  const rows = kind === "matches" ? data.exactMatches : data.rows;
  return encodeCsv(["分组", "检测输入", "参考输入", "原始名称", "中文名", "英文/规范名", "拉丁/规范名", "状态", "比对键", "别名表来源", "来源提交"], rows.map((row) => {
    const inputs = comparisonInputs(row);
    return [row.group ?? "交集", inputs.detected, inputs.reference, row.input, row.chinese, row.english, row.latin, row.status, row.normalizedKey, ...provenance];
  }));
}

function comparisonInputs(row: ComponentCompareRow) {
  return {
    detected: row.detectedInput ?? (row.group === "仅检测" ? row.input : ""),
    reference: row.referenceInput ?? (row.group === "仅参考" ? row.input : ""),
  };
}

export function ComponentComparisonResults({ data }: { data: ComponentComparison }) {
  const normalizedRows = [...data.detected, ...data.reference];
  const exportCsv = (kind: "matches" | "all" | "normalized") => downloadText(`component_compare_${kind}.csv`, componentComparisonCsv(data, kind), "text/csv;charset=utf-8");
  return <section className="chembl-results" aria-live="polite">
    <div className="case-list-heading"><div><h3 className="section-title-sm">名称对照结果</h3></div><button className="btn btn-secondary" type="button" onClick={() => downloadText("component_compare.json", JSON.stringify(data, null, 2), "application/json;charset=utf-8")}><FileJson size={14} />导出 JSON</button></div>
    <div className="chembl-comparison-counts"><div><strong>{data.counts.detected}</strong><span>检测项</span></div><div><strong>{data.counts.reference}</strong><span>参考项</span></div><div><strong>{data.counts.matched}</strong><span>精确交集</span></div><div><strong>{data.counts.detectedOnly}</strong><span>仅检测</span></div><div><strong>{data.counts.referenceOnly}</strong><span>仅参考</span></div><div><strong>{data.counts.matchRate}%</strong><span>参考列表命中率</span></div></div>
    <CatalogRVisualization query={{ queryType: "comparison", detected: data.detected.map(row => row.input).join("\n"), reference: data.reference.map(row => row.input).join("\n"), expectedSha256: data.evidenceSha256 }} />
    <details><summary>查看集合示意（圆面积不代表数量）</summary><div className="component-comparison-summary">
      <section className="figure-card"><div className="figure-heading"><span>Venn</span><div><h2>检测成分 ∩ 参考列表</h2><p>中英文和拉丁名称先规范化，再按比对键计算精确交集；圆形面积仅作示意。</p></div></div><ComponentComparisonVenn detectedCount={data.counts.detected} referenceCount={data.counts.reference} matchedCount={data.counts.matched} /></section>
      <div className="component-comparison-downloads"><p className="section-help">同家族候选 {data.counts.familyMatches} 项，规范化记录 {normalizedRows.length} 条。完整 CSV 包含所有分页记录及别名表出处；同家族候选单列于 JSON 和下方表格。</p>
        <button className="btn btn-secondary" type="button" disabled={!data.exactMatches.length} onClick={() => exportCsv("matches")}><Table2 size={15} />导出交集表</button>
        <button className="btn btn-secondary" type="button" disabled={!data.rows.length} onClick={() => exportCsv("all")}><Download size={15} />导出完整比对表</button>
        <button className="btn btn-secondary" type="button" disabled={!normalizedRows.length} onClick={() => exportCsv("normalized")}><Download size={15} />导出规范化清单</button>
      </div>
    </div></details>
    <h4 className="section-title-sm">规范化成分</h4>
    <PaginatedTable rows={normalizedRows} label="规范化成分" headers={["输入来源", "原始名称", "中文名", "英文/规范名", "拉丁/规范名", "同义名", "比对键"]} rowKey={(row, index) => `${row.side}-${row.normalizedKey}-${index}`} renderCells={(row) => <><td>{row.side === "detected" ? "检测成分" : "参考列表"}</td><td>{display(row.input)}</td><td>{display(row.chinese)}</td><td>{display(row.english)}</td><td>{display(row.latin)}</td><td>{display(row.matchedTerms)}</td><td>{display(row.normalizedKey)}</td></>} />
    <h4 className="section-title-sm">完整比对表</h4>
    <PaginatedTable rows={data.rows} label="成分比对" headers={["分组", "检测输入", "参考输入", "原始名称", "中文名", "英文/规范名", "拉丁/规范名", "状态"]} rowKey={(row, index) => `${row.group}-${row.normalizedKey}-${index}`} renderCells={(row) => { const inputs = comparisonInputs(row); return <><td>{display(row.group)}</td><td>{display(inputs.detected)}</td><td>{display(inputs.reference)}</td><td>{display(row.input)}</td><td>{display(row.chinese)}</td><td>{display(row.english)}</td><td>{display(row.latin)}</td><td>{display(row.status)}</td></>; }} />
    {data.familyMatches.length > 0 && <><p className="notice-warning">同家族候选不计入精确交集和命中率。</p><PaginatedTable rows={data.familyMatches} label="同家族候选" headers={["家族名称", "检测输入", "参考输入", "检测规范名", "参考规范名", "状态"]} rowKey={(row, index) => `${row.familyKey}-${index}`} renderCells={(row) => <><td>{display(row.familyName || row.familyKey)}</td><td>{display(row.detectedInput)}</td><td>{display(row.referenceInput)}</td><td>{display(row.detectedEnglish)}</td><td>{display(row.referenceEnglish)}</td><td>{display(row.status)}</td></>} /></>}
  </section>;
}
