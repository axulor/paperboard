import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";

import { ApiError, getTopic, type TopicMatch } from "@/lib/api/client";
import { day, oneLine } from "@/lib/arxiv";
import {
  NO_OPEN_QUESTIONS,
  NO_TOPIC_PAPERS,
  TOPIC_NOTE,
  paperLine,
  parseTopicId,
  topicSummary,
  topicTitle,
} from "@/lib/topics";

// Send the whole page at once, like the paper pages.
export const instant = false;

const UNAVAILABLE = "暂时取不到这个题目的数据";

/** The topic, or null when the API cannot be reached right now. */
const loadTopic = cache(async (segment: string) => {
  const id = parseTopicId(segment);
  if (id === null) notFound();
  let topic: TopicMatch | null;
  try {
    topic = await getTopic(id);
  } catch (error) {
    if (error instanceof ApiError) return null;
    throw error;
  }
  if (topic === null) notFound();
  return topic;
});

export async function generateMetadata({
  params,
}: PageProps<"/topics/[id]">): Promise<Metadata> {
  const topic = await loadTopic((await params).id);
  if (topic === null) return { title: UNAVAILABLE, robots: { index: false } };
  return {
    title: topicTitle(topic),
    description: topicSummary(topic),
    alternates: {
      canonical: `/topics/${topic.id}`,
      types: { "text/markdown": `/topics/${topic.id}.md` },
    },
  };
}

export default async function TopicPage({ params }: PageProps<"/topics/[id]">) {
  const topic = await loadTopic((await params).id);
  if (topic === null) {
    return (
      <main className="mx-auto w-full max-w-3xl px-6 py-10 leading-7">
        <h1 className="text-3xl font-bold">{UNAVAILABLE}</h1>
        <p className="mt-4">PaperBoard 的服务暂时没有响应，请过一会儿再试。</p>
      </main>
    );
  }
  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-10">
      <p className="text-neutral-600 dark:text-neutral-400">
        <Link className="underline" href="/topics">
          题目
        </Link>{" "}
        #{topic.id} · 建立于 {day(topic.created_at)}
      </p>
      <h1 className="mt-2 text-3xl leading-tight font-bold">
        {topicTitle(topic)}
      </h1>
      <p className="mt-4 leading-7">{topicSummary(topic)}</p>
      <p className="mt-2 text-neutral-600 dark:text-neutral-400">
        {TOPIC_NOTE}
      </p>

      <section className="mt-10">
        <h2 className="text-xl font-semibold">论文</h2>
        {topic.papers.length === 0 ? (
          <p className="mt-4 leading-7">{NO_TOPIC_PAPERS}</p>
        ) : (
          <ul className="mt-4 space-y-4">
            {topic.papers.map((paper) => (
              <li key={paper.source_id}>
                <a className="underline" href={`/abs/${paper.source_id}`}>
                  {oneLine(paper.title)}
                </a>
                <p className="text-sm text-neutral-600 dark:text-neutral-400">
                  {paperLine(paper)}
                </p>
              </li>
            ))}
            {topic.papers.length < topic.paper_count && (
              <li>……另有 {topic.paper_count - topic.papers.length} 篇</li>
            )}
          </ul>
        )}
      </section>

      <section className="mt-10">
        <h2 className="text-xl font-semibold">没人回答的问题</h2>
        {topic.open_questions.length === 0 ? (
          <p className="mt-4 leading-7">{NO_OPEN_QUESTIONS}</p>
        ) : (
          <ul className="mt-4 space-y-4">
            {topic.open_questions.map((question) => (
              <li key={question.id}>
                <p className="leading-7 break-words whitespace-pre-line">
                  {question.body}
                </p>
                <p className="text-sm text-neutral-600 dark:text-neutral-400">
                  <a
                    className="underline"
                    href={`/abs/${question.source_id}#note-${question.id}`}
                  >
                    {`#${question.id}`}
                  </a>
                  {` · arXiv ${question.source_id}v${question.version} · ${day(question.published_at)}`}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="mt-12 border-t border-neutral-200 pt-6 dark:border-neutral-800">
        <a className="underline" href={`/topics/${topic.id}.md`}>
          这一页的 Markdown 版
        </a>
      </p>
    </main>
  );
}
