import { apiRequest } from "./client";
export type Session = { authenticated: boolean; user?: { id: number; username: string; isSuperuser: boolean } };
type CsrfToken = { csrfToken: string };
export const getSession = () => apiRequest<Session>("/api/v1/auth/session/");
export async function login(username: string, password: string) {
  const { csrfToken } = await apiRequest<CsrfToken>("/api/v1/auth/csrf/");
  return apiRequest<Session>("/api/v1/auth/session/", { method: "POST", headers: { "X-CSRFToken": csrfToken }, body: { username, password } });
}
