import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { saveHerbEvidenceAnalysis, type HerbEvidenceSearch } from "../api/catalog";
import { getAnalysisTask, type AnalysisTask } from "../api/datasets";
import type { NetworkPharmacologyResult } from "../api/network";
import { KnowledgeNetworkGraph } from "./KnowledgeNetworkGraph";
import { RAnalysisGallery } from "./RAnalysisGallery";
import { SnapshotEvidence } from "./SnapshotEvidence";
import type { EvidenceSnapshot } from "../api/complete-evidence";

type CatalogResult = {
  analysisKind: "catalog_evidence";
  queries: string[];
  resultSha256: string;
  previewResultSha256?: string;
  snapshot?: EvidenceSnapshot;
  network: NetworkPharmacologyResult["network"];
  counts: { nodes: number; evidenceRecords: number; returnedEvidenceRecords: number; uniqueEdges: number };
  limits: { queryTruncated: boolean; graphTruncated: boolean };
};

function resultOf(task: AnalysisTask): CatalogResult {
  const result = task.result as Partial<CatalogResult>;
  if (task.task_type !== "network" || task.status !== "succeeded" || result?.analysisKind !== "catalog_evidence"
    || !Array.isArray(result.queries) || !result.queries.every(value => typeof value === "string")
    || typeof result.resultSha256 !== "string" || !Array.isArray(result.network?.nodes)
    || !Array.isArray(result.network?.links) || !result.counts || !result.limits) {
    throw new Error("该任务不是已保存的目录关系查询。");
  }
  return result as CatalogResult;
}

export function CatalogEvidenceFigures({ evidence }: { evidence: HerbEvidenceSearch | null }) {
  const [params, setParams] = useSearchParams();
  const savedId = params.get("catalogTask");
  const [task, setTask] = useState<AnalysisTask | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const locked = useRef(false);
  const mounted = useRef(false);
  const currentEvidence = useRef(evidence);
  const currentTask = useRef(task);
  currentEvidence.current = evidence; currentTask.current = task;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    generation.current++; locked.current = false;
    setTask(null); setError(null); setBusy(false);
    if (evidence) setParams(current => { const next = new URLSearchParams(current); next.delete("catalogTask"); return next; }, { replace: true });
    return () => { generation.current++; locked.current = false; };
  }, [evidence]);
  useEffect(() => {
    if (evidence || !savedId) return;
    const current = ++generation.current;
    if (!/^[1-9]\d*$/.test(savedId) || !Number.isSafeInteger(Number(savedId))) { setError("目录关系任务编号无效。"); return; }
    setBusy(true); setTask(null); setError(null);
    getAnalysisTask(Number(savedId)).then(source => {
      if (generation.current !== current) return;
      if (source.id !== Number(savedId)) throw new Error("返回的目录关系任务与所选记录不一致。");
      if (source.task_type !== "network" || source.input_parameters?.analysisKind !== "catalog_evidence") resultOf(source);
      if (source.status === "succeeded") resultOf(source);
      setTask(source);
    }).catch(cause => { if (generation.current === current) setError(cause instanceof Error ? cause.message : "目录关系图加载失败。"); })
      .finally(() => { if (generation.current === current) setBusy(false); });
    return () => { generation.current++; };
  }, [evidence, savedId]);

  useEffect(() => {
    if (!task || !["queued", "running"].includes(task.status)) return;
    let active = true, timer: number;
    const id = task.id;
    async function poll() {
      try {
        const next = await getAnalysisTask(id);
        if (!active) return;
        if (next.id !== id || next.task_type !== "network" || next.input_parameters?.analysisKind !== "catalog_evidence") throw new Error("返回的完整查询任务不一致。");
        if (next.status === "succeeded") resultOf(next);
        setTask(next); setError(null);
        if (!["queued", "running"].includes(next.status)) return;
      } catch { if (active) setError(`任务 #${id} 进度读取失败，正在重试读取已有任务。`); }
      if (active) timer = window.setTimeout(() => void poll(), 1200);
    }
    timer = window.setTimeout(() => void poll(), 1200);
    return () => { active = false; window.clearTimeout(timer); };
  }, [task?.id, task?.status]);

  async function save() {
    if (!mounted.current || evidence !== currentEvidence.current || !evidence?.resultSha256 || locked.current || currentTask.current) return;
    locked.current = true;
    const current = generation.current;
    setBusy(true); setError(null);
    try {
      const saved = await saveHerbEvidenceAnalysis(evidence);
      if (generation.current !== current) return;
      if (saved.status === "succeeded") {
        const result = resultOf(saved);
        if ((result.previewResultSha256 ?? result.resultSha256) !== evidence.resultSha256) throw new Error("保存结果与本次检索不一致，请重新检索。");
      } else if (saved.task_type !== "network" || saved.input_parameters?.expectedResultSha256 !== evidence.resultSha256) throw new Error("保存任务与本次检索不一致。");
      setTask(saved);
      setParams(currentParams => { const next = new URLSearchParams(currentParams); next.set("catalogTask", String(saved.id)); return next; }, { replace: true });
    } catch (cause) {
      if (generation.current === current) setError(cause instanceof Error ? cause.message : "关系查询保存失败，请重试。");
    } finally {
      if (generation.current === current) { locked.current = false; setBusy(false); }
    }
  }
  if (!evidence && !savedId) return null;
  const result = task?.status === "succeeded" ? resultOf(task) : null;
  const hasRelations = Boolean(evidence?.results.some(item => item.relations.length));
  return <section className="proteomics-result-section" aria-label="目录关系图与分析记录">
    <h3 className="section-title-sm">目录关系图与分析记录</h3>
    <p className="section-help">先保存本次检索的来源快照，再生成可下载的 R 图。使用实体 ID 连接关系，同名不同实体分别保留；这些连线表示目录收录关系。</p>
    {!task && evidence && <button className="btn btn-secondary" type="button" disabled={busy || !hasRelations || !evidence.resultSha256} onClick={() => void save()}>{busy ? "正在保存关系查询…" : "保存本次关系查询"}</button>}
    {busy && !evidence && <p role="status">正在读取已保存的关系查询…</p>}
    {error && <p className="notice-error" role="alert">{error}</p>}
    {task && ["queued", "running"].includes(task.status) && <p role="status">任务 #{task.id} · {task.status === "queued" ? "排队中" : "正在读取完整证据"} · {task.progress}%</p>}
    {task?.status === "failed" && <p className="notice-error" role="alert">任务 #{task.id}：{task.error_summary} 请重新检索后再提交。</p>}
    {task && result && <>
      <p className="section-help">任务 #{task.id} · {result.queries.join("、")} · {result.counts.nodes} 个节点 · {result.counts.evidenceRecords}/{result.counts.returnedEvidenceRecords} 条来源记录 · {result.counts.uniqueEdges} 对不同端点关系</p>
      <p className="section-help">快照按来源记录 ID 去重，R 图再合并同一对实体的重复连线；图中节点大小按展示子图计算。靶点名称仍需核对规范标识。</p>
      {(result.limits.queryTruncated || result.limits.graphTruncated) && <p className="notice-warning">{result.snapshot?.complete ? "完整证据已保存；以下图形只展示部分关系，可在完整快照中分页查看或下载全部记录。" : "查询或快照达到数量上限，以下仅展示已保存的部分关系，请缩小检索范围。"}</p>}
      <Link className="btn btn-secondary" to={`/research?catalogTask=${task.id}`}>打开此关系查询</Link>
      <details className="raw-details"><summary>来源版本与检索校验值</summary>
        {[...new Set(result.network.links.map(link => `${link.sourceSlug} · ${String((link as typeof link & { sourceVersion?: string }).sourceVersion ?? "")}`))].map(source => <p className="section-help" style={{ overflowWrap: "anywhere" }} key={source}>{source}</p>)}
        <p className="section-help" style={{ overflowWrap: "anywhere" }}>检索 SHA-256：{result.resultSha256}</p>
      </details>
      {result.snapshot && <SnapshotEvidence taskId={task.id} snapshot={result.snapshot} />}
      <KnowledgeNetworkGraph network={result.network} knownTruncated={result.limits.queryTruncated || result.limits.graphTruncated} />
      <RAnalysisGallery taskId={task.id} />
    </>}
  </section>;
}
