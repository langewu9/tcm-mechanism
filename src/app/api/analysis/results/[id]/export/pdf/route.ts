import { prisma } from "@/lib/prisma";
import { handleRouteError, jsonError, requireApiUser } from "@/lib/api";
import { buildPdf } from "@/lib/exporters";

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
    const lines = [
      item.summary,
      ...Object.entries(evidence).map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : value}`)
    ];
    const pdf = await buildPdf(item.task.name, lines);
    return new Response(new Uint8Array(pdf), {
      headers: {
        "content-type": "application/pdf",
        "content-disposition": `attachment; filename="${encodeURIComponent(item.task.name)}.pdf"`
      }
    });
  } catch (error) {
    return handleRouteError(error);
  }
}
