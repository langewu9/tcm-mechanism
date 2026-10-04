import { apiRequest } from "./client";
export type Session = { authenticated: boolean; user?: { id: number; username: string; name?: string; email?: string; isSuperuser: boolean } };
export type RegistrationResult = { status: "pending_verification"; message: string };
export type EmailVerificationResult = { status: "verified" | "already_verified"; accountActive: boolean; message: string };
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
export function verifyEmail(token: string) {
  return apiRequest<EmailVerificationResult>("/api/v1/auth/verify-email/", { method: "POST", body: { token } });
}
export function resendVerificationEmail(email: string) {
  return apiRequest<{ status: "accepted"; message: string }>("/api/v1/auth/resend-verification/", { method: "POST", body: { email } });
}
export const logout = () => apiRequest<void>("/api/v1/auth/session/", { method: "DELETE" });
