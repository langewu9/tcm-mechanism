import { apiRequest } from "./client";

export type ChemblMolecule = {
  chemblId: string;
  preferredName: string;
  moleculeType: string;
  maxPhase: string;
  firstApproval: string;
  naturalProduct: 0 | 1 | null;
  canonicalSmiles: string;
  recordUrl: string;
};

export type ChemblMoleculeSearch = {
  source: "ChEMBL";
  sourceVersion: string;
  releaseDate: string;
  query: string;
  endpoint: string;
  retrievedAt: string;
  limit: number;
  results: ChemblMolecule[];
};

export type ChemblActivity = {
  activityId: number | null;
  standardType: string;
  relation: string;
  value: string;
  units: string;
  pchemblValue: string;
  targetId: string;
  targetName: string;
  assayId: string;
  assayDescription: string;
  assayType: string;
  documentId: string;
};

export type ChemblActivitySearch = {
  source: "ChEMBL";
  sourceVersion: string;
  releaseDate: string;
  chemblId: string;
  endpoint: string;
  retrievedAt: string;
  resultLimit: number;
  totalCount: number;
  truncated: boolean;
  results: ChemblActivity[];
};

export const searchChemblMolecules = (query: string, consent: boolean) =>
  apiRequest<ChemblMoleculeSearch>("/api/v1/analysis/chembl/molecules/", {
    method: "POST", body: { query, consent },
  });

export const searchChemblActivities = (chemblId: string, consent: boolean) =>
  apiRequest<ChemblActivitySearch>("/api/v1/analysis/chembl/activities/", {
    method: "POST", body: { chemblId, consent },
  });
