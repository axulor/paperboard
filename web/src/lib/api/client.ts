// Calls to the PaperBoard API, made by this server while it renders a page.

import { apiUrl } from "@/lib/config";
import type { components } from "./schema";

export type PaperReport = components["schemas"]["PaperReport"];
export type PaperFacts = components["schemas"]["PaperFacts"];
export type CodeLink = components["schemas"]["CodeLink"];
export type PaperNotes = components["schemas"]["PaperNotes"];
export type NoteSummary = components["schemas"]["NoteSummary"];
export type StoredQuote = components["schemas"]["StoredQuote"];
export type TopicMatch = components["schemas"]["TopicMatch"];
export type TopicPaperSummary = components["schemas"]["TopicPaperSummary"];
export type OpenQuestion = components["schemas"]["OpenQuestion"];

async function get(path: string, timeoutMs = 10_000): Promise<Response> {
  try {
    return await fetch(`${apiUrl()}${path}`, {
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    throw new ApiError(`PaperBoard API unreachable: ${String(error)}`);
  }
}

/** One topic with its papers and open questions; null if there is no such topic. */
export async function getTopic(id: number): Promise<TopicMatch | null> {
  const response = await get(`/api/topics/${id}`);
  if (response.status === 404) return null;
  if (!response.ok)
    throw new ApiError(
      `PaperBoard API answered ${response.status} for topic ${id}`,
    );
  return (await response.json()) as TopicMatch;
}

/** Topics like `query`, or the newest topics when there is no query. */
export async function listTopics(query?: string): Promise<TopicMatch[]> {
  const search = query ? `?${new URLSearchParams({ q: query })}` : "";
  const response = await get(`/api/topics${search}`);
  if (!response.ok)
    throw new ApiError(`PaperBoard API answered ${response.status} for topics`);
  return (await response.json()) as TopicMatch[];
}

/** The API answered with an error, or could not be reached. */
export class ApiError extends Error {}

/** Facts about an arXiv paper; null if arXiv has no such paper. `id` must be a valid arXiv id. */
export async function getPaper(id: string): Promise<PaperReport | null> {
  let response: Response;
  try {
    // The first look at a paper fetches it from arXiv, which allows one request per 3 seconds.
    response = await fetch(`${apiUrl()}/api/papers/arxiv/${id}`, {
      signal: AbortSignal.timeout(60_000),
    });
  } catch (error) {
    throw new ApiError(`PaperBoard API unreachable: ${String(error)}`);
  }
  if (response.status === 404) return null;
  if (!response.ok)
    throw new ApiError(`PaperBoard API answered ${response.status} for ${id}`);
  return (await response.json()) as PaperReport;
}

/** Public notes on an arXiv paper, newest first. `id` must be a valid arXiv id. */
export async function getNotes(id: string): Promise<PaperNotes> {
  let response: Response;
  try {
    response = await fetch(`${apiUrl()}/api/papers/arxiv/${id}/notes`, {
      signal: AbortSignal.timeout(10_000),
    });
  } catch (error) {
    throw new ApiError(`PaperBoard API unreachable: ${String(error)}`);
  }
  if (!response.ok)
    throw new ApiError(
      `PaperBoard API answered ${response.status} for notes on ${id}`,
    );
  return (await response.json()) as PaperNotes;
}

export type Sitemap = components["schemas"]["Sitemap"];

/** Papers with public notes, and topics. */
export async function getSitemap(): Promise<Sitemap> {
  const response = await get("/api/sitemap");
  if (!response.ok)
    throw new ApiError(
      `PaperBoard API answered ${response.status} for sitemap`,
    );
  return (await response.json()) as Sitemap;
}

export type ReportReason = components["schemas"]["ReportIn"]["reason"];

/** Report a note; false if there is no such public note. */
export async function reportNote(
  id: number,
  reason: ReportReason,
  detail: string,
): Promise<boolean> {
  let response: Response;
  try {
    response = await fetch(`${apiUrl()}/api/notes/${id}/reports`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason, detail }),
      signal: AbortSignal.timeout(10_000),
    });
  } catch (error) {
    throw new ApiError(`PaperBoard API unreachable: ${String(error)}`);
  }
  if (response.status === 404) return false;
  if (!response.ok)
    throw new ApiError(
      `PaperBoard API answered ${response.status} for a report`,
    );
  return true;
}
