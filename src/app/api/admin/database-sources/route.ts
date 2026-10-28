import { NextResponse } from "next/server";

import { handleRouteError, requireApiAdmin } from "@/lib/api";
import { DEFAULT_DATABASE_MAPPING, parseMapping } from "@/lib/database-sync";
import { prisma } from "@/lib/prisma";

export const runtime = "nodejs";

export async function GET() {
  try {
    await requireApiAdmin();
    const items = await prisma.databaseSource.findMany({
      orderBy: { createdAt: "desc" },
      include: { syncRuns: { orderBy: { startedAt: "desc" }, take: 5 } }
    });
    return NextResponse.json({
      ok: true,
      items: items.map(({ connectionUrl, ...item }) => ({
        ...item,
        connectionConfigured: Boolean(connectionUrl || item.environmentVariable),
        connectionHint: item.environmentVariable ? `env:${item.environmentVariable}` : connectionUrl ? "本地文件（已隐藏）" : "未配置"
      }))
    });
  } catch (error) {
    return handleRouteError(error);
  }
}

export async function POST(request: Request) {
  try {
    await requireApiAdmin();
    const body = await request.json();
    const name = String(body.name ?? "").trim();
    const connectionUrl = String(body.connectionUrl ?? "").trim() || null;
    const environmentVariable = String(body.environmentVariable ?? "").trim() || null;
    if (!name) throw new Error("请输入数据源名称");
    if (!connectionUrl && !environmentVariable) throw new Error("数据库路径和环境变量至少填写一项");
    if (environmentVariable && !/^[A-Z][A-Z0-9_]*$/.test(environmentVariable)) throw new Error("环境变量名称无效");

    const mapping = parseMapping({
      table: String(body.table ?? DEFAULT_DATABASE_MAPPING.table).trim(),
      herbColumn: String(body.herbColumn ?? DEFAULT_DATABASE_MAPPING.herbColumn).trim(),
      compoundColumn: String(body.compoundColumn ?? DEFAULT_DATABASE_MAPPING.compoundColumn).trim(),
      targetColumn: String(body.targetColumn ?? DEFAULT_DATABASE_MAPPING.targetColumn).trim()
    });
    const item = await prisma.databaseSource.create({
      data: {
        name,
        driver: "SQLITE",
        connectionUrl,
        environmentVariable,
        mappingJson: JSON.stringify(mapping)
      }
    });
    return NextResponse.json({ ok: true, item: { ...item, connectionUrl: undefined } }, { status: 201 });
  } catch (error) {
    return handleRouteError(error);
  }
}
