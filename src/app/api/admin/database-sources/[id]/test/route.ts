import { NextResponse } from "next/server";

import { handleRouteError, requireApiAdmin } from "@/lib/api";
import { testDatabaseSource } from "@/lib/database-sync";
import { prisma } from "@/lib/prisma";

export const runtime = "nodejs";
type Params = { params: Promise<{ id: string }> };

export async function POST(_request: Request, { params }: Params) {
  try {
    await requireApiAdmin();
    const { id } = await params;
    const source = await prisma.databaseSource.findUniqueOrThrow({ where: { id } });
    const result = testDatabaseSource(source);
    await prisma.databaseSource.update({ where: { id }, data: { lastConnectedAt: new Date() } });
    return NextResponse.json({ ok: true, result });
  } catch (error) {
    return handleRouteError(error);
  }
}
