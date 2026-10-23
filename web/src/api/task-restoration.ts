import { getAnalysisTask, getAnalysisTaskSummaries, type AnalysisTask, type AnalysisTaskSummary } from "./datasets";

async function hydrate(summary: AnalysisTaskSummary): Promise<AnalysisTask> {
  const task = await getAnalysisTask(summary.id);
  if (task.id !== summary.id || task.task_type !== summary.task_type || task.parent_task !== summary.parent_task) {
    throw new Error("任务详情与列表记录不一致，请刷新后重试。");
  }
  return task;
}

function isVisualization(summary: AnalysisTaskSummary, parentId: number) {
  return summary.task_type === "visualization"
    && (summary.parent_task === null || summary.parent_task === parentId)
    && summary.display_parameters.analysisKind === "r_visualization"
    && Number(summary.display_parameters.parentTaskId) === parentId;
}

export async function restoreLatestAssistantTask(taskId?: number) {
  if (taskId !== undefined) {
    if (!Number.isSafeInteger(taskId) || taskId < 1) throw new Error("任务编号无效。");
    const task = await getAnalysisTask(taskId);
    if (task.id !== taskId || task.task_type !== "research_assistant") throw new Error("任务编号或类型不一致。");
    return task;
  }
  const page = await getAnalysisTaskSummaries(1, undefined, "research_assistant");
  const latest = page.results.find(item => item.task_type === "research_assistant");
  return latest ? hydrate(latest) : null;
}

export async function restoreProteomicsTasks(taskId?: number) {
  let task: AnalysisTask;
  if (taskId !== undefined) {
    if (!Number.isSafeInteger(taskId) || taskId < 1) throw new Error("蛋白组学任务编号无效。");
    task = await getAnalysisTask(taskId);
    if (task.id !== taskId || task.task_type !== "proteomics") throw new Error("蛋白组学任务编号或类型不一致。");
  } else {
    const page = await getAnalysisTaskSummaries(1, undefined, "proteomics");
    const latest = page.results.find(item => item.task_type === "proteomics");
    if (!latest) return { task: null, visualizationTask: null, volcanoVisualizationTask: null, figureError: null };
    task = await hydrate(latest);
  }
  try {
    const figures = await getAnalysisTaskSummaries(1, task.id);
    const jobs = await restoreGalleryJobs(figures.results, task.id,
      new Set(["proteomics_go_kegg_enrichment", "proteomics_volcano"]), figures.next);
    return { task, visualizationTask: jobs.proteomics_go_kegg_enrichment ?? null,
      volcanoVisualizationTask: jobs.proteomics_volcano ?? null, figureError: null };
  } catch {
    return { task, visualizationTask: null, volcanoVisualizationTask: null,
      figureError: "历史图表读取失败，分析结果已保留。可重新读取历史任务。" };
  }
}

export async function restoreGalleryJobs(summaries: AnalysisTaskSummary[], parentId: number, allowedKeys: Set<string>, nextPage?: string | null) {
  const latest = new Map<string, AnalysisTaskSummary>();
  let rows = summaries, pageNumber = 1;
  while (true) {
    for (const summary of rows) {
      const key = summary.display_parameters.chartKey;
      if (isVisualization(summary, parentId) && summary.parent_task === parentId
        && typeof key === "string" && allowedKeys.has(key) && !latest.has(key)) latest.set(key, summary);
    }
    if (!nextPage || latest.size === allowedKeys.size) break;
    if (!rows.length) throw new Error("图表历史分页响应无效，请重新读取。");
    // Construct local, authenticated URLs; never follow a server-provided next URL.
    const page = await getAnalysisTaskSummaries(++pageNumber, parentId);
    rows = page.results;
    nextPage = page.next;
  }
  const entries = await Promise.all([...latest].map(async ([key, summary]) => [key, await hydrate(summary)] as const));
  return Object.fromEntries(entries) as Record<string, AnalysisTask>;
}
