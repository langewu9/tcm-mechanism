import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { prisma } from "@/lib/prisma";
import { createSessionToken, hashPassword, SESSION_COOKIE } from "@/lib/auth";
import { handleRouteError, jsonError } from "@/lib/api";

export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const name = String(body.name ?? "").trim();
    const email = String(body.email ?? "").trim().toLowerCase();
    const password = String(body.password ?? "");
    if (!name || !email || password.length < 8) {
      return jsonError("姓名、邮箱和至少 8 位密码为必填项");
    }
    const exists = await prisma.user.findUnique({ where: { email } });
    if (exists) return jsonError("该邮箱已注册", 409);
    const user = await prisma.user.create({
      data: { name, email, passwordHash: hashPassword(password), role: "RESEARCHER" },
      select: { id: true, name: true, email: true, role: true }
    });
    const jar = await cookies();
    jar.set(SESSION_COOKIE, createSessionToken(user.id), {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 7
    });
    return NextResponse.json({ ok: true, user });
  } catch (error) {
    return handleRouteError(error);
  }
}
