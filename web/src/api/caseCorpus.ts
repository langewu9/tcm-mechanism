import { apiRequest } from "./client";

export type CaseCategory = "" | "pulmonary" | "stroke" | "stomach" | "pharyngitis" | "general";
export type CaseCorpusSummary = {
  available: boolean; sourceName: string; version: string | null; checksumSha256: string | null;
  recordCount: number; retrievalMethod: "keyword";
  categories: Array<{ key: CaseCategory; label: string; count: number }>;
  modelConfiguration?: { configured: boolean; name: string | null; version: string | null };
};
export type ReferenceCase = {
  id: number; refId: string; caseId: string; category: CaseCategory; categoryLabel: string; title: string;
  clinicalFeatures: Record<string, string>; source: string; sourceLink: string; sourceDoctor: string;
  sourceSheet: string; sourceVersion: string; recordStatus: string; originalExcerpt: string;
  originalText?: string; structuredData?: Record<string, string | null>; workbookName?: string;
  contentSha256?: string; sourceChecksumSha256?: string; selected?: boolean;
};
export type CaseCorpusPage = { summary: CaseCorpusSummary; count: number; page: number; pageSize: number; results: ReferenceCase[] };
export const getCaseCorpusSummary = () => apiRequest<CaseCorpusSummary>("/api/v1/research/case-corpus/summary/");
export const getCaseCorpus = (q = "", category: CaseCategory = "", page = 1) =>
  apiRequest<CaseCorpusPage>(`/api/v1/research/case-corpus/?${new URLSearchParams({ q, category, page: String(page) })}`);
export const getReferenceCase = (id: number) => apiRequest<ReferenceCase>(`/api/v1/research/case-corpus/${id}/`);
