import { NextResponse, type NextRequest } from "next/server";

import { idFromSegments, parseArxivId } from "@/lib/arxiv";

/**
 * Requests for paper pages.
 *
 * - The Markdown version, /abs/{id}.md or /abs/{id} requested with `Accept: text/markdown`, is
 *   served by the route handler under /md/abs/.
 * - A path that is not an arXiv id gets a real 404 here. A page starts streaming with status 200
 *   before it renders, so the page itself can only mark a missing paper with noindex.
 */
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const accept = request.headers.get("accept") ?? "";
  if (pathname.endsWith(".md") || accept.includes("text/markdown")) {
    const url = request.nextUrl.clone();
    url.pathname = `/md${pathname.replace(/\.md$/, "")}`;
    return NextResponse.rewrite(url);
  }
  const path = idFromSegments(pathname.split("/").slice(2));
  if (parseArxivId(path) === null) {
    // No route matches a private folder, so this renders app/not-found.tsx with a 404.
    return NextResponse.rewrite(new URL("/_not-a-paper", request.url));
  }
  const response = NextResponse.next();
  response.headers.set("Vary", "Accept");
  return response;
}

export const config = {
  matcher: "/abs/:path+",
};
