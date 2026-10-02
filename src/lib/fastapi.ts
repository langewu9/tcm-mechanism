export const FASTAPI_BASE_URL = (process.env.NEXT_PUBLIC_FASTAPI_BASE_URL || "http://127.0.0.1:8010").replace(/\/$/, "");

export type FastApiResult<T = unknown> = {
  ok: boolean;
  status: number;
  url: string;
  data: T | null;
  error?: string;
  elapsedMs: number;
};

export async function fastApiFetch<T = unknown>(
  path: string,
  init: RequestInit = {},
  timeoutMs = 15000
): Promise<FastApiResult<T>> {
  const startedAt = Date.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const url = `${FASTAPI_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;

  try {
    const response = await fetch(url, {
      ...init,
      headers: {
        "content-type": "application/json",
        ...(init.headers || {})
      },
      cache: "no-store",
      signal: controller.signal
    });
    const text = await response.text();
    let data: T | null = null;
    try {
      data = text ? (JSON.parse(text) as T) : null;
    } catch {
      data = { raw: text } as T;
    }
    return {
      ok: response.ok,
      status: response.status,
      url,
      data,
      elapsedMs: Date.now() - startedAt
    };
  } catch (error) {
    return {
      ok: false,
      status: 0,
      url,
      data: null,
      error: error instanceof Error ? error.message : String(error),
      elapsedMs: Date.now() - startedAt
    };
  } finally {
    clearTimeout(timer);
  }
}

export async function fastApiGet<T = unknown>(path: string, timeoutMs?: number) {
  return fastApiFetch<T>(path, { method: "GET" }, timeoutMs);
}

export async function fastApiPost<T = unknown>(path: string, body: unknown, timeoutMs?: number) {
  return fastApiFetch<T>(
    path,
    {
      method: "POST",
      body: JSON.stringify(body)
    },
    timeoutMs
  );
}
