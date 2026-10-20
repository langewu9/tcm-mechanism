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

export async function restoreLatestAssistantTask() {
  const page = await getAnalysisTaskSummaries(1, undefined, "research_assistant");
  const latest = page.results.find(item => item.task_type === "research_assistant");
  return latest ? hydrate(latest) : null;
}

export async function restoreProteomicsTasks() {
  const page = await getAnalysisTaskSummaries();
  const latest = page.results.find(item => item.task_type === "proteomics");
  if (!latest) return { task: null, visualizationTask: null, volcanoVisualizationTask: null };
  const enrichment = page.results.find(item => isVisualization(item, latest.id)
    && item.display_parameters.chartKey === "proteomics_go_kegg_enrichment");
  const volcano = page.results.find(item => isVisualization(item, latest.id)
    && item.display_parameters.chartKey === "proteomics_volcano");
  const [task, visualizationTask, volcanoVisualizationTask] = await Promise.all([
    hydrate(latest), enrichment ? hydrate(enrichment) : null, volcano ? hydrate(volcano) : null,
  ]);
  return { task, visualizationTask, volcanoVisualizationTask };
}

export async function restoreGalleryJobs(summaries: AnalysisTaskSummary[], parentId: number, allowedKeys: Set<string>) {
  const latest = new Map<string, AnalysisTaskSummary>();
  for (const summary of summaries) {
    const key = summary.display_parameters.chartKey;
    if (summary.task_type === "visualization" && summary.parent_task === parentId
      && typeof key === "string" && allowedKeys.has(key) && !latest.has(key)) latest.set(key, summary);
  }
  const entries = await Promise.all([...latest].map(async ([key, summary]) => [key, await hydrate(summary)] as const));
  return Object.fromEntries(entries) as Record<string, AnalysisTask>;
}
