import { apiRequest } from "./client";
export type HomeStats = { counts: { herbs: number; compounds: number; targets: number; pathways: number } };
export const getHomeStats = () => apiRequest<HomeStats>("/api/v1/home-stats/");
