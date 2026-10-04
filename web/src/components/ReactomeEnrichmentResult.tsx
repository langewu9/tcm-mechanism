import { Download } from "lucide-react";
import type { AnalysisTask } from "../api/datasets";
import type { NetworkPharmacologyResult, ReactomeEnrichmentResult as EnrichmentResult, ReactomePathway } from "../api/network";
import { downloadText } from "../utils/downloads";

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function isNullableNumber(value: unknown) {
  return value === null || isNumber(value);
}

function isPathway(value: unknown): value is ReactomePathway {
  return isRecord(value) && typeof value.stableId === "string" && typeof value.name === "string"
    && typeof value.species === "string" && isNumber(value.matchedEntities) && isNumber(value.fdr)
    && isNullableNumber(value.totalEntities) && isNullableNumber(value.coverage) && isNullableNumber(value.pValue);
}

// Read the Django task contract without turning incomplete or cancelled tasks into empty success.
export function readReactomeEnrichment(task: AnalysisTask | null): EnrichmentResult | null {
  if (!task || task.status !== "succeeded" || task.input_parameters.analysisKind !== "reactome_enrichment") return null;
  const value: unknown = task.result;
  if (!isRecord(value) || value.analysisKind !== "reactome_enrichment" || !Array.isArray(value.pathways)
    || !value.pathways.every(isPathway) || !isNumber(value.inputCount) || !isNumber(value.mappedCount)
    || !isNumber(value.identifiersNotFound) || !isNumber(value.truncatedCount) || typeof value.organism !== "string"
    || typeof value.source !== "string" || typeof value.retrievedAt !== "string"
    || !(value.sourceVersion === null || typeof value.sourceVersion === "string")) return null;
  return value as EnrichmentResult;
}

export function reactomeResultJson(task: AnalysisTask, source: NetworkPharmacologyResult) {
  if (!readReactomeEnrichment(task)) return null;
  return JSON.stringify({
    pageAssociation: {
      note: "sourceTaskId 为本页面关联的本地查询任务号，外部服务任务未保存此绑定。",
      sourceTaskId: source.taskId,
      herb: source.summary.herb,
      disease: source.summary.disease,
    },
    task,
  }, null, 2);
}

export function ReactomeEnrichmentResult({ task, source }: { task: AnalysisTask; source: NetworkPharmacologyResult }) {
  if (["queued", "running"].includes(task.status)) return <p className="section-help" role="status">Reactome 任务 #{task.id} 正在后台执行（{task.progress}%）。</p>;
  if (task.status === "failed") return <div className="notice-error" role="alert">Reactome 任务 #{task.id} 失败：{task.error_summary}</div>;
  if (task.status === "cancelled") return <p className="section-help" role="status">Reactome 任务 #{task.id} 已取消。</p>;
  const value = readReactomeEnrichment(task);
  if (!value) return <div className="notice-error" role="alert">Reactome 任务 #{task.id} 的结果格式不完整，暂不能绘图或导出。</div>;
  const pathways = [...value.pathways].sort((left, right) => left.fdr - right.fdr);
  function download() {
    const body = reactomeResultJson(task, source);
    if (body) downloadText(`reactome-pathways-task-${task.id}.json`, body, "application/json;charset=utf-8");
  }
  return <div className="panel source-record">
    <div className="case-record-top"><div><h3>Reactome 富集结果 · {value.sourceVersion ?? "来源版本未返回"}</h3><p className="section-help">任务 #{task.id} · {value.source} · {value.organism}</p></div>
      <button className="btn btn-secondary" type="button" onClick={download}><Download size={15} />导出全部通路 JSON</button></div>
    <p className="section-help">映射 {value.mappedCount} 个标识 · 未识别 {value.identifiersNotFound} 个 · 保留 {pathways.length} 条显著通路 · 检索时间 {value.retrievedAt}</p>
    {pathways.length ? <ul className="proteomics-pathways">{pathways.slice(0, 20).map((item, index) => <li key={`${item.stableId}-${index}`}><strong>{item.name}</strong><span>{item.stableId} · 命中 {item.matchedEntities} 个实体 · FDR {item.fdr.toExponential(2)}</span></li>)}</ul> : <p className="section-help">本次 Reactome 分析已完成，没有返回符合当前筛选阈值的显著通路。</p>}
    {pathways.length > 20 && <p className="section-help">页面展示 FDR 最低的 20 条；JSON 包含任务返回的全部 {pathways.length} 条通路及完整输入、来源版本和检索记录。</p>}
    <p className="section-help">本地查询任务 #{source.taskId} 是页面关联；导出保留实际外部任务记录。</p>
    {value.truncatedCount > 0 && <p className="section-help">标识映射达到服务上限，另有 {value.truncatedCount} 个标识未提交。</p>}
  </div>;
}
