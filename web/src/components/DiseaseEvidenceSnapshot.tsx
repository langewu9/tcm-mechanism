import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { saveDiseaseEvidenceAnalysis, type DiseaseEvidenceSearch } from "../api/catalog";
import { getAnalysisTask, type AnalysisTask } from "../api/datasets";
import { waitForCompleteTask, type EvidenceSnapshot } from "../api/complete-evidence";
import { SnapshotEvidence } from "./SnapshotEvidence";

type DiseaseResult = { analysisKind: "disease_evidence"; query: string; counts: DiseaseEvidenceSearch["counts"]; snapshot: EvidenceSnapshot };
function verify(task: AnalysisTask) {
  if (!Number.isSafeInteger(task.id) || task.id < 1 || task.task_type !== "network" || task.input_parameters?.analysisKind !== "disease_evidence") throw new Error("返回的任务不是本次疾病证据查询。");
  if (task.status === "succeeded") {
    const result = task.result as Partial<DiseaseResult>;
    if (result.analysisKind !== "disease_evidence" || typeof result.query !== "string" || !result.snapshot?.complete
      || !/^[a-f0-9]{64}$/.test(result.snapshot.sha256) || !result.snapshot.tables
      || !result.counts || !["diseases", "herbs", "targets", "links", "relations"].every(key => {
        const value = result.counts?.[key as keyof DiseaseEvidenceSearch["counts"]];
        return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
      })) throw new Error("该任务没有可展示的完整疾病快照。");
  }
}

export function DiseaseEvidenceSnapshot({ evidence, onRestoreQuery }: { evidence: DiseaseEvidenceSearch | null; onRestoreQuery?: (query: string) => void }) {
  const [params, setParams] = useSearchParams(), savedId = params.get("diseaseTask");
  const [task, setTask] = useState<AnalysisTask | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const generation = useRef(0), locked = useRef(false), mounted = useRef(false);
  const currentEvidence = useRef(evidence), currentTask = useRef(task);
  currentEvidence.current = evidence; currentTask.current = task;
  const current = (id: number) => mounted.current && generation.current === id;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++; }; }, []);
  useEffect(() => {
    generation.current++; locked.current = false; setTask(null); setBusy(false); setError("");
    if (evidence) setParams(previous => { const next = new URLSearchParams(previous); next.delete("diseaseTask"); return next; }, { replace: true });
    return () => { generation.current++; };
  }, [evidence]);

  async function settle(source: AnalysisTask, id: number) {
    verify(source);
    return waitForCompleteTask(source, {
      isActive: () => current(id),
      onTask: next => { verify(next); if (current(id)) { setTask(next); setError(""); } },
      onReadError: () => { if (current(id)) setError(`任务 #${source.id} 进度读取失败，正在重试读取已有任务。`); },
    });
  }

  async function read(taskId: number, id: number) {
    try {
      const source = await getAnalysisTask(taskId);
      if (!current(id)) return;
      if (source.id !== taskId) throw new Error("返回的疾病证据任务编号不一致。");
      verify(source);
      if (!evidence && typeof source.input_parameters.query === "string") onRestoreQuery?.(source.input_parameters.query);
      await settle(source, id);
    } catch (cause) { if (current(id)) setError(cause instanceof Error ? cause.message : "疾病快照读取失败。"); }
    finally { if (current(id)) { setBusy(false); locked.current = false; } }
  }

  useEffect(() => {
    if (evidence || !savedId) return;
    const id = ++generation.current;
    setTask(null); setBusy(true); setError("");
    if (!/^[1-9]\d*$/.test(savedId) || !Number.isSafeInteger(Number(savedId))) { setError("疾病证据任务编号无效。"); setBusy(false); return; }
    locked.current = true;
    void read(Number(savedId), id);
    return () => { generation.current++; locked.current = false; };
  }, [evidence, savedId]);

  async function save() {
    if (!mounted.current || currentEvidence.current !== evidence || !evidence?.resultSha256 || locked.current || currentTask.current) return;
    locked.current = true;
    const id = generation.current;
    setBusy(true); setError("");
    try {
      const queued = await saveDiseaseEvidenceAnalysis(evidence);
      if (!current(id)) return;
      verify(queued);
      if (queued.input_parameters.expectedResultSha256 !== evidence.resultSha256 || queued.input_parameters.query !== evidence.query) throw new Error("保存任务与本次疾病检索不一致。");
      setParams(previous => { const next = new URLSearchParams(previous); next.set("diseaseTask", String(queued.id)); return next; }, { replace: true });
      await settle(queued, id);
    } catch (cause) { if (current(id)) setError(cause instanceof Error ? cause.message : "完整疾病查询保存失败。"); }
    finally { if (current(id)) { setBusy(false); locked.current = false; } }
  }

  const visible = task && (!evidence || task.input_parameters.expectedResultSha256 === evidence.resultSha256)
    && (!savedId || task.id === Number(savedId)) ? task : null;
  const result = visible?.status === "succeeded" ? visible.result as unknown as DiseaseResult : null;
  const retryId = visible?.id ?? (!evidence && savedId && /^[1-9]\d*$/.test(savedId) && Number.isSafeInteger(Number(savedId)) ? Number(savedId) : null);
  if (!evidence && !savedId) return null;
  return <section className="proteomics-result-section" aria-label="完整疾病证据与分析记录">
    <h3 className="section-title-sm">完整疾病证据与分析记录</h3>
    <p className="section-help">上方检索和导出是有限预览。保存后由后台读取全部有效输入，完整证据按任务固定保存，目录更新不会改变本次记录。</p>
    {!visible && evidence && <button className="btn btn-secondary" type="button" disabled={busy || !evidence.matches.length || !evidence.resultSha256} onClick={() => void save()}>{busy ? "正在保存完整疾病查询…" : "保存完整疾病查询"}</button>}
    {busy && <p role="status">{visible ? `任务 #${visible.id} · ${visible.status === "queued" ? "排队中" : "正在读取完整证据"} · ${visible.progress}%` : "正在读取疾病快照…"}</p>}
    {error && <p className="notice-error" role="alert">{error}{retryId && !busy && <button className="btn btn-secondary" type="button" onClick={() => { if (locked.current) return; locked.current = true; setBusy(true); void read(retryId, generation.current); }}>重新读取任务</button>}</p>}
    {visible && result && <>
      <p className="section-help">任务 #{visible.id} · {result.query} · 完整匹配 {result.counts.diseases} 个疾病实体、{result.counts.herbs} 个中药实体、{result.counts.targets} 个来源靶点、{result.counts.relations} 条来源关系。</p>
      <p className="section-help">不同实体分别计数；没有规范身份的关系不会按同名中药补配。目录关系不代表因果或临床结论。</p>
      <SnapshotEvidence taskId={visible.id} snapshot={result.snapshot} />
    </>}
  </section>;
}
