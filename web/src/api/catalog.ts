import { apiRequest } from "./client";
export type HomeStats = { counts: { herbs: number; compounds: number; targets: number; pathways: number } };
export const getHomeStats = () => apiRequest<HomeStats>("/api/v1/home-stats/");

export type ReactomeCatalogResult = {
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

export type EntityNeighborhood = {
  entity: KnowledgeEntity;
  relations: EvidenceRelation[];
  truncated: boolean;
};

export type HerbEvidenceEntity = {
  id: number;
  stableId: string;
  label: string;
  sourceSlug: string | null;
  sourceVersion: string | null;
};

export type HerbEvidenceRelation = {
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
  matches: HerbEvidenceEntity[];
  ambiguous: boolean;
  herbs: HerbEvidenceEntity[];
  compounds: HerbEvidenceEntity[];
  targets: HerbEvidenceEntity[];
  relations: HerbEvidenceRelation[];
  truncated: boolean;
};

export type HerbEvidenceSearch = {
  queryType: "herb" | "compound";
  results: HerbEvidenceItem[];
};

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
