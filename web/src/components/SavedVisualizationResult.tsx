import type { AnalysisTask } from "../api/datasets";
import { parseSavedTaskId } from "../api/task-history";
import { ArtifactPreview } from "./ArtifactPreview";

type Artifact = { id: number; format: string; downloadUrl: string };
const labels: Record<string, string> = {
  overlap: "中药—疾病靶点交集柱状图", proteomics_volcano: "差异蛋白火山图",
  proteomics_summary: "蛋白组学分析概览", proteomics_go_kegg_enrichment: "GO / KEGG 富集气泡图",
  proteomics_go_kegg_bar: "GO / KEGG 富集条形图", evidence_network: "中药—成分—靶点—疾病网络",
  gene_pathway_network: "基因—通路证据网络", gene_pathway_distribution: "基因通路分布图",
  ppi_network: "STRING PPI 网络图", ppi_degree: "PPI 连接度排行", reactome_enrichment: "Reactome 通路气泡图",
};

export function savedFigure(task: AnalysisTask) {
  if (!task.result || typeof task.result !== "object" || Array.isArray(task.result)
    || !task.input_parameters || typeof task.input_parameters !== "object") return null;
  const value = task.result as Record<string, unknown>;
  const key = task.input_parameters.chartKey;
  let resultParent: number, inputParent: number;
  try {
    resultParent = parseSavedTaskId(typeof value.parentTaskId === "number" || typeof value.parentTaskId === "string" ? String(value.parentTaskId) : undefined);
    inputParent = parseSavedTaskId(typeof task.input_parameters.parentTaskId === "number" || typeof task.input_parameters.parentTaskId === "string" ? String(task.input_parameters.parentTaskId) : undefined);
  } catch { return null; }
  const inputHash = task.input_parameters.inputSha256, resultHash = value.inputSha256;
  if ((inputHash !== undefined || resultHash !== undefined)
    && (typeof inputHash !== "string" || !/^[a-f0-9]{64}$/.test(inputHash) || inputHash !== resultHash)) return null;
  if (task.task_type !== "visualization" || task.input_parameters.analysisKind !== "r_visualization"
    || typeof key !== "string" || !key || value.taskId !== task.id || value.chartKey !== key
    || resultParent !== inputParent || resultParent === task.id
    || (task.parent_task !== null && (resultParent !== task.parent_task
      || !Number.isSafeInteger(task.parent_task) || task.parent_task < 1))
    || !Array.isArray(value.artifacts) || !value.artifacts.length || value.artifacts.length > 16) return null;
  const ids = new Set<number>();
  for (const item of value.artifacts) {
    if (!item || typeof item !== "object" || !Number.isSafeInteger(item.id) || item.id < 1 || ids.has(item.id)
      || !["svg", "png", "pdf", "html"].includes(item.format)
      || item.downloadUrl !== `/api/v1/research/analysis-artifacts/${item.id}/download/`) return null;
    ids.add(item.id);
  }
  return { title: Object.hasOwn(labels, key) ? labels[key] : "已保存图表", renderer: typeof value.rendererVersion === "string" ? value.rendererVersion : "版本未记录",
    artifacts: value.artifacts as Artifact[] };
}

export function SavedVisualizationResult({ task }: { task: AnalysisTask }) {
  const figure = savedFigure(task);
  if (!figure) return <p className="notice-error" role="alert">该图表的保存结果或来源关联不完整，暂不能展示或下载。</p>;
  const preview = figure.artifacts.find(item => item.format === "svg") ?? figure.artifacts.find(item => item.format === "png");
  return <div className="panel source-record"><h3>{figure.title} · {figure.renderer}</h3>
    {preview && <ArtifactPreview src={`${preview.downloadUrl}?inline=1`} alt={figure.title} />}
    <div className="source-record-actions">{figure.artifacts.map(item => <a className="btn btn-secondary" key={item.id} href={item.downloadUrl}>下载 {item.format.toUpperCase()}</a>)}</div>
  </div>;
}
