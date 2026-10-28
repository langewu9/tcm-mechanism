import { NextResponse } from "next/server";

import { handleRouteError, requireApiAdmin } from "@/lib/api";
import { synchronizeDatabaseSource } from "@/lib/database-sync";
import { prisma } from "@/lib/prisma";

export const runtime = "nodejs";
export const maxDuration = 300;
type Params = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: Params) {
  try {
    await requireApiAdmin();
    const { id } = await params;
    const body = await request.json().catch(() => ({}));
    const maxRows = body.maxRows === null || body.maxRows === "" || body.maxRows === undefined ? undefined : Number(body.maxRows);
    if (body.reset === true) await prisma.databaseSource.update({ where: { id }, data: { syncCursor: 0 } });
    const source = await prisma.databaseSource.findUniqueOrThrow({ where: { id } });
    const result = await synchronizeDatabaseSource(source, maxRows);
    return NextResponse.json({ ok: true, result });
  } catch (error) {
    return handleRouteError(error);
  }
}
