import { apiRequest } from "./client";

export type AdminDataSource = {
  id: number;
  slug: string;
  name: string;
  description: string;
  access_mode: string;
  documentation_url: string;
  license_note: string;
  enabled: boolean;
  last_success_at: string | null;
  latest_run_status: string | null;
  latest_run_at: string | null;
};

export type SyncRun = {
  id: number;
  source: number;
  source_slug: string;
  source_name: string;
  release: number | null;
  release_version: string | null;
  release_checksum: string | null;
  status: "pending" | "running" | "succeeded" | "failed";
  trigger: "manual" | "scheduled";
  records_seen: number;
  records_created: number;
  records_updated: number;
  records_retired: number;
  error_summary: string;
  preview_summary: {
    mode?: "preview" | "apply";
    basedOn?: number;
    sourceVersion?: string | null;
    releaseVersion?: string;
    checksumSha256?: string;
    totalRecords?: number;
    wouldCreate?: number;
    wouldUpdate?: number;
    unchanged?: number;
    wouldRetire?: number;
  };
  requested_by: number | null;
  requested_by_username: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
};

export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };

export const getAdminDataSources = () => apiRequest<Page<AdminDataSource>>("/api/v1/admin/sources/");
export const getSyncRuns = () => apiRequest<Page<SyncRun>>("/api/v1/admin/sync-runs/");
export const previewDataSourceSync = (sourceId: number) =>
  apiRequest<{ run: SyncRun }>(`/api/v1/admin/sources/${sourceId}/sync/`, { method: "POST", body: {} });
export const applySyncPreview = (runId: number) =>
  apiRequest<{ run: SyncRun }>(`/api/v1/admin/sync-runs/${runId}/apply/`, { method: "POST", body: {} });
