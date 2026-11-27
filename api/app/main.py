from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.types import ASGIApp, Receive, Scope, Send

from app import VERSION
from app.config import Settings
from app.core.moderation import WordList
from app.core.notes import NotePolicy
from app.mcp.auth import AccountTokenVerifier
from app.mcp.server import LOGIN_PATH, Login, build_mcp_app, build_mcp_server
from app.rest import health, papers, site, topics
from app.sources import ArxivAdapter


def create_app(
    settings: Settings | None = None,
    *,
    arxiv: ArxivAdapter | None = None,
    login: Login | None = None,
) -> FastAPI:
    """The whole service. `arxiv` replaces the real arXiv adapter, and `login` the token check
    and posting rules, e.g. in tests.

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
    if login is None and sessions is not None:
        login = Login(
            verifier=AccountTokenVerifier(sessions),
            policy=NotePolicy(
                notes_per_hour=settings.notes_per_hour,
                blocked_words=WordList.load(settings.blocked_words_file),
            ),
            site_url=settings.site_url,
        )
    servers = [build_mcp_server(arxiv, sessions=sessions)]
    connector = build_mcp_app(servers[0], settings.public_hosts)
    if login is not None:
        servers.append(build_mcp_server(arxiv, sessions=sessions, login=login))
        login_connector = build_mcp_app(servers[1], settings.public_hosts, LOGIN_PATH)
        connector = _by_path({LOGIN_PATH: login_connector}, connector)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        # A mounted sub-app's lifespan is not run by FastAPI, so the MCP session managers are
        # started here.
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(arxiv)
            for server in servers:
                await stack.enter_async_context(server.session_manager.run())
            if engine is not None:
                stack.push_async_callback(engine.dispose)
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                app.state.db_engine = engine
            yield

    app = FastAPI(title="PaperBoard API", version=VERSION, lifespan=lifespan)
    app.include_router(health.router, prefix="/api")
    app.include_router(papers.build_router(arxiv, sessions=sessions), prefix="/api")
    app.include_router(topics.build_router(sessions), prefix="/api")
    app.include_router(site.build_router(sessions), prefix="/api")
    # Mounted last at the root so it only receives what the REST routes did not match: /mcp
    # for everyone, /mcp/login for logged-in agents.
    app.mount("/", connector)
    return app


def _by_path(routes: dict[str, ASGIApp], default: ASGIApp) -> ASGIApp:
    """Send requests for exactly these paths to their app, and the rest to `default`."""

    async def dispatch(scope: Scope, receive: Receive, send: Send) -> None:
        target = routes.get(scope["path"], default) if scope["type"] == "http" else default
        await target(scope, receive, send)

    return dispatch


app = create_app()
