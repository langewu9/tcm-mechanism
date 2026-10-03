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
  sourceQuery: string;
  matchedQueries: string[];
  componentChinese: string;
  componentEnglish: string;
  componentLatin: string;
};

export type ChemblNameMatch = {
  query: string;
  chinese: string;
  english: string;
  latin: string;
  matchedTerms: string;
  hitCount: number;
};

export type ChemblMoleculeSearch = {
  source: "ChEMBL";
  sourceVersion: string;
  releaseDate: string;
  query: string;
  queries: string[];
  resolvedQueries: string[];
  nameMatches: ChemblNameMatch[];
  aliasSource: string;
  aliasSourceCommit: string;
  failedQueries: string[];
  endpoint: string;
  retrievedAt: string;
  queriedTerms: number;
  resultLimit: number;
  totalCount: number;
  truncated: boolean;
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

export type ComponentCompareRow = {
  side?: "detected" | "reference";
  familyKey?: string;
  matchedTerms?: string;
  group?: string;
  normalizedKey?: string;
  input?: string;
  detectedInput?: string;
  referenceInput?: string;
  chinese?: string;
  english?: string;
  latin?: string;
  familyName?: string;
  detectedEnglish?: string;
  referenceEnglish?: string;
  status?: string;
};

export type ComponentComparison = {
  aliasSource: string;
  aliasSourceCommit: string;
  detected: ComponentCompareRow[];
  reference: ComponentCompareRow[];
  exactMatches: ComponentCompareRow[];
  detectedOnly: ComponentCompareRow[];
  referenceOnly: ComponentCompareRow[];
  familyMatches: ComponentCompareRow[];
  rows: ComponentCompareRow[];
  counts: {
    detected: number;
    reference: number;
    matched: number;
    detectedOnly: number;
    referenceOnly: number;
    familyMatches: number;
    matchRate: number;
  };
};

export const compareComponents = (detected: string, reference: string) =>
  apiRequest<ComponentComparison>("/api/v1/analysis/component-compare/", {
    method: "POST", body: { detected, reference },
  });
