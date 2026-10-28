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
  refresh_interval_hours?: number | null;
  last_preview_requested_at?: string | null;
  scheduled_previews_enabled?: boolean;
  latest_run_status: string | null;
  latest_run_at: string | null;
  connector_type: "reactome-catalog" | "sqlite-herb-compound-target" | "uniprot-human-catalog" | "pubchem-compound-catalog" | "string-human-identifier-crosswalk" | string;
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
    connector?: string;
    actorCommand?: string;
    rows?: number;
    relations?: number;
    quarantined?: number;
    basedOn?: number;
    sourceVersion?: string | null;
    releaseVersion?: string;
    checksumSha256?: string;
    totalRecords?: number;
    wouldCreate?: number;
    wouldUpdate?: number;
    unchanged?: number;
    wouldRetire?: number;
    totalRows?: number;
    uniqueHerbs?: number;
    uniqueCompounds?: number;
    uniqueTargets?: number;
    uniqueDiseases?: number;
    relationships?: number;
    relationshipsCreated?: number;
    relationshipsUpdated?: number;
    databaseFile?: string;
    table?: string;
    tableRowCounts?: Record<string, number>;
    fileBytes?: number;
    pageCount?: number;
    releaseDate?: string | null;
    geneSymbolsMappedToExistingTargets?: number;
    ambiguousLocalGeneSymbols?: number;
    localHumanEntityCount?: number;
    submittedQueryCount?: number;
    unmappedQueries?: number;
    ambiguousLocalEntities?: number;
    ambiguousStringIds?: number;
    identifierConflicts?: number;
    conflictFingerprint?: string;
    previewRecords?: Array<{
      compound?: string;
      stableId?: string;
      cid?: string;
      molecularFormula?: string;
      molecularWeight?: string;
      inchiKey?: string;
      iupacName?: string;
      entityStableId?: string;
      query?: string;
      stringId?: string;
      preferredName?: string;
      annotation?: string;
    }>;
    previewRecordsTruncated?: boolean;
  };
  requested_by: number | null;
  requested_by_username: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
};

export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };

export const getAdminDataSources = () => apiRequest<Page<AdminDataSource>>("/api/v1/admin/sources/");
export const deleteDataSource = (sourceId: number) =>
  apiRequest<void>(`/api/v1/admin/sources/${sourceId}/`, { method: "DELETE" });
export const updateDataSourceSettings = (sourceId: number, input: {
  enabled: boolean; refresh_interval_hours: number | null;
}) => apiRequest<AdminDataSource>(`/api/v1/admin/sources/${sourceId}/`, { method: "PATCH", body: input });
export const getSyncRuns = () => apiRequest<Page<SyncRun>>("/api/v1/admin/sync-runs/");
export const previewDataSourceSync = (sourceId: number) =>
  apiRequest<{ run: SyncRun }>(`/api/v1/admin/sources/${sourceId}/sync/`, { method: "POST", body: {} });
export const applySyncPreview = (runId: number) =>
  apiRequest<{ run: SyncRun }>(`/api/v1/admin/sync-runs/${runId}/apply/`, { method: "POST", body: {} });
export const createSQLiteDataSource = (input: {
  name: string;
  description?: string;
  databaseFile: string;
  table: string;
  herbColumn: string;
  compoundColumn: string;
  targetColumn: string;
  diseaseTargetTable?: string;
  diseaseColumn?: string;
  diseaseTargetColumn?: string;
  diseaseSourceColumn?: string;
  diseaseHerbTargetTable?: string;
  diseaseHerbColumn?: string;
  diseaseHerbHerbColumn?: string;
  diseaseHerbTargetColumn?: string;
}) => apiRequest<AdminDataSource>("/api/v1/admin/sources/", { method: "POST", body: input });
export const testSQLiteDataSource = (sourceId: number) => apiRequest<{
  ok: true;
  rowCount: number;
  fileBytes: number;
  checksumSha256: string;
  columns: string[];
  mapping: Record<string, string>;
  tableRowCounts: Record<string, number>;
}>(`/api/v1/admin/sources/${sourceId}/test/`, { method: "POST", body: {} });
