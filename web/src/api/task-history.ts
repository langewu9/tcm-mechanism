import type { AnalysisTask } from "./datasets";

export function parseSavedTaskId(value: string | undefined): number {
  if (!value || !/^[1-9]\d*$/.test(value) || !Number.isSafeInteger(Number(value))) throw new Error("任务编号无效。");
  return Number(value);
}

export function verifySavedTask(task: AnalysisTask, requestedId: number, previous?: AnalysisTask) {
  if (!task || typeof task !== "object") throw new Error("任务保存记录不完整，无法读取此历史记录。");
  const record = (value: unknown) => value !== null && typeof value === "object" && !Array.isArray(value);
  const optionalId = (value: unknown) => value === null || (typeof value === "number" && Number.isSafeInteger(value) && value > 0);
  if (task.id !== requestedId || !["proteomics", "case_link", "network", "visualization", "research_assistant", "text_analysis"].includes(task.task_type)
    || !["queued", "running", "succeeded", "failed", "cancelled"].includes(task.status)
    || !record(task.input_parameters) || !record(task.result) || !optionalId(task.parent_task)
    || task.parent_task === task.id || !optionalId(task.dataset) || !optionalId(task.medical_case)
    || typeof task.error_summary !== "string" || !Number.isInteger(task.progress) || task.progress < 0 || task.progress > 100) throw new Error("任务编号、类型或保存记录不完整，无法读取此历史记录。");
  if (previous && (task.task_type !== previous.task_type || task.parent_task !== previous.parent_task
    || task.dataset !== previous.dataset || task.medical_case !== previous.medical_case
    || task.input_parameters.analysisKind !== previous.input_parameters.analysisKind
    || task.input_parameters.chartKey !== previous.input_parameters.chartKey
    || task.input_parameters.parentTaskId !== previous.input_parameters.parentTaskId
    || task.input_parameters.inputSha256 !== previous.input_parameters.inputSha256)) throw new Error("任务来源发生变化，已停止读取，请重新核对。");
}

// Main tasks return to their existing workbench. Child jobs keep their exact
// saved result instead of opening a different/latest job in a parent's gallery.
export function savedTaskDestination(task: AnalysisTask): string | null {
  if (task.task_type === "proteomics") return `/proteomics?proteomicsTask=${task.id}`;
  if (task.task_type === "text_analysis") return `/analysis?textTask=${task.id}`;
  if (task.task_type === "case_link") return `/cases?caseTask=${task.id}`;
  if (task.task_type === "research_assistant") return `/assistant?assistantTask=${task.id}`;
  if (task.task_type !== "network") return null;
  if (task.input_parameters.analysisKind === "network_pharmacology") return `/network-pharmacology?networkTask=${task.id}`;
  if (task.input_parameters.analysisKind === "catalog_evidence") return `/research?catalogTask=${task.id}`;
  if (task.input_parameters.analysisKind === "disease_evidence") return `/research?diseaseTask=${task.id}`;
  return null;
}
