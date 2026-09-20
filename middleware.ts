import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const SESSION_COOKIE = "qh_session";

const protectedPaths = ["/dashboard", "/datasets", "/cases", "/analysis", "/visualization", "/admin", "/assistant"];

export function middleware(request: NextRequest) {
  const isProtected = protectedPaths.some((path) => request.nextUrl.pathname.startsWith(path));
  if (!isProtected) return NextResponse.next();

  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", request.nextUrl.pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/datasets/:path*", "/cases/:path*", "/analysis/:path*", "/visualization/:path*", "/admin/:path*", "/assistant/:path*"]
};
