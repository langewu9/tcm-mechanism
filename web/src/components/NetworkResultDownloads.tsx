import { Download, FileJson, Table2 } from "lucide-react";
import type { NetworkPharmacologyResult } from "../api/network";

type CsvValue = string | number | null | undefined;

function csvCell(value: CsvValue) {
  let text = String(value ?? "");
  // Spreadsheet applications can interpret quoted strings as formulae too.
  if (typeof value === "string" && /^[\s\u0000-\u001f]*[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

function csv(headers: string[], rows: CsvValue[][]) {
  return `\ufeff${[headers, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n")}\r\n`;
}

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

function download(filename: string, body: string, type: string) {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function NetworkResultDownloads({ result }: { result: NetworkPharmacologyResult }) {
  return <section aria-label="本次候选靶点与证据下载">
    <div className="source-record-actions">
      <button className="btn btn-secondary" type="button" disabled={!result.targets.length} onClick={() => download(`network-targets-task-${result.taskId}.csv`, networkTargetsCsv(result), "text/csv;charset=utf-8")}><Table2 size={15} />候选靶点 CSV</button>
      <button className="btn btn-secondary" type="button" disabled={!result.targets.some((target) => target.sources.length)} onClick={() => download(`network-evidence-task-${result.taskId}.csv`, networkEvidenceCsv(result), "text/csv;charset=utf-8")}><Download size={15} />来源证据 CSV</button>
      <button className="btn btn-secondary" type="button" onClick={() => download(`network-result-task-${result.taskId}.json`, JSON.stringify(result, null, 2), "application/json;charset=utf-8")}><FileJson size={15} />本次结果 JSON</button>
    </div>
    <p className="section-help" style={{ marginTop: ".5rem" }}>导出当前接口返回的候选靶点及其来源版本、记录号；每个靶点最多附带 30 条来源记录，来源 CSV 的行数不等于全库证据总数。{result.limits.targetsTruncated ? "本次候选靶点超过 1,000 个，导出同页面一样仅包含前 1,000 个。" : ""}</p>
  </section>;
}
