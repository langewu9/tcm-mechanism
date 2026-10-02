import { apiRequest } from "./client";
export type Session = { authenticated: boolean; user?: { id: number; username: string; isSuperuser: boolean } };
export const getSession = () => apiRequest<Session>("/api/v1/auth/session/");
export async function login(username: string, password: string) {
  return apiRequest<Session>("/api/v1/auth/session/", { method: "POST", body: { username, password } });
}
export const logout = () => apiRequest<void>("/api/v1/auth/session/", { method: "DELETE" });
