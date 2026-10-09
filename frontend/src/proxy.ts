import { NextResponse, type NextRequest } from "next/server";

// Optimistic check only: no session cookie means no point rendering the app shell.
// FastAPI validates the session on every API call; this just avoids a flash of UI.
const SESSION_COOKIE = "ppe_session";

export function proxy(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  const url = request.nextUrl.clone();
  const next = request.nextUrl.pathname + request.nextUrl.search;
  url.pathname = "/login";
  url.search = next && next !== "/" ? `?next=${encodeURIComponent(next)}` : "";
  return NextResponse.redirect(url);
}

export const config = {
  matcher: [
    "/",
    "/dashboard/:path*",
    "/notifications/:path*",
    "/review/:path*",
    "/annotate/:path*",
    "/training/:path*",
    "/config/:path*",
    "/admin/:path*",
  ],
};
