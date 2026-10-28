import { apiRequest } from "./client";
import type { AnalysisTask } from "./datasets";

export type ResearchAssistantRequest = {
  question: string;
  entityIds: number[];
  useModel: boolean;
  confirmModelSharing: boolean;
  caseIds?: number[];
  caseCategory?: string;
};

export const createResearchAssistantTask = (data: ResearchAssistantRequest) =>
  apiRequest<AnalysisTask>("/api/v1/research/assistant/", { method: "POST", body: data });
