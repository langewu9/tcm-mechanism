import { apiRequest } from "./client";
import type { AnalysisTask } from "./datasets";

export type CaseStatisticRow = { label: string; count: number };
export type CaseStatisticMetric = { label: string; unit: string; denominator: number; multiLabel?: boolean; rows: CaseStatisticRow[] };
export type CaseAnalysisFigure = { label: string; note: string; table: { headers: string[]; rows: (string | number)[][] } };
export type CaseGraphEvidence = { sheet: string; row: number; field: string; value?: string };
export type CaseGraphNode = { id: string; type: string; typeLabel: string; label: string; properties: Record<string, string | number>; evidence: CaseGraphEvidence[] };
export type CaseGraphEdge = { id: string; source: string; target: string; type: string; label: string; properties: Record<string, string | number>; evidence: CaseGraphEvidence[] };
export type CaseKnowledgeGraph = {
  schemaVersion: string;
  scope: "all_visits";
  scopeLabel: string;
  sourceSheet: string;
  sourceVisitCount: number;
  includedVisitCount: number;
  omittedVisitCount: number;
  caseCount: number;
  entityCount: number;
  relationshipCount: number;
  limits: { maxVisits: number; maxEntities: number; maxRelationships: number };
  nodes: CaseGraphNode[];
  edges: CaseGraphEdge[];
};
export type CaseStatisticsSnapshot = {
  adapterVersion: string;
  testData: true;
  unit: "first_visit" | "all_visits";
  unitLabel: string;
  recordCount: number;
  caseGroupCount: number;
  analysisCount: number;
  sheetName: string;
  fileSha256: string;
  metrics: Record<string, CaseStatisticMetric>;
  figures?: Record<string, CaseAnalysisFigure>;
  knowledgeGraph?: CaseKnowledgeGraph;
  medicationSummary?: {prescriptionCount: number; herbCount: number; ruleCount: number; missingPrescriptionCount: number};
};
export type CaseStatisticsTask = AnalysisTask & { result: CaseStatisticsSnapshot };

export const getCaseStatisticsTask = (taskId: number) =>
  apiRequest<CaseStatisticsTask>(`/api/v1/research/case-statistics/?task=${taskId}`);
export const getRecentCaseStatisticsTasks = () =>
  apiRequest<{ results: CaseStatisticsTask[] }>("/api/v1/research/case-statistics/");
export const uploadCaseStatisticsWorkbook = (file: File, unit: "first_visit" | "all_visits") => {
  const body = new FormData();
  body.append("file", file);
  body.append("unit", unit);
  return apiRequest<CaseStatisticsTask>("/api/v1/research/case-statistics/", { method: "POST", body });
};
