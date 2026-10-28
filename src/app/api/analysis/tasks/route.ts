import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { handleRouteError, jsonError, requireApiUser } from "@/lib/api";
import { runAnalysis } from "@/lib/analysis";

export const runtime = "nodejs";

export async function GET() {
  try {
    const user = await requireApiUser();
    const items = await prisma.analysisTask.findMany({
      where: user.role === "ADMIN" ? {} : { ownerId: user.id },
      orderBy: { createdAt: "desc" },
      include: { result: true, medicalCase: true }
    });
    return NextResponse.json({ ok: true, items });
  } catch (error) {
    return handleRouteError(error);
  }
}

export async function POST(request: Request) {
  try {
    const user = await requireApiUser();
    const body = await request.json();
    const name = String(body.name ?? "中医药理分析任务").trim();
    const query = String(body.query ?? "").trim();
    const caseId = body.caseId ? String(body.caseId) : null;
    if (!query) return jsonError("请输入医案或分析问题");
    if (caseId) {
      const owned = await prisma.medicalCase.findFirst({
        where: { id: caseId, ...(user.role === "ADMIN" ? {} : { ownerId: user.id }) }
      });
      if (!owned) return jsonError("医案不存在或无权限", 404);
    }
    const analysis = await runAnalysis({ name, query, caseId });
    const task = await prisma.analysisTask.create({
      data: {
        name,
        query,
        ownerId: user.id,
        caseId,
        result: {
          create: {
            summary: analysis.summary,
            evidenceJson: JSON.stringify(analysis.evidence),
            networkJson: JSON.stringify(analysis.network)
          }
        }
      },
      include: { result: true, medicalCase: true }
    });
    return NextResponse.json({ ok: true, item: task });
  } catch (error) {
    return handleRouteError(error);
  }
}
