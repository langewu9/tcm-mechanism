import { Download, FileJson, Table2 } from "lucide-react";
import type { DiseaseEvidenceSearch } from "../api/catalog";
import { downloadText, encodeCsv } from "../utils/downloads";
import { PaginatedTable } from "./PaginatedTable";

const jsonDownload = (data: DiseaseEvidenceSearch) => downloadText(
  "disease-evidence-result.json",
  JSON.stringify(data, null, 2),
  "application/json;charset=utf-8",
);

const displayValue = (value: string | null | undefined, fallback = "—") => value?.trim() ? value : fallback;

export function DiseaseEvidenceResults({ data }: { data: DiseaseEvidenceSearch }) {
  const entities = [
    ...data.matches.map((entity) => ({ kind: "疾病", entity })),
    ...data.herbs.map((entity) => ({ kind: "中药", entity })),
    ...data.targets.map((entity) => ({ kind: "靶点", entity })),
  ];

  function downloadCsv(filename: string, headers: string[], rows: Array<Array<string | number | null>>) {
    downloadText(filename, encodeCsv(headers, rows), "text/csv;charset=utf-8");
  }

  return <>
    <div className="panel-header">
      <div>
        <h3 className="section-title-sm">疾病关联证据</h3>
        <p className="section-help">检索词：{data.query} · 匹配到 {data.counts.diseases} 个疾病实体</p>
      </div>
    </div>
    <div className="case-form-fields">
      <div className="np-metrics">
        <div><span>匹配疾病</span><strong>{data.counts.diseases}</strong></div>
        <div><span>关联中药</span><strong>{data.counts.herbs}</strong></div>
        <div><span>关联靶点</span><strong>{data.counts.targets}</strong></div>
        <div><span>关联记录</span><strong>{data.counts.links}</strong></div>
      </div>

      {data.expandedQueries.length > 0 && <p className="notice-info">
        疾病别名表 {data.aliasSource} @ {data.aliasSourceCommit} 展开的检索词：{data.expandedQueries.join("、")}。别名只用于扩展检索，不代表术语等价，也不是药理证据。
      </p>}
      {data.ambiguous && <p className="notice-warning">检索词命中多个疾病实体，可能包含不同疾病或同名记录。下表分别保留数据库 ID、稳定标识和来源，不自动合并；若名称相同，可按 ID 区分。</p>}
      {data.matches.length === 0 ? <div className="empty-state">
        <strong>没有匹配的疾病实体</strong>
        <p>当前启用来源中没有找到该名称对应的疾病记录。</p>
      </div> : data.links.length === 0 && data.relations.length === 0 ? <div className="empty-state">
        <strong>疾病实体已找到，但没有返回关联证据</strong>
        <p>这表示当前启用来源没有可展示的疾病关联记录，不代表存在未展示的中药或靶点关系。</p>
      </div> : null}

      {data.truncated && <p className="notice-warning">
        返回结果已达到接口展示限制（最多 {data.limits.maxMatches} 个疾病匹配、{data.limits.maxRelations} 条关系）。页面中的数量和下方导出只包含本次已返回范围，不代表全库总数。
      </p>}

      <div className="download-panel">
        <button type="button" disabled={!data.links.length} onClick={() => downloadCsv(
          "disease-evidence-links.csv",
          ["疾病", "中药", "靶点", "关系类型", "来源库", "来源版本", "原始记录号"],
          data.links.map((row) => [row.disease, row.herb, row.target, row.relationType, row.sourceSlug, row.sourceVersion, row.sourceRecordId]),
        )}><Table2 size={15} />导出关联 CSV</button>
        <button type="button" disabled={!data.relations.length} onClick={() => downloadCsv(
          "disease-evidence-relations.csv",
          ["主体", "主体类型", "客体", "客体类型", "关系类型", "证据类型", "来源库", "来源版本", "原始记录号", "分值"],
          data.relations.map((row) => [row.subject, row.subjectType, row.object, row.objectType, row.relationType, row.evidenceType, row.sourceSlug, row.sourceVersion, row.sourceRecordId, row.score]),
        )}><Download size={15} />导出关系来源 CSV</button>
        <button type="button" disabled={!entities.length} onClick={() => downloadCsv(
          "disease-evidence-entities.csv",
          ["实体类型", "数据库 ID", "稳定标识", "名称", "来源库", "来源版本"],
          entities.map(({ kind, entity }) => [kind, entity.id, entity.stableId, entity.label, entity.sourceSlug, entity.sourceVersion]),
        )}><Table2 size={15} />导出实体来源 CSV</button>
        <button type="button" onClick={() => jsonDownload(data)}><FileJson size={15} />导出完整 JSON</button>
      </div>
      <p className="section-help">CSV 使用本次接口返回的数据，并对可能触发公式的单元格做转义。JSON 保留本次完整响应。</p>
    </div>

    {data.matches.length > 0 && <PaginatedTable
      rows={data.matches}
      label="匹配疾病实体"
      headers={["名称", "数据库 ID", "稳定标识", "来源库", "来源版本"]}
      rowKey={(row, index) => `${row.id}-${index}`}
      renderCells={(row) => <><td>{displayValue(row.label)}</td><td>{row.id}</td><td>{displayValue(row.stableId)}</td><td>{displayValue(row.sourceSlug, "未登记")}</td><td>{displayValue(row.sourceVersion, "未登记")}</td></>}
    />}

    {data.links.length > 0 && <PaginatedTable
      rows={data.links}
      label="疾病中药靶点关联"
      headers={["疾病", "中药", "靶点", "关系", "来源库", "来源版本", "原始记录号"]}
      rowKey={(row, index) => `${row.sourceSlug}-${row.sourceVersion}-${row.sourceRecordId}-${index}`}
      renderCells={(row) => <><td>{displayValue(row.disease)}</td><td>{displayValue(row.herb)}</td><td>{displayValue(row.target)}</td><td>{displayValue(row.relationType)}</td><td>{displayValue(row.sourceSlug, "未登记")}</td><td>{displayValue(row.sourceVersion, "未登记")}</td><td>{displayValue(row.sourceRecordId, "未登记")}</td></>}
    />}

    {(data.herbs.length > 0 || data.targets.length > 0) && <PaginatedTable
      rows={[
        ...data.herbs.map((entity) => ({ kind: "中药", entity })),
        ...data.targets.map((entity) => ({ kind: "靶点", entity })),
      ]}
      label="关联中药与靶点实体"
      headers={["类型", "名称", "数据库 ID", "稳定标识", "来源库", "来源版本"]}
      rowKey={(row, index) => `${row.kind}-${row.entity.id}-${index}`}
      renderCells={(row) => <><td>{row.kind}</td><td>{displayValue(row.entity.label)}</td><td>{row.entity.id}</td><td>{displayValue(row.entity.stableId)}</td><td>{displayValue(row.entity.sourceSlug, "未登记")}</td><td>{displayValue(row.entity.sourceVersion, "未登记")}</td></>}
    />}

    {data.relations.length > 0 && <PaginatedTable
      rows={data.relations}
      label="疾病关系来源记录"
      headers={["主体", "关系", "客体", "证据类型", "来源库", "来源版本", "原始记录号", "分值"]}
      rowKey={(row, index) => `${row.sourceSlug}-${row.sourceVersion}-${row.sourceRecordId}-${index}`}
      renderCells={(row) => <><td>{displayValue(row.subject)}</td><td>{displayValue(row.relationType)}</td><td>{displayValue(row.object)}</td><td>{displayValue(row.evidenceType)}</td><td>{displayValue(row.sourceSlug, "未登记")}</td><td>{displayValue(row.sourceVersion, "未登记")}</td><td>{displayValue(row.sourceRecordId, "未登记")}</td><td>{row.score ?? "—"}</td></>}
    />}

    <details className="raw-details">
      <summary>查看本次完整原始响应</summary>
      <pre style={{ maxHeight: "32rem", overflow: "auto", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(data, null, 2)}</pre>
    </details>
  </>;
}
