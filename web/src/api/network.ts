import { apiRequest } from "./client";
import type { AnalysisTask } from "./datasets";
import type { DataQualityNotice } from "./catalog";

export type NetworkRawTable = "herbLinks" | "diseaseTargets" | "diseaseHerbLinks" | "directDiseaseHerbLinks";

export type TargetIdentityRecord = { entityId: number; label: string; source: string; originalTaxon: string; status: string; method: string; masterKey: string | null; geneKey: string | null };
export type TargetIdentityOverlap = { key: string; label: string; taxon: string; herbRecords: TargetIdentityRecord[]; diseaseRecords: TargetIdentityRecord[]; recordCounts: { herb: number; disease: number } };
export type TargetIdentityResult = { available: boolean; version: string; comparisonVersion?: string; reason?: string; referenceVersion?: string; referenceSha256?: string; referenceTaxon?: string; releaseId?: number;
  coverage?: { scope: string; rawRowLimitsApplied: boolean };
  herb?: { records: number; verifiedRecords: number; pendingRecords: number; geneUnresolvedRecords?: number; genes: number; proteins: number; statuses: Record<string, number> };
  disease?: { records: number; verifiedRecords: number; pendingRecords: number; geneUnresolvedRecords?: number; genes: number; proteins: number; statuses: Record<string, number> };
  verifiedGeneIntersectionCount?: number; verifiedProteinIntersectionCount?: number; pendingGeneOverlapCount?: number;
  geneIntersections?: TargetIdentityOverlap[]; proteinIntersections?: TargetIdentityOverlap[]; pendingCandidates?: TargetIdentityOverlap[]; pendingRowsTruncated?: boolean;
};

export type NetworkPharmacologyResult = {
  dataQuality?: DataQualityNotice[];
  targetIdentity?: TargetIdentityResult;
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
    matchedDiseases: string[];
    unmatchedDiseases: string[];
    diseaseResolution?: {
      status: "exact" | "alias" | "needs_selection" | "unmatched";
      input: string;
      resolvedTerms: string[];
      aliasVersion: string;
      entitiesTruncated: boolean;
      candidates: Array<{ label: string; sourceSlugs: string[] }>;
    };
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
    structuralRowsCollapsed?: boolean;
    structuralEvidencePolicy?: string;
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

export const runNetworkPharmacology = (input: { herb: string; disease: string; source_case_id?: number; source_candidate_id?: number }) =>
  apiRequest<NetworkPharmacologyResult>("/api/v1/analysis/network-pharmacology/", { method: "POST", body: input });

export const runReactomeEnrichment = (sourceTaskId: number) =>
  apiRequest<AnalysisTask>("/api/v1/analysis/pathway-enrichment/", { method: "POST", body: { source_task_id: sourceTaskId, consent: true } });

export const runStringNetwork = (sourceTaskId: number, required_score: number) =>
  apiRequest<AnalysisTask>("/api/v1/analysis/string-network/", { method: "POST", body: { source_task_id: sourceTaskId, required_score, consent: true } });

export const createVisualization = (taskId: number, chartKey: string) =>
  apiRequest<AnalysisTask>(`/api/v1/research/analysis-tasks/${taskId}/visualizations/`, { method: "POST", body: { chartKey } });
