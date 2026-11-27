import asyncio
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.sources.arxiv import API_URL, HTML_URL, OAI_URL
from tests.http_mock import MockHTTP, Route

FIXTURES = Path(__file__).parent / "fixtures" / "arxiv"
PAPER_ID = "2401.04088"
PAPER_HTML_URL = HTML_URL.format(f"{PAPER_ID}v1")


@pytest.fixture
def anyio_backend() -> str | tuple[str, dict[str, object]]:
    # psycopg's async mode cannot use the Proactor event loop that Windows uses by default.
    if sys.platform == "win32":
        return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}
    return "asyncio"


@pytest.fixture
def http() -> MockHTTP:
    return MockHTTP()


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = os.environ.get("PAPERBOARD_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PAPERBOARD_TEST_DATABASE_URL is not set")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                yield async_sessionmaker(connection, join_transaction_mode="create_savepoint")
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
def paper_requests(http: MockHTTP) -> tuple[Route, Route, Route]:
    return (
        http.get(API_URL).mock(
            return_value=httpx2.Response(
                200, content=(FIXTURES / "api_2401.04088.xml").read_bytes()
            )
        ),
        http.get(OAI_URL).mock(
            return_value=httpx2.Response(
                200, content=(FIXTURES / "oai_2401.04088.xml").read_bytes()
            )
        ),
        http.get(PAPER_HTML_URL).mock(
            return_value=httpx2.Response(
                200,
                content=(FIXTURES / "html_2401.04088v1.html").read_bytes(),
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        ),
    )
