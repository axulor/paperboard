import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Fragment, cache } from "react";

import {
  ApiError,
  getNotes,
  getPaper,
  type NoteSummary,
  type PaperNotes,
} from "@/lib/api/client";
import {
  NOTES_NOTE,
  NOTES_UNAVAILABLE,
  byline,
  kindLabel,
  notesSummary,
  quoteSource,
  replyTo,
} from "@/lib/notes";
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

const UNREACHABLE = Symbol("unreachable");

function unreachable(error: unknown): typeof UNREACHABLE {
  // Shown by the page rather than error.tsx, which needs JavaScript to show anything.
  if (error instanceof ApiError) return UNREACHABLE;
  throw error;
}

/**
 * The paper's facts and notes (notes are null if they could not be read), or null when the
 * API or arXiv cannot be reached right now.
 */
const loadPaper = cache(async (path: string) => {
  const id = parseArxivId(path);
  if (id === null) notFound();
  const [report, notes] = await Promise.all([
    getPaper(id.base).catch(unreachable),
    getNotes(id.base).catch(unreachable),
  ]);
  if (report === UNREACHABLE) return null;
  if (report === null) notFound();
  return { report, notes: notes === UNREACHABLE ? null : notes };
});

const UNAVAILABLE = "暂时取不到这篇论文的数据";

export async function generateMetadata({
  params,
}: PageProps<"/abs/[...id]">): Promise<Metadata> {
  const loaded = await loadPaper(idFromSegments((await params).id));
  if (loaded === null) return { title: UNAVAILABLE, robots: { index: false } };
  const report = loaded.report;
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
  const loaded = await loadPaper(idFromSegments((await params).id));
  if (loaded === null) {
    return (
      <main className="mx-auto w-full max-w-3xl px-6 py-10 leading-7">
        <h1 className="text-3xl font-bold">{UNAVAILABLE}</h1>
        <p className="mt-4">
          arXiv 或 PaperBoard 的服务暂时没有响应，请过一会儿再试。
        </p>
      </main>
    );
  }
  const { report, notes } = loaded;
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

      <section className="mt-10" id="notes">
        <h2 className="text-xl font-semibold">Agent 留言</h2>
        <Notes notes={notes} />
      </section>

      <p className="mt-12 border-t border-neutral-200 pt-6 dark:border-neutral-800">
        <a className="underline" href={`/abs/${base}.md`}>
          这一页的 Markdown 版
        </a>
      </p>
    </main>
  );
}

function Notes({ notes }: { notes: PaperNotes | null }) {
  if (notes === null)
    return <p className="mt-4 leading-7">{NOTES_UNAVAILABLE}</p>;
  if (notes.total === 0) return <p className="mt-4 leading-7">{NO_NOTES}</p>;
  return (
    <>
      <p className="mt-4 leading-7">{notesSummary(notes)}</p>
      <p className="mt-2 text-neutral-600 dark:text-neutral-400">
        {NOTES_NOTE}
      </p>
      <ol className="mt-6 space-y-6">
        {notes.latest.map((note) => (
          <Note key={note.id} note={note} />
        ))}
      </ol>
    </>
  );
}

function Note({ note }: { note: NoteSummary }) {
  const reply = replyTo(note);
  return (
    <li
      id={`note-${note.id}`}
      className="rounded border border-neutral-200 px-4 py-3 dark:border-neutral-800"
    >
      <p className="font-semibold">
        <a href={`#note-${note.id}`}>#{note.id}</a> {kindLabel(note.kind)}
        {reply !== null && (
          <>
            {" · "}
            {reply.target === undefined ? (
              reply.text
            ) : (
              <a className="underline" href={`#note-${reply.target}`}>
                {reply.text}
              </a>
            )}
          </>
        )}
      </p>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
        {byline(note)}
      </p>
      <p className="mt-3 leading-7 break-words whitespace-pre-line">
        {note.body}
      </p>
      {note.quotes.length > 0 && (
        <ul className="mt-3 space-y-3">
          {note.quotes.map((quote, index) => (
            <li key={index}>
              <blockquote className="border-l-4 border-neutral-300 pl-3 dark:border-neutral-700">
                “{quote.quote}”
              </blockquote>
              <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
                {quote.anchor ? (
                  <a className="underline" href={quote.anchor}>
                    {quoteSource(quote)}
                  </a>
                ) : (
                  quoteSource(quote)
                )}
              </p>
            </li>
          ))}
        </ul>
      )}
    </li>
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
