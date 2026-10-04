export type ApiErrorBody = { code: string; message: string; details: unknown; requestId: string | null };
export class ApiError extends Error {
  constructor(message: string, readonly code: string, readonly details: unknown, readonly requestId: string | null, readonly status: number) {
    super(message); this.name = "ApiError";
  }
}
type RequestOptions = Omit<RequestInit, "body"> & { body?: unknown };
const unsafeMethods = new Set(["POST", "PUT", "PATCH", "DELETE"]);

async function readError(response: Response): Promise<ApiError> {
  const payload: unknown = await response.json().catch(() => null);
  const error = (payload as { error?: ApiErrorBody } | null)?.error;
  return new ApiError(
    typeof error?.message === "string" && error.message ? error.message : "服务器暂时无法处理请求，请稍后重试。",
    typeof error?.code === "string" && error.code ? error.code : "UNEXPECTED_RESPONSE",
    error?.details ?? null,
    typeof error?.requestId === "string" ? error.requestId : response.headers.get("X-Request-ID"),
    response.status,
  );
}

async function readJson(response: Response): Promise<unknown> {
  try { return await response.json(); }
  catch { throw new ApiError("平台返回了无法识别的响应，请稍后重试。", "INVALID_RESPONSE", null, response.headers.get("X-Request-ID"), response.status); }
}

async function getCsrfToken(): Promise<string> {
  let response: Response;
  try {
    response = await fetch("/api/v1/auth/csrf/", { credentials: "same-origin" });
  } catch {
    throw new ApiError("无法连接平台服务，请确认服务已启动后重试。", "NETWORK_ERROR", null, null, 0);
  }
  if (!response.ok) throw await readError(response);
  const payload = (await readJson(response)) as { csrfToken?: string } | null;
  if (typeof payload?.csrfToken !== "string" || !payload.csrfToken) throw new ApiError("无法建立安全会话，请刷新页面后重试。", "CSRF_TOKEN_MISSING", null, response.headers.get("X-Request-ID"), response.status);
  return payload.csrfToken;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body !== undefined && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const method = (options.method ?? "GET").toUpperCase();
  if (unsafeMethods.has(method) && !headers.has("X-CSRFToken")) {
    headers.set("X-CSRFToken", await getCsrfToken());
  }
  let response: Response;
  try {
    response = await fetch(path, {
      ...options,
      method,
      headers,
      credentials: "same-origin",
      body: options.body instanceof FormData ? options.body : options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch {
    throw new ApiError("无法连接平台服务，请确认服务已启动后重试。", "NETWORK_ERROR", null, null, 0);
  }
  if (response.status === 204) return undefined as T;
  if (!response.ok) throw await readError(response);
  return (await readJson(response)) as T;
}

export async function apiRequestBlob(path: string): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: "same-origin" });
  } catch {
    throw new ApiError("无法连接平台服务，请确认服务已启动后重试。", "NETWORK_ERROR", null, null, 0);
  }
  if (!response.ok) throw await readError(response);
  return response.blob();
}
