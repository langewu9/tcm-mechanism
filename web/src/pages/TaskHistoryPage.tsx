import { useEffect, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { getAnalysisTask, type AnalysisTask } from "../api/datasets";
import { parseSavedTaskId, savedTaskDestination, verifySavedTask } from "../api/task-history";
import { ReactomeEnrichmentResult } from "../components/ReactomeEnrichmentResult";
import { StringTaskResult } from "../components/StringNetworkResult";
import { SavedVisualizationResult } from "../components/SavedVisualizationResult";

const statuses: Record<AnalysisTask["status"], string> = { queued: "排队中", running: "运行中", succeeded: "已完成", failed: "失败", cancelled: "已取消" };
export function TaskHistoryPage() {
  const { taskId } = useParams();
  const [state, setState] = useState<{ id: string | undefined; task: AnalysisTask | null; error: string | null }>({ id: taskId, task: null, error: null });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true, timer: number | undefined, previous: AnalysisTask | undefined;
    setState({ id: taskId, task: null, error: null });
    async function read() {
      try {
        const id = parseSavedTaskId(taskId);
        const task = await getAnalysisTask(id);
        if (!active) return;
        verifySavedTask(task, id, previous);
        previous = task;
        setState({ id: taskId, task, error: null });
        if (["queued", "running"].includes(task.status) && !savedTaskDestination(task)) timer = window.setTimeout(() => void read(), 1500);
      } catch (cause) {
        if (active) setState({ id: taskId, task: previous ?? null, error: cause instanceof ApiError || cause instanceof Error ? cause.message : "历史任务读取失败。" });
      }
    }
    void read();
    return () => { active = false; if (timer !== undefined) window.clearTimeout(timer); };
  }, [taskId, attempt]);
  const current = state.id === taskId;
  const task = current ? state.task : null, error = current ? state.error : null;
  const destination = task ? savedTaskDestination(task) : null;
  if (destination && !error) return <Navigate to={destination} replace />;
  const pending = task && ["queued", "running"].includes(task.status);
  const kind = task?.input_parameters.analysisKind;
  return <>
    <div className="page-heading"><div className="page-heading-copy"><p className="page-kicker">Saved analysis</p><h1 className="page-title">历史任务{task ? ` #${task.id}` : ""}</h1><p className="page-description">查看这次任务保存的状态和结果。</p></div><Link className="btn btn-secondary" to="/dashboard">返回研究总览</Link></div>
    {error && <div className="notice-error" role="alert"><p>{error}</p><button className="btn btn-secondary" type="button" onClick={() => setAttempt(value => value + 1)}>重新读取此任务</button></div>}
    {!task && !error && <p role="status">正在读取指定任务…</p>}
    {task && <section className="panel proteomics-result-panel" aria-label="指定历史任务结果">
      <p className="section-help">任务 #{task.id} · {statuses[task.status]} · {task.progress}%</p>
      {task.parent_task !== null ? <Link className="btn btn-secondary" to={`/tasks/${task.parent_task}`}>查看来源任务 #{task.parent_task}</Link> : <p className="section-help">此任务未保存父任务关联，不推断来源任务。</p>}
      {pending && <p role="status">任务仍在后台，正在读取进度；不会重新提交分析。</p>}
      {task.status === "failed" && <p className="notice-error" role="alert">任务失败：{task.error_summary || "未记录具体原因。"} 可返回来源任务核对输入后，再决定是否重新分析。</p>}
      {task.status === "cancelled" && <p role="status">任务已取消，没有新的完成结果。</p>}
      {task.status === "succeeded" && (task.task_type === "visualization" ? <SavedVisualizationResult task={task} />
        : task.task_type === "network" && kind === "reactome_enrichment" ? <ReactomeEnrichmentResult task={task} />
        : task.task_type === "network" && kind === "string_ppi" ? <StringTaskResult task={task} />
        : <p className="notice-error" role="alert">此任务类型尚无对应的历史结果视图，未替换为其他任务。</p>)}
    </section>}
  </>;
}
