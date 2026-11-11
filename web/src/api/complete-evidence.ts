import { ApiError, apiRequest } from "./client";
import { getAnalysisTask, type AnalysisTask } from "./datasets";

export type EvidenceSnapshot = {
  version: string; complete: true; sha256: string; capturedAt: string;
  tables: Record<string, { count: number; sha256: string; columns: string[] }>;
};
export type CompleteTaskOptions = {
  isActive?: () => boolean;
  onTask?: (task: AnalysisTask) => void;
  onReadError?: () => void;
};

// A failed GET only re-reads the existing task; it must NEVER repeat a POST.
export async function waitForCompleteTask(initial: AnalysisTask, options: CompleteTaskOptions = {}) {
  let task = initial;
  let announce = true;
  const start = Date.now();
  while (true) {
    if (options.isActive && !options.isActive()) throw new Error("页面查询已切换，后台任务仍保留。");
    if (task.id !== initial.id || task.task_type !== "network") throw new Error("完整分析任务编号或类型不一致。");
    if (announce) options.onTask?.(task);
    announce = false;
    if (task.status === "succeeded") return task;
    if (!["queued", "running"].includes(task.status)) throw new Error(task.error_summary || `任务 #${task.id} 未完成，请查看失败原因后重试。`);
    if (Date.now() - start > 20 * 60 * 1000) throw new Error(`任务 #${task.id} 仍在后台，请从任务记录重新打开；不要重复提交。`);
    await new Promise(resolve => window.setTimeout(resolve, 1200));
    if (options.isActive && !options.isActive()) throw new Error("页面查询已切换，后台任务仍保留。");
    try { task = await getAnalysisTask(initial.id); announce = true; }
    catch (error) {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500 && ![408, 429].includes(error.status)) throw error;
      options.onReadError?.();
    }
  }
}

export function snapshotDownloadUrl(taskId: number, table?: string, format: "csv" | "jsonl" = "jsonl") {
  const params = new URLSearchParams({ file_format: format });
  if (table) params.set("table", table);
  return `/api/v1/research/analysis-tasks/${taskId}/snapshot-export/?${params}`;
}

export type SnapshotPage = {
  count: number; next: string | null; previous: string | null;
  taskId: number; table: string; snapshotSha256: string; tableSha256: string; complete: true;
  results: Array<{ ordinal: number; payload: Record<string, unknown> }>;
};
export const getSnapshotPage = (taskId: number, table: string, page: number) =>
  apiRequest<SnapshotPage>(`/api/v1/research/analysis-tasks/${taskId}/snapshot-rows/?${new URLSearchParams({ table, page: String(page), page_size: "20" })}`);
