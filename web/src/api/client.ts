export type ApiErrorBody = { code: string; message: string; details: unknown; requestId: string | null };
export class ApiError extends Error {
  constructor(message: string, readonly code: string, readonly details: unknown, readonly requestId: string | null, readonly status: number) {
    super(message); this.name = "ApiError";
  }
}
type RequestOptions = Omit<RequestInit, "body"> & { body?: unknown };
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body !== undefined && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(path, {
    ...options, headers, credentials: "same-origin",
    body: options.body instanceof FormData ? options.body : options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (response.status === 204) return undefined as T;
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (payload as { error?: ApiErrorBody } | null)?.error;
    throw new ApiError(error?.message ?? "服务器暂时无法处理请求，请稍后重试。", error?.code ?? "UNEXPECTED_RESPONSE", error?.details ?? null, error?.requestId ?? response.headers.get("X-Request-ID"), response.status);
  }
  return payload as T;
}
