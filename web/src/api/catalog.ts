import { apiRequest } from "./client";
export type HomeStats = { counts: { herbs: number; compounds: number; targets: number; pathways: number } };
export const getHomeStats = () => apiRequest<HomeStats>("/api/v1/home-stats/");

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
};

export type CatalogPage<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
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

export function searchCatalogEntities(query: string, entityType: string, page = 1) {
  const params = new URLSearchParams({ search: query, page: String(page) });
  if (entityType) params.set("entity_type", entityType);
  return apiRequest<CatalogPage<KnowledgeEntity>>(`/api/v1/catalog/entities/?${params}`);
}

export function getEntityNeighborhood(entityId: number) {
  return apiRequest<EntityNeighborhood>(`/api/v1/catalog/entities/${entityId}/neighborhood/`);
}
