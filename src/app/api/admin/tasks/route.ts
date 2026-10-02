import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { handleRouteError, requireApiAdmin } from "@/lib/api";

export const runtime = "nodejs";

export async function GET() {
  try {
    await requireApiAdmin();
    const items = await prisma.analysisTask.findMany({
      orderBy: { createdAt: "desc" },
      include: { owner: { select: { name: true, email: true } }, result: true }
    });
    return NextResponse.json({ ok: true, items });
  } catch (error) {
    return handleRouteError(error);
  }
}
