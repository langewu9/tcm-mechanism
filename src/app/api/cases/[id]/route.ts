import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { handleRouteError, jsonError, requireApiUser } from "@/lib/api";

export const runtime = "nodejs";

type Params = { params: Promise<{ id: string }> };

export async function DELETE(_request: Request, { params }: Params) {
  try {
    const user = await requireApiUser();
    const { id } = await params;
    const exists = await prisma.medicalCase.findFirst({
      where: { id, ...(user.role === "ADMIN" ? {} : { ownerId: user.id }) }
    });
    if (!exists) return jsonError("医案不存在", 404);
    await prisma.medicalCase.delete({ where: { id } });
    return NextResponse.json({ ok: true });
  } catch (error) {
    return handleRouteError(error);
  }
}
