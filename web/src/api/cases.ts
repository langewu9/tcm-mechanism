import { apiRequest } from "./client";

export type MedicalCase = {
  id: number;
  owner_id: number;
  owner_username: string;
  title: string;
  deidentified_text: string;
  structured_data: Record<string, unknown>;
  source_reference: string;
  research_notes: string;
  review_status: "draft" | "reviewed";
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };
export type NewMedicalCase = Pick<MedicalCase, "title" | "deidentified_text" | "source_reference" | "research_notes"> & {
  structured_data: Record<string, string>;
};

export const getMedicalCases = (page = 1) => apiRequest<Page<MedicalCase>>(`/api/v1/research/cases/?page=${page}`);
export const createMedicalCase = (data: NewMedicalCase) =>
  apiRequest<MedicalCase>("/api/v1/research/cases/", { method: "POST", body: data });
export const deleteMedicalCase = (id: number) =>
  apiRequest<void>(`/api/v1/research/cases/${id}/`, { method: "DELETE" });
