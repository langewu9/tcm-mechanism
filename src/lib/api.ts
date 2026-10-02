import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { prisma } from "@/lib/prisma";
import { readSessionToken, SESSION_COOKIE } from "@/lib/auth";

export function jsonError(message: string, status = 400) {
  return NextResponse.json({ ok: false, error: message }, { status });
}

export async function apiUser() {
  const jar = await cookies();
  const userId = readSessionToken(jar.get(SESSION_COOKIE)?.value);
  if (!userId) return null;
  return prisma.user.findUnique({ where: { id: userId } });
}

export async function requireApiUser() {
  const user = await apiUser();
  if (!user) throw new Response("Unauthorized", { status: 401 });
  return user;
}

export async function requireApiAdmin() {
  const user = await requireApiUser();
  if (user.role !== "ADMIN") throw new Response("Forbidden", { status: 403 });
  return user;
}

export function handleRouteError(error: unknown) {
  if (error instanceof Response) {
    return new NextResponse(error.body, { status: error.status });
  }
  const message = error instanceof Error ? error.message : "未知错误";
  return jsonError(message, 500);
}
