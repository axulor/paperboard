from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import VERSION
from app.config import Settings
from app.mcp.server import build_mcp_app, build_mcp_server
from app.rest import health
from app.sources import ArxivAdapter


def create_app(settings: Settings | None = None, *, arxiv: ArxivAdapter | None = None) -> FastAPI:
    """The whole service. `arxiv` replaces the real arXiv adapter, e.g. in tests.

    One ArxivAdapter serves the process, so every request shares its rate limit.
    """
    settings = settings or Settings()
    arxiv = arxiv or ArxivAdapter()
    engine = (
        create_async_engine(settings.database_url.get_secret_value())
        if settings.database_url is not None
        else None
    )
    sessions = async_sessionmaker(engine) if engine is not None else None
    mcp_server = build_mcp_server(arxiv, sessions=sessions)
    mcp_app = build_mcp_app(mcp_server, settings.public_hosts)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        # A mounted sub-app's lifespan is not run by FastAPI, so the MCP session manager is
        # started here.
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(arxiv)
            await stack.enter_async_context(mcp_server.session_manager.run())
            if engine is not None:
                stack.push_async_callback(engine.dispose)
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                app.state.db_engine = engine
            yield

    app = FastAPI(title="PaperBoard API", version=VERSION, lifespan=lifespan)
    app.include_router(health.router, prefix="/api")
    # Mounted last at the root so it only receives what the REST routes did not match (/mcp).
    app.mount("/", mcp_app)
    return app


app = create_app()
