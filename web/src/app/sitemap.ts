import type { MetadataRoute } from "next";
import { connection } from "next/server";

import { ApiError, getSitemap, type Sitemap } from "@/lib/api/client";
import { siteUrl } from "@/lib/config";

/**
 * The home page, the topic list, every topic page and every paper page with public notes.
 * Paper pages that only show facts are left out: any arXiv id has one.
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  // Built for each request from the database, not once at build time.
  await connection();
  const site = siteUrl();
  let listed: Sitemap = { papers: [], topics: [] };
  try {
    listed = await getSitemap();
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
  }
  return [
    { url: `${site}/` },
    { url: `${site}/topics`, changeFrequency: "daily" },
    ...listed.topics.map((topic) => ({
      url: `${site}/topics/${topic.id}`,
      lastModified: topic.updated,
    })),
    ...listed.papers.map((paper) => ({
      url: `${site}/abs/${paper.source_id}`,
      lastModified: paper.updated,
    })),
  ];
}
