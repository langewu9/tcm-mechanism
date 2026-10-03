import { apiRequest, apiRequestBlob } from "./client";
import type { AnalysisTask } from "./datasets";
import type { NetworkPharmacologyResult } from "./network";

export type TextAnalysisResult = {
  algorithmVersion: string;
  ruleSource: string;
  matchStatus: "matched" | "no_rule_match" | "catalog_missing" | "ambiguous_syndrome";
  summary: string;
  selectedRule: { name: string; score: number; matchedKeywords: string[] } | null;
  ruleScores: Array<{ name: string; score: number; matchedKeywords: string[] }>;
  evidence: Record<string, string | string[]>;
  network: NetworkPharmacologyResult["network"];
  evidenceRecords: Array<{
    refId: string; subjectLabel: string; objectLabel: string; relationType: string;
    evidenceType: string; source: string; sourceSlug: string; sourceVersion: string; sourceRecordId: string;
  }>;
  sources: Array<{ id: number; source: string; sourceSlug: string; version: string; checksumSha256: string }>;
  warnings: string[];
  limits: { maxRelations: number; relationsTruncated: boolean };
};
export type TextAnalysisTask = Omit<AnalysisTask, "result"> & { result: TextAnalysisResult };
export type TextAnalysisWorkspace = {
  tasks: TextAnalysisTask[];
  cases: Array<{ id: number; title: string }>;
  casesTruncated: boolean;
};
export const getTextAnalysisWorkspace = () => apiRequest<TextAnalysisWorkspace>("/api/v1/research/text-analysis/");
export const createTextAnalysis = (input: { name: string; query: string; caseId: number | null }) =>
  apiRequest<TextAnalysisTask>("/api/v1/research/text-analysis/", { method: "POST", body: input });
export const exportTextAnalysis = (taskId: number, format: "csv" | "pdf") =>
  apiRequestBlob(`/api/v1/research/analysis-tasks/${taskId}/export/?file_format=${format}`);
