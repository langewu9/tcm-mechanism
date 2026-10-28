import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { handleRouteError, jsonError, requireApiUser } from "@/lib/api";

export const runtime = "nodejs";

export async function GET(request: Request) {
  try {
    const user = await requireApiUser();
    const q = new URL(request.url).searchParams.get("q")?.trim();
    const items = await prisma.medicalCase.findMany({
      where: {
        ...(user.role === "ADMIN" ? {} : { ownerId: user.id }),
        ...(q ? { OR: [{ title: { contains: q } }, { symptoms: { contains: q } }, { diagnosis: { contains: q } }] } : {})
      },
      orderBy: { createdAt: "desc" },
      include: { owner: { select: { name: true } } }
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
    const title = String(body.title ?? "").trim();
    const symptoms = String(body.symptoms ?? "").trim();
    if (!title || !symptoms) return jsonError("医案标题和症状为必填项");
    const item = await prisma.medicalCase.create({
      data: {
        title,
        symptoms,
        patientInfo: String(body.patientInfo ?? "").trim(),
        tonguePulse: String(body.tonguePulse ?? "").trim(),
        diagnosis: String(body.diagnosis ?? "").trim(),
        source: String(body.source ?? "").trim(),
        ownerId: user.id
      }
    });
    return NextResponse.json({ ok: true, item });
  } catch (error) {
    return handleRouteError(error);
  }
}
