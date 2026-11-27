// Smoke tests of what the server sends: the HTML and Markdown an agent's fetch tool receives,
// without running a browser. Run after `pnpm build`.

import { defineConfig } from "@playwright/test";

const API_PORT = 8765;
const WEB_PORT = 3100;

export default defineConfig({
  testDir: "tests",
  use: { baseURL: `http://localhost:${WEB_PORT}` },
  webServer: [
    {
      command: `node tests/fake-api.mjs ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/health`,
    },
    {
      command: `pnpm exec next start --port ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}/`,
      env: {
        PAPERBOARD_API_URL: `http://127.0.0.1:${API_PORT}`,
        PAPERBOARD_SITE_URL: `http://localhost:${WEB_PORT}`,
      },
    },
  ],
});
