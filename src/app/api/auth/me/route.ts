import { NextResponse } from "next/server";
import { apiUser, handleRouteError } from "@/lib/api";

export const runtime = "nodejs";

export async function GET() {
  try {
    const user = await apiUser();
    return NextResponse.json({
      ok: true,
      user: user ? { id: user.id, name: user.name, email: user.email, role: user.role } : null
    });
  } catch (error) {
    return handleRouteError(error);
  }
}
