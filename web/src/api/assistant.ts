import { apiRequest } from "./client";
import type { AnalysisTask } from "./datasets";

export type ResearchAssistantRequest = {
  mode?: "evidence";
  question: string;
  entityIds: number[];
  useModel: boolean;
  confirmModelSharing: boolean;
} | {
  mode: "scientist_hypothesis";
  question: string;
  disease: string;
  formula: string;
  focus: string;
  useModel: false;
  confirmModelSharing: false;
};

export const createResearchAssistantTask = (data: ResearchAssistantRequest) =>
  apiRequest<AnalysisTask>("/api/v1/research/assistant/", { method: "POST", body: data });
