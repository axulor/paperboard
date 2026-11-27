# The web pages. Build from web/: docker build -t paperboard-web .
#
# The site and connector addresses are build arguments: pages built ahead of time (the home page,
# llms.txt) contain them.

FROM node:24-slim AS build
ENV NEXT_TELEMETRY_DISABLED=1 PAPERBOARD_STANDALONE=1
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile
COPY . .
ARG PAPERBOARD_SITE_URL=http://localhost:8080
ARG PAPERBOARD_MCP_URL=http://localhost:8080/mcp
ENV PAPERBOARD_SITE_URL=$PAPERBOARD_SITE_URL PAPERBOARD_MCP_URL=$PAPERBOARD_MCP_URL
# public/ holds static files; git does not keep it while it is empty.
RUN mkdir -p public && pnpm build

FROM node:24-slim
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
WORKDIR /app
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
