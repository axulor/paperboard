// arXiv identifiers, matching the rules of api/app/sources/arxiv.py.

// Group 1 is the id without version, group 2 the version.
const ARXIV_ID =
  /^(\d{4}\.\d{4,5}|[a-z]+(?:-[a-z]+)*(?:\.[A-Z]{2})?\/\d{7})(?:v([1-9]\d*))?$/;

export type ArxivId = { base: string; version: number | null };

/** "2401.12345", "2401.12345v2" or "hep-th/9901001"; null for anything else. */
export function parseArxivId(text: string): ArxivId | null {
  const match = ARXIV_ID.exec(text);
  if (match === null) return null;
  const [, base, version] = match;
  return { base, version: version === undefined ? null : Number(version) };
}

/** The id in a catch-all route: old-style ids span two segments. */
export function idFromSegments(segments: string[]): string {
  return segments.map(decodeSegment).join("/");
}

function decodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment; // Malformed escapes; parseArxivId rejects the result.
  }
}

export function arxivAbsUrl(base: string): string {
  return `https://arxiv.org/abs/${base}`;
}

/** "2024-01-08" from an ISO timestamp, in UTC as arXiv dates its versions. */
export function day(timestamp: string): string {
  return timestamp.slice(0, 10);
}

/** Collapses the line breaks arXiv keeps in titles and abstracts. */
export function oneLine(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}
