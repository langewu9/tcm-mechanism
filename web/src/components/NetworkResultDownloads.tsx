import { Download, FileJson, Table2 } from "lucide-react";
import type { NetworkPharmacologyResult, NetworkRawTable } from "../api/network";
import { downloadText as download, encodeCsv as csv } from "../utils/downloads";

export function networkTargetsCsv(result: NetworkPharmacologyResult) {
  return csv([
    "taskId", "herbQuery", "diseaseQuery", "target", "normalizedTarget", "targetName", "genes", "matchType",
    "components", "herbs", "diseaseNames", "pathways", "herbEvidenceCount", "diseaseEvidenceCount", "directEvidenceCount",
    "sourceSlugs", "sourceVersions", "sourceRecordIds", "targetsTruncated",
  ], result.targets.map((target) => [
    result.taskId, result.summary.herb, result.summary.disease, target.target, target.normalizedTarget, target.targetName, target.genes, target.matchType,
    target.components.join("; "), target.herbs.join("; "), target.diseaseNames.join("; "), target.pathways.join("; "),
    target.herbEvidenceCount, target.diseaseEvidenceCount, target.directEvidenceCount,
    target.sources.map((source) => source.sourceSlug).join("; "), target.sources.map((source) => source.sourceVersion).join("; "),
    target.sources.map((source) => source.sourceRecordId).join("; "), result.limits.targetsTruncated ? "true" : "false",
  ]));
}

export function networkEvidenceCsv(result: NetworkPharmacologyResult) {
  return csv([
    "taskId", "herbQuery", "diseaseQuery", "target", "normalizedTarget", "matchType", "relationType",
    "sourceName", "sourceSlug", "sourceVersion", "sourceRecordId", "evidenceType", "score",
  ], result.targets.flatMap((target) => target.sources.map((source) => [
    result.taskId, result.summary.herb, result.summary.disease, target.target, target.normalizedTarget, target.matchType,
    source.relationType, source.source, source.sourceSlug, source.sourceVersion, source.sourceRecordId, source.evidenceType, source.score,
  ])));
}

function rawTableTruncated(result: NetworkPharmacologyResult, table: NetworkRawTable) {
  const limits = result.rawLimits;
  if (!limits) return false;
  const inputs = limits.inputRelationsTruncated;
  return limits.tablesTruncated[table] || (table === "herbLinks"
    ? inputs.formulaHerbs || inputs.herbCompounds || inputs.compoundTargets
    : inputs.diseaseTargets || (table === "directDiseaseHerbLinks" && inputs.formulaHerbs)) || false;
}

export function networkRawCsv(result: NetworkPharmacologyResult, table: NetworkRawTable) {
  const limits = result.rawLimits;
  if (!result.raw || !limits) return null;
  const rows = result.raw[table];
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  return csv([
    "taskId", "herbQuery", "diseaseQuery", "table", "formatVersion", "rowLimit", "truncated", ...columns,
  ], rows.map((row) => [
    result.taskId, result.summary.herb, result.summary.disease, table, limits.formatVersion,
    limits.rowLimit, rawTableTruncated(result, table), ...columns.map((key) => row[key]),
  ]));
}

const rawTables = [
  { key: "herbLinks", label: "中药侧原始表" },
  { key: "diseaseTargets", label: "疾病侧原始表" },
  { key: "directDiseaseHerbLinks", label: "直接关联表" },
] as const;

export function NetworkResultDownloads({ result }: { result: NetworkPharmacologyResult }) {
  return <section aria-label="本次候选靶点与证据下载">
    <div className="source-record-actions">
      <button className="btn btn-secondary" type="button" disabled={!result.targets.length} onClick={() => download(`network-targets-task-${result.taskId}.csv`, networkTargetsCsv(result), "text/csv;charset=utf-8")}><Table2 size={15} />候选靶点 CSV</button>
      <button className="btn btn-secondary" type="button" disabled={!result.targets.some((target) => target.sources.length)} onClick={() => download(`network-evidence-task-${result.taskId}.csv`, networkEvidenceCsv(result), "text/csv;charset=utf-8")}><Download size={15} />来源证据 CSV</button>
      {rawTables.map(({ key, label }) => <button key={key} className="btn btn-secondary" type="button" disabled={!result.rawLimits || !result.raw?.[key].length} onClick={() => {
        const content = networkRawCsv(result, key);
        if (content !== null) download(`network-${key}-task-${result.taskId}.csv`, content, "text/csv;charset=utf-8");
      }}><Download size={15} />{label}</button>)}
      <button className="btn btn-secondary" type="button" onClick={() => download(`network-result-task-${result.taskId}.json`, JSON.stringify(result, null, 2), "application/json;charset=utf-8")}><FileJson size={15} />本次结果 JSON</button>
    </div>
    <p className="section-help" style={{ marginTop: ".5rem" }}>导出当前接口返回的候选靶点及其来源版本、记录号；每个靶点最多附带 30 条来源记录，来源 CSV 的行数不等于全库证据总数。{result.limits.targetsTruncated ? "本次候选靶点超过 1,000 个，导出同页面一样仅包含前 1,000 个。" : ""}</p>
    {!result.raw || !result.rawLimits ? <p className="section-help">此任务未保存原始侧证据，相关导出不可用；不会用当前目录补算历史结果。</p> : <p className="section-help">三类原始表按本次读取的版本化目录关系生成，含未进入候选集的证据，保留实体 ID 和来源记录；中药侧每行同时保留中药—成分与成分—靶点两条来源。每表最多 {result.rawLimits.rowLimit.toLocaleString("zh-CN")} 行，本次读取的疾病—中药—靶点记录另保存在本次 JSON 中。{result.rawLimits.structuralRowsCollapsed ? "工作簿中重复的中药—成分结构关系按来源版本取一条代表记录；全部原始行仍保留在来源记录表，此导出不是全库原始文件。" : ""}{rawTables.some(({ key }) => rawTableTruncated(result, key)) || result.rawLimits.tablesTruncated.diseaseHerbLinks ? "本次输入关系或导出表超过上限，侧证据范围不完整；各表 CSV 保留截断标记。" : ""}</p>}
  </section>;
}
