import { apiRequest } from "./client";
import type { AnalysisTask } from "./datasets";

export type NetworkPharmacologyResult = {
  taskId: number;
  summary: {
    herb: string;
    herbs: string[];
    matchedHerbs: string[];
    unmatchedHerbs: string[];
    disease: string;
    matchedDiseases: string[];
    unmatchedDiseases: string[];
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
  network: { nodes: Array<{ id: string; label: string; type: string }>; links: Array<{ source: string; target: string; relation: string; sourceRecordId: string; sourceSlug: string }> };
  charts: { overlap: Array<{ name: string; value: number }>; components: Array<{ name: string; targets: number }>; pathways: Array<{ name: string; targets: number }> };
  limits: { targetsTruncated: boolean; linksTruncated: boolean };
};

export const runNetworkPharmacology = (input: { herb: string; disease: string }) =>
  apiRequest<NetworkPharmacologyResult>("/api/v1/analysis/network-pharmacology/", { method: "POST", body: input });

export const runReactomeEnrichment = (targets: string[]) =>
  apiRequest<AnalysisTask>("/api/v1/analysis/pathway-enrichment/", { method: "POST", body: { targets, consent: true } });

export const runStringNetwork = (targets: string[], required_score: number) =>
  apiRequest<AnalysisTask>("/api/v1/analysis/string-network/", { method: "POST", body: { targets, required_score, consent: true } });
