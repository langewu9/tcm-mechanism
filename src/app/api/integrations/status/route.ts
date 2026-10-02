import { NextResponse } from "next/server";
import { handleRouteError, requireApiUser } from "@/lib/api";
import { FASTAPI_BASE_URL, fastApiGet } from "@/lib/fastapi";

export const runtime = "nodejs";

export async function GET() {
  try {
    await requireApiUser();
    const [health, sources, qwenStatus, qwenModels] = await Promise.all([
      fastApiGet("/api/health", 8000),
      fastApiGet("/api/sources", 8000),
      fastApiGet("/api/qwen/status", 8000),
      fastApiGet("/api/qwen/models", 8000)
    ]);

    return NextResponse.json({
      ok: health.ok,
      fastapiBaseUrl: FASTAPI_BASE_URL,
      checkedAt: new Date().toISOString(),
      services: {
        health,
        sources,
        qwenStatus,
        qwenModels
      }
    });
  } catch (error) {
    return handleRouteError(error);
  }
}
