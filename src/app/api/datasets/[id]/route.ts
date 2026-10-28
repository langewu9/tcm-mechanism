import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { handleRouteError, jsonError, requireApiUser } from "@/lib/api";

export const runtime = "nodejs";

type Params = { params: Promise<{ id: string }> };

export async function GET(_request: Request, { params }: Params) {
  try {
    const user = await requireApiUser();
    const { id } = await params;
    const item = await prisma.dataset.findFirst({
      where: { id, ...(user.role === "ADMIN" ? {} : { ownerId: user.id }) },
      include: { rows: { take: 100, orderBy: { index: "asc" } } }
    });
    if (!item) return jsonError("数据集不存在", 404);
    return NextResponse.json({ ok: true, item });
  } catch (error) {
    return handleRouteError(error);
  }
}

export async function DELETE(_request: Request, { params }: Params) {
  try {
    const user = await requireApiUser();
    const { id } = await params;
    const exists = await prisma.dataset.findFirst({
      where: { id, ...(user.role === "ADMIN" ? {} : { ownerId: user.id }) }
    });
    if (!exists) return jsonError("数据集不存在", 404);
    await prisma.dataset.delete({ where: { id } });
    return NextResponse.json({ ok: true });
  } catch (error) {
    return handleRouteError(error);
  }
}
