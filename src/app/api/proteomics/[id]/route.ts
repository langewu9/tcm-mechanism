import { NextResponse } from "next/server";

import { handleRouteError, requireApiUser } from "@/lib/api";
import { prisma } from "@/lib/prisma";

export const runtime = "nodejs";

type Params = { params: Promise<{ id: string }> };

export async function GET(_request: Request, { params }: Params) {
  try {
    const user = await requireApiUser();
    const { id } = await params;
    const item = await prisma.proteomicsAnalysis.findFirst({
      where: { id, ...(user.role === "ADMIN" ? {} : { ownerId: user.id }) },
      include: { dataset: true }
    });
    if (!item) return NextResponse.json({ ok: false, error: "分析结果不存在或无权限" }, { status: 404 });
    return NextResponse.json({ ok: true, item: { ...item, result: JSON.parse(item.resultJson) } });
  } catch (error) {
    return handleRouteError(error);
  }
}
