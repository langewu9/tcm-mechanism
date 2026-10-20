import { apiRequest } from "./client";

export type AdminOverviewUser = {
  id: number;
  name: string;
  email: string;
  role: "ADMIN" | "RESEARCHER";
  is_active: boolean;
  date_joined: string;
  last_login: string | null;
  dataset_count: number;
  case_count: number;
  task_count: number;
};

export type AdminOverviewDataset = {
  id: number;
  name: string;
  owner_name: string;
  row_count: number;
  created_at: string;
};

export type AdminOverviewTask = {
  id: number;
  name: string;
  owner_name: string;
  task_type: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  created_at: string;
};

export type AdminOverview = {
  users: AdminOverviewUser[];
  datasets: AdminOverviewDataset[];
  tasks: AdminOverviewTask[];
};

export const getAdminOverview = () => apiRequest<AdminOverview>("/api/v1/admin/overview/");
