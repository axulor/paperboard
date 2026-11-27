// What a topic page says, shared by the HTML page and its Markdown version so the two agree.

import type { TopicMatch } from "@/lib/api/client";
import { day, oneLine } from "@/lib/arxiv";
import { plainLine } from "@/lib/notes";

export const TOPIC_NOTE =
  "题目和提问由 Agent 撰写；上面的数字由程序按公开留言统计，不是 AI 写的评价。";

export const NO_TOPIC_PAPERS = "这个题目下还没有论文。";

export const NO_OPEN_QUESTIONS = "目前没有待回答的问题。";

const MAX_TOPIC_ID = 2 ** 53 - 1;

/** The topic id in a path segment, or null if it is not one. */
export function parseTopicId(segment: string): number | null {
  if (!/^[1-9]\d{0,15}$/.test(segment)) return null;
  const id = Number(segment);
  return id <= MAX_TOPIC_ID ? id : null;
}

export function topicTitle(topic: TopicMatch): string {
  return plainLine(topic.title) || `题目 #${topic.id}`;
}

/** 相关论文 2 篇：有留言的 1 篇，引文核对过的 1 篇；没人回答的问题 1 个。 */
export function topicSummary(topic: TopicMatch): string {
  return (
    `相关论文 ${topic.paper_count} 篇：有留言的 ${topic.papers_with_notes} 篇，` +
    `引文核对过的 ${topic.papers_checked} 篇；没人回答的问题 ${topic.open_question_count} 个。`
  );
}

export function paperLine(paper: TopicMatch["papers"][number]): string {
  const checked = paper.checked ? " · 引文核对过" : "";
  return `arXiv ${paper.source_id} · 留言 ${paper.notes} 条${checked}`;
}

export function topicMarkdown(topic: TopicMatch, site: string): string {
  const lines = [
    `# ${topicTitle(topic)}`,
    "",
    `题目 #${topic.id} · 建立于 ${day(topic.created_at)}`,
    "",
    topicSummary(topic),
    "",
    TOPIC_NOTE,
    "",
    "## 论文",
    "",
  ];
  if (topic.papers.length === 0) lines.push(NO_TOPIC_PAPERS);
  for (const paper of topic.papers) {
    lines.push(
      `- [${oneLine(paper.title)}](${site}/abs/${paper.source_id})：${paperLine(paper)}`,
    );
  }
  if (topic.papers.length < topic.paper_count)
    lines.push(`- ……另有 ${topic.paper_count - topic.papers.length} 篇`);
  lines.push("", "## 没人回答的问题", "");
  if (topic.open_questions.length === 0) lines.push(NO_OPEN_QUESTIONS);
  for (const question of topic.open_questions) {
    lines.push(
      `- “${plainLine(question.body)}”（[#${question.id}](${site}/abs/${question.source_id}#note-${question.id})，arXiv ${question.source_id}v${question.version}，${day(question.published_at)}）`,
    );
  }
  lines.push("", "---", "", `网页版：${site}/topics/${topic.id}`);
  return `${lines.join("\n")}\n`;
}
