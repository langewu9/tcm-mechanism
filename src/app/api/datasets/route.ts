import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { handleRouteError, requireApiUser } from "@/lib/api";
import { parseUploadedTable } from "@/lib/upload";

export const runtime = "nodejs";

export async function GET(request: Request) {
  try {
    const user = await requireApiUser();
    const url = new URL(request.url);
    const q = url.searchParams.get("q")?.trim();
    const where = {
      ...(user.role === "ADMIN" ? {} : { ownerId: user.id }),
      ...(q ? { OR: [{ name: { contains: q } }, { filename: { contains: q } }] } : {})
    };
    const datasets = await prisma.dataset.findMany({
      where,
      orderBy: { createdAt: "desc" },
      include: { owner: { select: { name: true, email: true } } }
    });
    return NextResponse.json({ ok: true, items: datasets });
  } catch (error) {
    return handleRouteError(error);
  }
}

export async function POST(request: Request) {
  try {
    const user = await requireApiUser();
    const form = await request.formData();
    const file = form.get("file");
    if (!(file instanceof File)) throw new Error("请上传 CSV 或 Excel 文件");
    const parsed = await parseUploadedTable(file);
    const name = String(form.get("name") ?? file.name).trim();
    const description = String(form.get("description") ?? "").trim();
    const dataset = await prisma.dataset.create({
      data: {
        name,
        description,
        filename: file.name,
        type: file.type || "application/octet-stream",
        rowCount: parsed.rows.length,
        columnsJson: JSON.stringify(parsed.columns),
        ownerId: user.id,
        rows: {
          create: parsed.rows.slice(0, 5000).map((row, index) => ({
            index,
            dataJson: JSON.stringify(row)
          }))
        }
      },
      include: { rows: { take: 25, orderBy: { index: "asc" } } }
    });
    return NextResponse.json({ ok: true, item: dataset });
  } catch (error) {
    return handleRouteError(error);
  }
}
