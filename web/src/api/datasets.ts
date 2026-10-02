import { apiRequest } from "./client";

export type ResearchDataset = {
  id: number;
  owner_id: number;
  owner_username: string;
  name: string;
  description: string;
  original_filename: string;
  content_sha256: string;
  byte_size: number;
  columns_mapping: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type DatasetPage = { count: number; next: string | null; previous: string | null; results: ResearchDataset[] };

export const getDatasets = (page = 1) => apiRequest<DatasetPage>(`/api/v1/research/datasets/?page=${page}`);
export const uploadDataset = (data: FormData) =>
  apiRequest<ResearchDataset>("/api/v1/research/datasets/", { method: "POST", body: data });
export const deleteDataset = (id: number) =>
  apiRequest<void>(`/api/v1/research/datasets/${id}/`, { method: "DELETE" });
