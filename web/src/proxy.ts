import { NextResponse, type NextRequest } from "next/server";

import { idFromSegments, parseArxivId } from "@/lib/arxiv";
import { parseTopicId } from "@/lib/topics";

/**
 * Requests for paper pages (/abs/{arXiv id}) and topic pages (/topics/{id}).
 *
 * - The Markdown version, the page's path plus .md or the page requested with
 *   `Accept: text/markdown`, is served by the route handlers under /md/.
 * - A path that is not an arXiv id or a topic id gets a real 404 here. A page starts streaming
 *   with status 200 before it renders, so the page itself can only mark a missing item with
 *   noindex.
 */
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const accept = request.headers.get("accept") ?? "";
  if (pathname.endsWith(".md") || accept.includes("text/markdown")) {
    const url = request.nextUrl.clone();
    url.pathname = `/md${pathname.replace(/\.md$/, "")}`;
    return NextResponse.rewrite(url);
  }
  const [, section, ...segments] = pathname.split("/");
  const valid =
    section === "abs"
      ? parseArxivId(idFromSegments(segments)) !== null
      : segments.length === 1 && parseTopicId(segments[0]) !== null;
  if (!valid) {
    // No route matches a private folder, so this renders app/not-found.tsx with a 404.
    return NextResponse.rewrite(new URL("/_not-found-here", request.url));
  }
  const response = NextResponse.next();
  response.headers.set("Vary", "Accept");
  return response;
}

export const config = {
  matcher: ["/abs/:path+", "/topics/:path+"],
};
