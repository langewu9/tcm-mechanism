import { apiRequest } from "./client";
import type { AnalysisTask } from "./datasets";
export type CatalogSnapshotQuery = { queryType: "herb" | "compound" | "disease" | "pathway" | "entity" | "comparison"; queries?: string[]; entityId?: number; detected?: string; reference?: string; expectedSha256: string };
export const createCatalogSnapshot = (input: CatalogSnapshotQuery) => apiRequest<AnalysisTask>("/api/v1/catalog/visualization-snapshots/", { method: "POST", body: input });
export type HomeStats = { counts: { herbs: number; compounds: number; targets: number; pathways: number } };
export const getHomeStats = () => apiRequest<HomeStats>("/api/v1/home-stats/");

export type ReactomeCatalogResult = {
  evidenceSha256?: string;
  query: string; catalogTotal: number; matchedTotal: number; maxItems: number; truncated: boolean;
  sourceCode: string; warnings: string[];
  sources: Array<{ sourceSlug: string; sourceVersion: string; checksumSha256: string }>;
  items: Array<{
    entityId: number; stableId: string; name: string; species: string; sourceVersion: string;
    checksumSha256: string; sourceUrl: string; lastSyncedAt: string; targetAnnotations: number;
    annotationSources: Array<{ sourceSlug: string; sourceVersion: string }>;
    enrichmentRecords: number | null;
  }>;
};
export const searchReactomeCatalog = (query: string) => apiRequest<ReactomeCatalogResult>(
  `/api/v1/catalog/pathways/reactome/?${new URLSearchParams({ query })}`,
);

export type DashboardTask = {
  analysis_kind?: string;
  id: number;
  title: string;
  summary: string;
  task_type: "proteomics" | "case_link" | "network" | "visualization" | "research_assistant" | "text_analysis";
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  created_at: string;
};
export type ResearchDashboard = {
  stats: { datasets: number; cases: number; tasks: number; herbs: number; compounds: number; targets: number; pathways: number };
  latest_tasks: DashboardTask[];
};
export const getResearchDashboard = () => apiRequest<ResearchDashboard>("/api/v1/research/dashboard/");

export type KnowledgeEntity = {
  id: number;
  entity_type: string;
  stable_id: string;
  label: string;
  organism: string;
  source_release: number | null;
  source_slug: string | null;
  source_version: string | null;
  synonyms: string[];
  metadata: Record<string, unknown>;
  matchedQueries?: string[];
};

export type CatalogPage<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export type KnowledgeSearchPage = CatalogPage<KnowledgeEntity> & {
  query?: string;
  expandedQueries?: string[];
  aliasSource?: string;
  aliasSourceCommit?: string;
};

export type EvidenceRelation = {
  id: number;
  subject: number;
  subject_label: string;
  object: number;
  object_label: string;
  relation_type: string;
  evidence_type: string;
  score: string | null;
  evidence_text: string;
  organism: string;
  source_slug: string;
  source_version: string;
  observed_at: string | null;
};

export type DataQualityNotice = { source: string; version: string; quarantinedRows: number; verifiedTargetIds: number; message: string };

export type EntityNeighborhood = {
  compoundProperties?: { source: string; sourceVersion: string; sourceCompoundId: string; values: Record<string, number | null>; conflicts: string[]; fieldSourceRecords: Record<string, string>; sourceRecordId: string | null; note: string } | null;
  evidenceSha256?: string;
  entity: KnowledgeEntity;
  relations: EvidenceRelation[];
  truncated: boolean;
};

export type HerbEvidenceEntity = {
  id: number;
  stableId: string;
  label: string;
  sourceReleaseId?: number | null;
  sourceSlug: string | null;
  sourceVersion: string | null;
};

export type HerbEvidenceRelation = {
  id?: number;
  relationId?: number; subjectId?: number; objectId?: number; sourceReleaseId?: number;
  subject: string;
  object: string;
  subjectType: string;
  objectType: string;
  relationType: string;
  evidenceType: string;
  sourceSlug: string;
  sourceVersion: string;
  sourceRecordId: string;
  score: number | null;
};

export type HerbEvidenceItem = {
  query: string;
  searchedNames?: string[];
  resolution?: {
    version: string;
    strategy: string;
    expandedNames: string[];
    identityMerged: boolean;
    authorityIdentityVerified: boolean;
    aliasSource?: string;
    aliasSourceCommit?: string;
    warnings: string[];
    matchEvidence: Array<{ entityId: number; stableId: string; originalLabel: string; sourceEntityId: string | null;
      sourceSlug: string | null; sourceReleaseId: number | null; sourceVersion: string | null; basis: Array<Record<string, unknown>> }>;
  };
  matches: HerbEvidenceEntity[];
  ambiguous: boolean;
  herbs: HerbEvidenceEntity[];
  compounds: HerbEvidenceEntity[];
  targets: HerbEvidenceEntity[];
  relations: HerbEvidenceRelation[];
  truncated: boolean;
};

export type HerbEvidenceSearch = {
  dataQuality?: DataQualityNotice[];
  evidenceSha256?: string;
  queryType: "herb" | "compound";
  resultSha256: string;
  results: HerbEvidenceItem[];
};

export type DiseaseEvidenceLink = {
  disease: string;
  herb: string;
  target: string;
  relationType: string;
  sourceSlug: string;
  sourceVersion: string;
  sourceRecordId: string;
};

export type DiseaseEvidenceSearch = {
  dataQuality?: DataQualityNotice[];
  evidenceSha256?: string;
  resultSha256: string;
  query: string;
  expandedQueries: string[];
  aliasSource: string;
  aliasSourceCommit: string;
  matches: HerbEvidenceEntity[];
  ambiguous: boolean;
  herbs: HerbEvidenceEntity[];
  targets: HerbEvidenceEntity[];
  relations: HerbEvidenceRelation[];
  links: DiseaseEvidenceLink[];
  counts: { diseases: number; herbs: number; targets: number; links: number; relations: number };
  truncated: boolean;
  limits: { maxMatches: number; maxRelations: number };
};

export function searchDiseaseEvidence(query: string) {
  return apiRequest<DiseaseEvidenceSearch>(`/api/v1/catalog/diseases/evidence-search/?${new URLSearchParams({ query })}`);
}

export function saveDiseaseEvidenceAnalysis(evidence: DiseaseEvidenceSearch) {
  return apiRequest<AnalysisTask>("/api/v1/catalog/diseases/evidence-analyses/", {
    method: "POST", body: { query: evidence.query, expectedResultSha256: evidence.resultSha256 },
  });
}

export function searchCatalogEntities(query: string, entityType: string, page = 1) {
  if (entityType === "disease") {
    const params = new URLSearchParams({ query, page: String(page) });
    return apiRequest<KnowledgeSearchPage>(`/api/v1/catalog/diseases/alias-search/?${params}`);
  }
  const params = new URLSearchParams({ search: query, page: String(page) });
  if (entityType) params.set("entity_type", entityType);
  return apiRequest<KnowledgeSearchPage>(`/api/v1/catalog/entities/?${params}`);
}

export function getEntityNeighborhood(entityId: number) {
  return apiRequest<EntityNeighborhood>(`/api/v1/catalog/entities/${entityId}/neighborhood/`);
}

export function searchHerbComponentEvidence(queryType: HerbEvidenceSearch["queryType"], queries: string[]) {
  return apiRequest<HerbEvidenceSearch>("/api/v1/catalog/herb-evidence/batch/", {
    method: "POST",
    body: { queryType, queries },
  });
}

export function saveHerbEvidenceAnalysis(evidence: HerbEvidenceSearch) {
  return apiRequest<AnalysisTask>("/api/v1/catalog/herb-evidence/analyses/", {
    method: "POST",
    body: { queryType: evidence.queryType, queries: evidence.results.map(item => item.query), expectedResultSha256: evidence.resultSha256, complete: true },
  });
}
