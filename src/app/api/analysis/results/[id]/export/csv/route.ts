import { prisma } from "@/lib/prisma";
import { handleRouteError, jsonError, requireApiUser } from "@/lib/api";
import { toCsv } from "@/lib/exporters";

export const runtime = "nodejs";

type Params = { params: Promise<{ id: string }> };

export async function GET(_request: Request, { params }: Params) {
  try {
    const user = await requireApiUser();
    const { id } = await params;
    const item = await prisma.analysisResult.findFirst({
      where: { id, task: user.role === "ADMIN" ? {} : { ownerId: user.id } },
      include: { task: true }
    });
    if (!item) return jsonError("分析结果不存在", 404);
    const evidence = JSON.parse(item.evidenceJson) as Record<string, string[] | string>;
    const rows = Object.entries(evidence).map(([level, value]) => ({
      level,
      value: Array.isArray(value) ? value.join("; ") : value
    }));
    return new Response(toCsv(rows), {
      headers: {
        "content-type": "text/csv; charset=utf-8",
        "content-disposition": `attachment; filename="${encodeURIComponent(item.task.name)}.csv"`
      }
    });
  } catch (error) {
    return handleRouteError(error);
  }
}
