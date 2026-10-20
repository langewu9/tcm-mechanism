import { apiRequest } from "./client";
import type { AnalysisTask } from "./datasets";

export type MedicalCase = {
  id: number;
  owner_id: number;
  owner_username: string;
  archived_at: string | null;
  archived_by: number | null;
  title: string;
  deidentified_text: string;
  structured_data: Record<string, unknown>;
  source_reference: string;
  research_notes: string;
  review_status: "draft" | "reviewed";
  reviewed_at: string | null;
  reviewed_by_username: string | null;
  created_at: string;
  updated_at: string;
};

export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };
export type CaseAuditEvent = {
  id: number;
  case_id_snapshot: number;
  case_title_snapshot: string;
  actor_username: string | null;
  action: "created" | "updated" | "reviewed" | "candidate" | "analyzed" | "deleted" | "archived" | "restored";
  changed_fields: string[];
  content_hashes: Record<string, { before: string | null; after: string | null }>;
  metadata: Record<string, unknown>;
  created_at: string;
};
export type CaseEvidence = { field: string; quote: string };
export type CaseKnowledgeEvidence = {
  refId: string;
  kind: "entity" | "relation";
  label?: string;
  entityType?: string;
  stableId?: string;
  subject?: string;
  predicate?: string;
  object?: string;
  evidenceType?: string;
  score?: number | null;
  sourceName: string;
  sourceVersion: string;
  sourceRecordId?: string;
  evidenceText?: string;
};
export type MedicalCaseCandidate = {
  id: number;
  task_id: number;
  medical_case_id: number;
  candidate_type: "syndrome" | "formula";
  label: string;
  entity_id: number | null;
  entity_stable_id: string | null;
  entity_label: string | null;
  match_status: "exact" | "unmatched" | "ambiguous";
  confidence: string;
  rank: number;
  evidence: CaseEvidence[];
  knowledge_evidence: CaseKnowledgeEvidence[];
  review_status: "pending" | "accepted" | "rejected";
  review_note: string;
  reviewed_by_username: string | null;
  reviewed_at: string | null;
  created_at: string;
};
export type MedicalCaseAnalysis = {
  task: AnalysisTask | null;
  candidates: MedicalCaseCandidate[];
  stale: boolean;
  modelConfiguration: { configured: boolean; name: string | null; version: string | null };
};
export type NewMedicalCase = Pick<MedicalCase, "title" | "deidentified_text" | "source_reference" | "research_notes"> & {
  structured_data: Record<string, string>;
};

export const getMedicalCases = (page = 1, archived = false) => apiRequest<Page<MedicalCase>>(`/api/v1/research/cases/?page=${page}&archived=${archived}`);
export const createMedicalCase = (data: NewMedicalCase) =>
  apiRequest<MedicalCase>("/api/v1/research/cases/", { method: "POST", body: data });
export const restoreMedicalCase = (id: number) =>
  apiRequest<MedicalCase>(`/api/v1/research/cases/${id}/restore/`, { method: "POST" });
export const deleteMedicalCase = (id: number) =>
  apiRequest<void>(`/api/v1/research/cases/${id}/`, { method: "DELETE" });
export const getMedicalCaseAudit = (id: number) =>
  apiRequest<Page<CaseAuditEvent>>(`/api/v1/research/cases/${id}/audit/`);
export const getMedicalCaseAnalysis = (id: number) =>
  apiRequest<MedicalCaseAnalysis>(`/api/v1/research/cases/${id}/analysis/`);
export const startMedicalCaseAnalysis = (id: number) =>
  apiRequest<AnalysisTask>(`/api/v1/research/cases/${id}/analysis/`, { method: "POST", body: { confirmLocalModel: true } });
export const reviewMedicalCaseCandidate = (caseId: number, candidateId: number, decision: "accept" | "reject") =>
  apiRequest<MedicalCaseCandidate>(`/api/v1/research/cases/${caseId}/candidates/${candidateId}/review/`, { method: "POST", body: { decision } });
export const approveMedicalCase = (id: number) =>
  apiRequest<MedicalCase>(`/api/v1/research/cases/${id}/review/`, { method: "POST", body: { decision: "approve" } });
