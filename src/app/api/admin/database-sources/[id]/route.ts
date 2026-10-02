import { NextResponse } from "next/server";

import { handleRouteError, requireApiAdmin } from "@/lib/api";
import { prisma } from "@/lib/prisma";

export const runtime = "nodejs";
type Params = { params: Promise<{ id: string }> };

export async function DELETE(_request: Request, { params }: Params) {
  try {
    await requireApiAdmin();
    const { id } = await params;
    await prisma.databaseSource.delete({ where: { id } });
    return NextResponse.json({ ok: true });
  } catch (error) {
    return handleRouteError(error);
  }
}
