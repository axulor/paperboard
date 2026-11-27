// Takes the report form under a note (a plain HTML form, no JavaScript needed), passes it to
// the API, and sends the reader to a page that says what happened.

import type { NextRequest } from "next/server";

import { ApiError, reportNote } from "@/lib/api/client";
import { parseArxivId } from "@/lib/arxiv";
import {
  MAX_REPORT_DETAIL,
  isReportReason,
  type ReportResult,
} from "@/lib/reports";
import { parseId } from "@/lib/topics";

export async function POST(
  request: NextRequest,
  context: RouteContext<"/notes/[id]/report">,
) {
  const note = parseId((await context.params).id);
  const form = await request.formData();
  const reason = form.get("reason");
  const detail = String(form.get("detail") ?? "").trim();
  const paper = parseArxivId(String(form.get("paper") ?? ""));

  let result: ReportResult;
  if (
    note === null ||
    !isReportReason(reason) ||
    detail.length > MAX_REPORT_DETAIL
  ) {
    result = "invalid";
  } else {
    try {
      result = (await reportNote(note, reason, detail)) ? "ok" : "missing";
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      result = "unavailable";
    }
  }
  const query = new URLSearchParams({ result });
  if (paper !== null) query.set("paper", paper.base);
  if (note !== null) query.set("note", String(note));
  // 303: the browser follows with a GET, so reloading does not send the report again.
  return new Response(null, {
    status: 303,
    headers: { Location: `/reported?${query}` },
  });
}
