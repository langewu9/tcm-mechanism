import { apiRequest } from "./client";
import type { AnalysisTask } from "./datasets";
import { waitForCompleteTask, type CompleteTaskOptions, type EvidenceSnapshot } from "./complete-evidence";

export type NetworkRawTable = "herbLinks" | "diseaseTargets" | "diseaseHerbLinks" | "directDiseaseHerbLinks";

export type NetworkPharmacologyResult = {
  snapshot?: EvidenceSnapshot;
  taskId: number;
  summary: {
    herb: string;
    herbs: string[];
    matchedHerbs: string[];
    unmatchedHerbs: string[];
    formulas?: string[];
    matchedFormulas?: string[];
    unmatchedFormulas?: string[];
    unresolvedFormulas?: string[];
    disease: string;
    expandedDiseaseQueries?: string[];
    diseaseAliasSource?: string;
    diseaseAliasSourceCommit?: string;
    matchedDiseases: string[];
    unmatchedDiseases: string[];
    diseaseTargetCount: number;
    herbTargetCount: number;
    strictIntersectionCount: number;
    directAssociationTargetCount: number;
    candidateTargetCount: number;
    componentCount: number;
    pathwayCount: number;
  };
  targets: Array<{
    target: string;
    normalizedTarget: string;
    matchType: string;
    targetName: string;
    genes: string;
    pathways: string[];
    components: string[];
    herbs: string[];
    diseaseNames: string[];
    herbEvidenceCount: number;
    diseaseEvidenceCount: number;
    directEvidenceCount: number;
    sources: Array<{ source: string; sourceSlug: string; sourceVersion: string; evidenceType: string; sourceRecordId: string; relationType: string; score: number | null }>;
  }>;
  raw?: Record<NetworkRawTable, Array<Record<string, string | number | null>>>;
  rawLimits?: {
    formatVersion: string;
    rowLimit: number;
    tablesTruncated: Record<NetworkRawTable, boolean>;
    inputRelationsTruncated: Partial<Record<"formulaHerbs" | "herbCompounds" | "compoundTargets" | "diseaseTargets" | "pathways", boolean>>;
  };
  network: { nodes: Array<{ id: string; label: string; type: string }>; links: Array<{ source: string; target: string; relation: string; sourceRecordId: string; sourceSlug: string }> };
  charts: { overlap: Array<{ name: string; value: number }>; components: Array<{ name: string; targets: number }>; pathways: Array<{ name: string; targets: number }> };
  limits: { targetsTruncated: boolean; linksTruncated: boolean };
};

export type ReactomePathway = {
  stableId: string;
  name: string;
  species: string;
  matchedEntities: number;
  totalEntities: number | null;
  coverage: number | null;
  pValue: number | null;
  fdr: number;
};

export type ReactomeEnrichmentResult = {
  analysisKind: "reactome_enrichment";
  organism: string;
  inputCount: number;
  mappedCount: number;
  mappings: Array<Record<string, unknown>>;
  ambiguous: string[];
  unmapped: string[];
  rejected: string[];
  truncatedCount: number;
  source: string;
  sourceVersion: string | null;
  sourceToken: string | null;
  identifiersNotFound: number;
  pathways: ReactomePathway[];
  retrievedAt: string;
};

export async function runNetworkPharmacology(input: { herb: string; disease: string; source_case_id?: number; source_candidate_id?: number }, options?: CompleteTaskOptions) {
  const queued = await apiRequest<AnalysisTask>("/api/v1/analysis/network-pharmacology/", { method: "POST", body: { ...input, complete: true } });
  const task = await waitForCompleteTask(queued, options);
  const result = task.result as unknown as NetworkPharmacologyResult;
  if (!result.snapshot?.complete || !result.summary || !Array.isArray(result.targets)) throw new Error("任务尚无完整本地分析快照。");
  return { ...result, taskId: task.id };
}

export const runReactomeEnrichment = (sourceTaskId: number) =>
  apiRequest<AnalysisTask>("/api/v1/analysis/pathway-enrichment/", { method: "POST", body: { source_task_id: sourceTaskId, consent: true } });

export const runStringNetwork = (sourceTaskId: number, required_score: number) =>
  apiRequest<AnalysisTask>("/api/v1/analysis/string-network/", { method: "POST", body: { source_task_id: sourceTaskId, required_score, consent: true } });

export const createVisualization = (taskId: number, chartKey: string) =>
  apiRequest<AnalysisTask>(`/api/v1/research/analysis-tasks/${taskId}/visualizations/`, { method: "POST", body: { chartKey } });
