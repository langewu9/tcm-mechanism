import { apiRequest, apiRequestBlob } from "./client";

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

export type ProteomicsResult = {
  algorithmVersion: string;
  dataset: { id: number; sha256: string; originalFilename: string; rowCount: number; sheetName: string };
  columns: string[];
  mapping: Record<string, string>;
  thresholds: { log2FcMin: number; fdrMax: number; pValueMax: number };
  qc: {
    inputRowCount: number;
    rowsWithIdentifier: number;
    missingIdentifierCount: number;
    duplicateIdentifierCount: number;
    invalidNumericValueRowCount: number;
    excludedRowCount: number;
    excludedReasonCounts: Record<string, number>;
    selectedRowCount: number;
    databaseMappedCount: number;
    unverifiedSymbolCount: number;
    unmappedLabelCount: number;
  };
  warnings: string[];
  summary: {
    selectedRowCount: number;
    uniqueLabelCount: number;
    normalizedCount: number;
    databaseMappedCount: number;
    unverifiedSymbolCount: number;
    unmappedCount: number;
    localAnnotatedCount: number;
    referenceCount: number;
    candidateOverlapCount: number;
    pathwayCount: number;
    enrichmentMode: string;
    enrichmentNote: string;
    externalMappedCount?: number;
    reactomePathwayCount?: number;
    goKeggTermCount?: number;
  };
  externalReactome?: {
    status: string;
    organism: string;
    source: string;
    sourceVersion: string | null;
    reactomeToken: string | null;
    pathways: Array<{
      stableId: string;
      name: string;
      species: string;
      matchedEntities: number;
      totalEntities: number | null;
      coverage: number | null;
      pValue: number | null;
      fdr: number | null;
    }>;
    mappings: Array<{ query: string; symbol: string; name: string | null; entrezGeneId: string | null }>;
    ambiguousIdentifiers: string[];
    unmappedIdentifiers: string[];
    rejectedIdentifiers: string[];
    identifiersNotFound?: number;
    pathwaysFound?: number;
    submittedIdentifierCount?: number;
    truncatedLabelCount?: number;
    truncatedIdentifierCount?: number;
    rejectedIdentifierCount?: number;
    failureStage?: string;
  };
  externalString?: {
    status: string;
    organism: string;
    source: string;
    sourceVersion: string | null;
    sourceVersionKnown: boolean;
    networkType: "physical";
    requiredScore: number;
    inputCount: number;
    submittedIdentifierCount: number;
    truncatedIdentifierCount: number;
    rejectedIdentifierCount?: number;
    interactionCount: number;
    nodes: Array<{ id: string; label: string; type: string; degree?: number; betweenness?: number }>;
    edges: Array<{ source: string; target: string; score: number; scoreOutOf1000: number }>;
    centralityMethod?: string;
    consentRecorded: boolean;
    failureStage?: string;
  };
  externalGProfiler?: {
    status: string;
    organism: string;
    source: string;
    sourceVersion: string | null;
    sourceRelease?: number;
    dataVersions: Record<string, unknown>;
    sources: string[];
    queryCount: number;
    queryTruncatedCount: number;
    backgroundCount: number;
    backgroundType: string;
    threshold: number;
    correctionMethod: string;
    rawPValuesReturned: boolean;
    terms: Array<{
      termId: string;
      name: string;
      source: string;
      pValue: number | null;
      adjustedPValue: number;
      correctionMethod: string;
      intersectionSize: number | null;
      querySize: number | null;
      geneRatio: number | null;
      termSize: number | null;
      effectiveDomainSize: number | null;
      precision: number | null;
      recall: number | null;
      matchedIdentifiers: string[];
    }>;
    consentRecorded: boolean;
    failureStage?: string;
  };
  rows: Array<{
    index: number;
    originalLabel: string;
    proteinName: string | null;
    symbol: string | null;
    mappingStatus: string;
    mappingSource: string;
    log2FoldChange: number | null;
    pValue: number | null;
    fdr: number | null;
    direction: string | null;
  }>;
  previewTruncated: boolean;
  unmapped: string[];
  unmappedTruncated: boolean;
  topNodes: Array<{
    symbol: string;
    degree: number;
    log2FoldChange: number | null;
    fdr: number | null;
    direction: string | null;
    pathways: string[];
    mappingStatus: string;
  }>;
  pathways: Array<{ name: string; stableId: string; source: string; version: string }>;
  validation: { referenceTargets: string[]; overlap: string[]; proteomicsOnly: string[]; referenceOnly: string[] };
  network: { nodes: Array<{ id: string; label: string; type: string }>; links: Array<Record<string, unknown>> };
};

export type AnalysisTask = {
  id: number;
  task_type: "proteomics" | "case_link" | "network" | "visualization";
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  dataset: number | null;
  medical_case: number | null;
  input_parameters: Record<string, unknown>;
  source_releases: number[];
  progress: number;
  result: ProteomicsResult | Record<string, unknown>;
  error_summary: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type AnalysisTaskPage = { count: number; next: string | null; previous: string | null; results: AnalysisTask[] };
export type ProteomicsRow = {
  row_index: number;
  original_label: string;
  protein_name: string;
  normalized_symbol: string;
  mapping_status: string;
  mapping_source: string;
  matched_entity: number | null;
  matched_entity_label: string | null;
  log2_fold_change: number | null;
  p_value: number | null;
  fdr: number | null;
  direction: string;
  selected: boolean;
  exclusion_reasons: string[];
  qc_warnings: string[];
};
export type ProteomicsRowPage = { count: number; next: string | null; previous: string | null; results: ProteomicsRow[] };

export type ProteomicsRunRequest = {
  name?: string;
  externalReactome?: boolean;
  externalString?: boolean;
  externalGProfiler?: boolean;
  stringRequiredScore?: number;
  mapping?: {
    geneColumn?: string;
    proteinColumn?: string;
    log2FcColumn?: string;
    pValueColumn?: string;
    fdrColumn?: string;
    directionColumn?: string;
  };
  thresholds?: { log2FcMin?: number; fdrMax?: number; pValueMax?: number };
  referenceTargets?: string[];
};

export const getDatasets = (page = 1) => apiRequest<DatasetPage>(`/api/v1/research/datasets/?page=${page}`);
export const uploadDataset = (data: FormData) =>
  apiRequest<ResearchDataset>("/api/v1/research/datasets/", { method: "POST", body: data });
export const deleteDataset = (id: number) =>
  apiRequest<void>(`/api/v1/research/datasets/${id}/`, { method: "DELETE" });
export const runProteomicsAnalysis = (datasetId: number, request: ProteomicsRunRequest) =>
  apiRequest<AnalysisTask>(`/api/v1/research/datasets/${datasetId}/analyze/`, { method: "POST", body: request });
export const getAnalysisTasks = (page = 1) =>
  apiRequest<AnalysisTaskPage>(`/api/v1/research/analysis-tasks/?page=${page}`);
export const getAnalysisTask = (id: number) =>
  apiRequest<AnalysisTask>(`/api/v1/research/analysis-tasks/${id}/`);
export const getProteomicsRows = (taskId: number, page = 1) =>
  apiRequest<ProteomicsRowPage>(`/api/v1/research/analysis-tasks/${taskId}/rows/?page=${page}`);
export const exportProteomicsResults = (taskId: number, format: "csv" | "xlsx") =>
  apiRequestBlob(`/api/v1/research/analysis-tasks/${taskId}/export/?file_format=${format}`);
