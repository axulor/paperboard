import type { Metadata } from "next";

import { parseArxivId } from "@/lib/arxiv";
import { REPORT_MESSAGES, reportResult } from "@/lib/reports";
import { parseId } from "@/lib/topics";

export const instant = false;

export const metadata: Metadata = {
  title: "举报",
  robots: { index: false },
};

function first(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

export default async function ReportedPage({
  searchParams,
}: PageProps<"/reported">) {
  const params = await searchParams;
  const result = reportResult(first(params.result));
  const paper = parseArxivId(first(params.paper));
  const note = parseId(first(params.note));
  const back =
    paper === null
      ? null
      : `/abs/${paper.base}${note === null ? "" : `#note-${note}`}`;
  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-10 leading-7">
      <h1 className="text-3xl font-bold">举报</h1>
      <p className="mt-4">{REPORT_MESSAGES[result]}</p>
      {back !== null && (
        <p className="mt-6">
          <a className="underline" href={back}>
            回到论文页
          </a>
        </p>
      )}
    </main>
  );
}
