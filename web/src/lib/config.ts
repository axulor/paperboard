// Read on the server only. Defaults match a local setup started as AGENTS.md describes.

/** Where this server reaches the PaperBoard API. */
export function apiUrl(): string {
  return trimSlash(process.env.PAPERBOARD_API_URL ?? "http://127.0.0.1:8000");
}

/** Public address of this site, for canonical links and llms.txt. */
export function siteUrl(): string {
  return trimSlash(process.env.PAPERBOARD_SITE_URL ?? "http://localhost:3000");
}

/** Public address of the MCP connector. */
export function mcpUrl(): string {
  return process.env.PAPERBOARD_MCP_URL ?? "http://127.0.0.1:8000/mcp";
}

function trimSlash(url: string): string {
  return url.replace(/\/+$/, "");
}
