import { apiRequest } from "./client";
export type Session = { authenticated: boolean; user?: { id: number; username: string; isSuperuser: boolean } };
export type RegistrationResult = { status: "pending_approval"; message: string };
export const getSession = () => apiRequest<Session>("/api/v1/auth/session/");
export async function login(username: string, password: string) {
  return apiRequest<Session>("/api/v1/auth/session/", { method: "POST", body: { username, password } });
}
export function registerResearcher(username: string, email: string, password: string, password_confirmation: string) {
  return apiRequest<RegistrationResult>("/api/v1/auth/register/", {
    method: "POST",
    body: { username, email, password, password_confirmation },
  });
}
export const logout = () => apiRequest<void>("/api/v1/auth/session/", { method: "DELETE" });
