import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { handleRouteError, requireApiUser } from "@/lib/api";

export const runtime = "nodejs";

export async function GET() {
  try {
    const user = await requireApiUser();
    const [datasets, cases, tasks, herbs, compounds, targets, pathways] = await Promise.all([
      prisma.dataset.count({ where: user.role === "ADMIN" ? {} : { ownerId: user.id } }),
      prisma.medicalCase.count({ where: user.role === "ADMIN" ? {} : { ownerId: user.id } }),
      prisma.analysisTask.count({ where: user.role === "ADMIN" ? {} : { ownerId: user.id } }),
      prisma.herb.count(),
      prisma.compound.count(),
      prisma.target.count(),
      prisma.pathway.count()
    ]);
    return NextResponse.json({
      ok: true,
      stats: { datasets, cases, tasks, herbs, compounds, targets, pathways }
    });
  } catch (error) {
    return handleRouteError(error);
  }
}
