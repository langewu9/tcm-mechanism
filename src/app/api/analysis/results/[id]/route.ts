import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { handleRouteError, jsonError, requireApiUser } from "@/lib/api";

export const runtime = "nodejs";

type Params = { params: Promise<{ id: string }> };

export async function GET(_request: Request, { params }: Params) {
  try {
    const user = await requireApiUser();
    const { id } = await params;
    const item = await prisma.analysisResult.findFirst({
      where: { id, task: user.role === "ADMIN" ? {} : { ownerId: user.id } },
      include: { task: { include: { medicalCase: true } } }
    });
    if (!item) return jsonError("分析结果不存在", 404);
    return NextResponse.json({ ok: true, item });
  } catch (error) {
    return handleRouteError(error);
  }
}
