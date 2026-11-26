import asyncio
import os
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from mcp import Client
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.papers import check_paper
from app.db.models import Paper
from app.mcp.server import build_mcp_server
from app.sources.arxiv import API_URL, HTML_URL, OAI_URL, PDF_URL
from tests.http_mock import MockHTTP, Route, arxiv_adapter

PAPER_ID = "2401.04088"
PAPER_HTML_URL = HTML_URL.format(f"{PAPER_ID}v1")
FIXTURES = Path(__file__).parent / "fixtures" / "arxiv"
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str | tuple[str, dict[str, object]]:
    if sys.platform == "win32":
        return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}
    return "asyncio"


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


async def test_check_paper_reuses_report_for_versioned_url(
    http: MockHTTP,
    paper_requests: tuple[Route, Route, Route],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with (
        arxiv_adapter(http) as arxiv,
        Client(build_mcp_server(arxiv, sessions=sessions)) as client,
    ):
        first = await client.call_tool("check_paper", {"paper": PAPER_ID})
        assert not first.is_error
        assert [route.call_count for route in paper_requests] == [1, 1, 1]
        cached = await client.call_tool(
            "check_paper", {"paper": f"https://arxiv.org/abs/{PAPER_ID}v1"}
        )
        assert not cached.is_error
        assert cached.content == first.content
        assert [route.call_count for route in paper_requests] == [1, 1, 1]


async def test_expired_paper_refreshes_in_place(
    http: MockHTTP,
    paper_requests: tuple[Route, Route, Route],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with arxiv_adapter(http) as arxiv:
        assert await check_paper(arxiv, PAPER_ID, sessions=sessions) is not None
        expired = datetime.now(UTC) - timedelta(hours=25)
        async with sessions.begin() as session:
            row_id = await session.scalar(select(Paper.id).where(Paper.source_id == PAPER_ID))
            assert row_id is not None
            await session.execute(
                update(Paper).where(Paper.id == row_id).values(fetched_at=expired)
            )

        assert await check_paper(arxiv, PAPER_ID, sessions=sessions) is not None
        assert [route.call_count for route in paper_requests] == [2, 2, 2]
        assert await check_paper(arxiv, PAPER_ID, sessions=sessions) is not None
        assert [route.call_count for route in paper_requests] == [2, 2, 2]
        async with sessions() as session:
            [row] = (await session.scalars(select(Paper).where(Paper.source_id == PAPER_ID))).all()
            assert row.id == row_id
            assert row.fetched_at > expired


async def test_failed_full_text_fetch_is_retried(
    http: MockHTTP,
    paper_requests: tuple[Route, Route, Route],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    paper_requests[2].mock(return_value=httpx2.Response(404))
    pdf = http.get(PDF_URL.format(f"{PAPER_ID}v1")).mock(return_value=httpx2.Response(404))
    async with arxiv_adapter(http) as arxiv:
        for _ in range(2):
            report = await check_paper(arxiv, PAPER_ID, sessions=sessions)
            assert report is not None and report.full_text_problem is not None
    assert [route.call_count for route in (*paper_requests, pdf)] == [2, 2, 2, 2]
    async with sessions() as session:
        assert await session.scalar(select(Paper).where(Paper.source_id == PAPER_ID)) is None


async def test_an_older_source_version_does_not_replace_a_newer_cached_version(
    http: MockHTTP,
    sessions: async_sessionmaker[AsyncSession],
    paper_requests: tuple[Route, Route, Route],
) -> None:
    async with arxiv_adapter(http) as arxiv:
        first = await check_paper(arxiv, PAPER_ID, sessions=sessions)
        assert first is not None
        newer_facts = first.facts.model_copy(update={"latest_version": 2, "withdrawn": True})
        expired = datetime.now(UTC) - timedelta(hours=25)
        async with sessions.begin() as session:
            await session.execute(
                update(Paper)
                .where(Paper.source_id == PAPER_ID)
                .values(
                    latest_version=2,
                    facts=newer_facts.model_dump(mode="json"),
                    full_text_url=None,
                    full_text_format=None,
                    fetched_at=expired,
                )
            )
        refreshed = await check_paper(arxiv, PAPER_ID, sessions=sessions)
        assert refreshed is not None
        assert refreshed.facts.latest_version == 2 and refreshed.facts.withdrawn
        assert [route.call_count for route in paper_requests] == [2, 2, 2]
        async with sessions() as session:
            row = await session.scalar(select(Paper).where(Paper.source_id == PAPER_ID))
            assert row is not None
            assert row.latest_version == 2
            assert row.fetched_at == expired
