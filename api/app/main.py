from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import VERSION
from app.config import Settings
from app.mcp.server import build_mcp_app, build_mcp_server
from app.rest import health


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    mcp_server = build_mcp_server()
    mcp_app = build_mcp_app(mcp_server, settings.public_hosts)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # A mounted sub-app's lifespan is not run by FastAPI, so the MCP session manager is
        # started here.
        async with mcp_server.session_manager.run():
            yield

    app = FastAPI(title="PaperBoard API", version=VERSION, lifespan=lifespan)
    app.include_router(health.router, prefix="/api")
    # Mounted last at the root so it only receives what the REST routes did not match (/mcp).
    app.mount("/", mcp_app)
    return app


app = create_app()
