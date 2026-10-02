import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { handleRouteError, requireApiAdmin } from "@/lib/api";

export const runtime = "nodejs";

export async function GET() {
  try {
    await requireApiAdmin();
    const items = await prisma.user.findMany({
      orderBy: { createdAt: "desc" },
      select: {
        id: true,
        name: true,
        email: true,
        role: true,
        createdAt: true,
        updatedAt: true,
        _count: { select: { datasets: true, cases: true, tasks: true } }
      }
    });
    return NextResponse.json({ ok: true, items });
  } catch (error) {
    return handleRouteError(error);
  }
}
