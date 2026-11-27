// Calls to the PaperBoard API, made by this server while it renders a page.

import { apiUrl } from "@/lib/config";
import type { components } from "./schema";

export type PaperReport = components["schemas"]["PaperReport"];
export type PaperFacts = components["schemas"]["PaperFacts"];
export type CodeLink = components["schemas"]["CodeLink"];

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
