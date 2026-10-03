import { apiRequest } from "./client";

export type IntegrationTarget = "qwen" | "disease" | "herb" | "component" | "chembl" | "intersection" | "compare" | "scientist";

export type IntegrationResult = {
  ok: boolean;
  status: number;
  url: string;
  data?: unknown;
  error?: string;
  elapsedMs: number;
};

export type IntegrationStatus = {
  ok: boolean;
  checkedAt: string;
  elapsedMs: number;
  services: Record<string, {
    ok: boolean;
    status: number;
    url: string;
    data?: unknown;
    error?: string;
  }>;
};

export const getIntegrationStatus = () =>
  apiRequest<IntegrationStatus>("/api/v1/admin/integrations/status/");

export const testIntegration = (target: IntegrationTarget, consent = false) =>
  apiRequest<{ target: IntegrationTarget; result: IntegrationResult }>("/api/v1/admin/integrations/test/", {
    method: "POST",
    body: { target, consent },
  });
