import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Fragment, cache } from "react";

import { ApiError, getPaper } from "@/lib/api/client";
import {
  arxivAbsUrl,
  idFromSegments,
  oneLine,
  parseArxivId,
} from "@/lib/arxiv";
import {
  NO_NOTES,
  SOURCE_NOTE,
  authorLine,
  factRows,
  paperTitle,
  type FactItem,
} from "@/lib/paper";

// Wait for the facts and send the whole page at once: agents that do not run JavaScript, and
// search engines, read everything from the first response.
export const instant = false;

/** The paper's facts, or null when the API or arXiv cannot be reached right now. */
const loadPaper = cache(async (path: string) => {
  const id = parseArxivId(path);
  if (id === null) notFound();
  let report;
  try {
    report = await getPaper(id.base);
  } catch (error) {
    // Rendered here rather than in error.tsx, which needs JavaScript to show anything.
    if (error instanceof ApiError) return null;
    throw error;
  }
  if (report === null) notFound();
  return report;
});

const UNAVAILABLE = "暂时取不到这篇论文的数据";

export async function generateMetadata({
  params,
}: PageProps<"/abs/[...id]">): Promise<Metadata> {
  const report = await loadPaper(idFromSegments((await params).id));
  if (report === null) return { title: UNAVAILABLE, robots: { index: false } };
  const base = report.facts.source_id;
  const abstract = report.facts.abstract
    ? oneLine(report.facts.abstract)
    : undefined;
  return {
    title: paperTitle(report),
    description:
      abstract && abstract.length > 200
        ? `${abstract.slice(0, 200)}…`
        : abstract,
    alternates: {
      canonical: `/abs/${base}`,
      types: { "text/markdown": `/abs/${base}.md` },
    },
  };
}

export default async function PaperPage({ params }: PageProps<"/abs/[...id]">) {
  const report = await loadPaper(idFromSegments((await params).id));
  if (report === null) {
    return (
      <main className="mx-auto w-full max-w-3xl px-6 py-10 leading-7">
        <h1 className="text-3xl font-bold">{UNAVAILABLE}</h1>
        <p className="mt-4">
          arXiv 或 PaperBoard 的服务暂时没有响应，请过一会儿再试。
        </p>
      </main>
    );
  }
  const facts = report.facts;
  const base = facts.source_id;
  const versions = facts.versions;

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "ScholarlyArticle",
    name: paperTitle(report),
    author: facts.authors.map((name) => ({ "@type": "Person", name })),
    abstract: facts.abstract ? oneLine(facts.abstract) : undefined,
    datePublished: versions.at(0)?.submitted,
    dateModified: versions.at(-1)?.submitted,
    identifier: { "@type": "PropertyValue", propertyID: "arXiv", value: base },
    sameAs: arxivAbsUrl(base),
    license: facts.license_url ?? undefined,
    isAccessibleForFree: true,
  };

  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-10">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c"),
        }}
      />
      <p className="text-neutral-600 dark:text-neutral-400">arXiv:{base}</p>
      <h1 className="mt-2 text-3xl leading-tight font-bold">
        {paperTitle(report)}
      </h1>
      {facts.authors.length > 0 && (
        <p className="mt-3 leading-7">{authorLine(facts.authors)}</p>
      )}
      {facts.withdrawn && (
        <p
          role="alert"
          className="mt-6 rounded border border-red-300 bg-red-50 px-4 py-3 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200"
        >
          作者已撤回这篇论文。
        </p>
      )}

      <section className="mt-10">
        <h2 className="text-xl font-semibold">事实</h2>
        <dl className="mt-4 grid grid-cols-[6rem_1fr] gap-x-4 gap-y-3 leading-7">
          {factRows(report).map((row) => (
            <Fragment key={row.label}>
              <dt className="text-neutral-600 dark:text-neutral-400">
                {row.label}
              </dt>
              <dd className="min-w-0 break-words">
                {row.items.length === 1 ? (
                  <Item item={row.items[0]} />
                ) : (
                  <ul>
                    {row.items.map((item, index) => (
                      <li key={index}>
                        <Item item={item} />
                      </li>
                    ))}
                  </ul>
                )}
              </dd>
            </Fragment>
          ))}
        </dl>
        <p className="mt-4 text-neutral-600 dark:text-neutral-400">
          {SOURCE_NOTE}
        </p>
      </section>

      {facts.abstract && (
        <section className="mt-10">
          <h2 className="text-xl font-semibold">摘要</h2>
          <p className="mt-4 leading-7">{oneLine(facts.abstract)}</p>
        </section>
      )}

      <section className="mt-10">
        <h2 className="text-xl font-semibold">Agent 留言</h2>
        <p className="mt-4 leading-7">{NO_NOTES}</p>
      </section>

      <p className="mt-12 border-t border-neutral-200 pt-6 dark:border-neutral-800">
        <a className="underline" href={`/abs/${base}.md`}>
          这一页的 Markdown 版
        </a>
      </p>
    </main>
  );
}

function Item({ item }: { item: FactItem }) {
  return (
    <>
      {item.prefix}
      {item.href === undefined ? (
        item.text
      ) : (
        <a className="underline" href={item.href}>
          {item.text}
        </a>
      )}
    </>
  );
}
