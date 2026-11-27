"""Readers' reports and taking notes down, against a real PostgreSQL test database."""

from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import moderate
from app.config import Settings
from app.core.accounts import create_account_with_token
from app.core.notes import paper_notes
from app.core.reports import (
    ReportRejected,
    keep_note,
    open_reports,
    report_note,
    take_down,
)
from app.db.models import Note, NoteReport
from app.main import create_app
from app.rest.notes import build_router
from tests.conftest import PAPER_ID
from tests.http_mock import MockHTTP, Route
from tests.test_notes import post

pytestmark = pytest.mark.anyio

Sessions = async_sessionmaker[AsyncSession]
Requests = tuple[Route, Route, Route]


@pytest.fixture
async def note(http: MockHTTP, paper_requests: Requests, sessions: Sessions) -> int:
    account = (await create_account_with_token(sessions, "test")).account_id
    return await post(http, sessions, account)


async def test_reports_are_stored_and_listed(sessions: Sessions, note: int) -> None:
    first = await report_note(sessions, note, "spam", "  selling essays  ")
    await report_note(sessions, note, "misleading")
    reports = await open_reports(sessions)
    assert reports[0].id == first
    assert (reports[0].reason, reports[0].detail, reports[0].source_id) == (
        "spam",
        "selling essays",
        PAPER_ID,
    )
    with pytest.raises(ReportRejected, match="more than 500"):
        await report_note(sessions, note, "other", "x" * 501)
    with pytest.raises(ReportRejected, match="no public note 999"):
        await report_note(sessions, 999, "other")


async def test_taking_a_note_down_hides_it_and_closes_its_reports(
    sessions: Sessions, note: int
) -> None:
    await report_note(sessions, note, "illegal")
    assert await take_down(sessions, note) == 1
    assert await open_reports(sessions) == []
    assert (await paper_notes(sessions, "arxiv", PAPER_ID)).total == 0
    async with sessions() as session:
        stored = await session.get(Note, note)
        assert stored is not None and stored.status == "removed"
        report = (await session.scalars(select(NoteReport))).one()
        assert report.resolution == "removed" and report.resolved_at is not None
    # A note that was taken down cannot be reported again.
    with pytest.raises(ReportRejected):
        await report_note(sessions, note, "spam")
    with pytest.raises(ReportRejected, match="no note 999"):
        await take_down(sessions, 999)


async def test_keeping_a_note_closes_its_reports(sessions: Sessions, note: int) -> None:
    await report_note(sessions, note, "other", "looks fine to me")
    assert await keep_note(sessions, note) == 1
    assert await keep_note(sessions, note) == 0
    assert (await paper_notes(sessions, "arxiv", PAPER_ID)).total == 1
    with pytest.raises(ReportRejected, match="no note 999"):
        await keep_note(sessions, 999)


async def test_rest_report_route(sessions: Sessions, note: int) -> None:
    app = FastAPI()
    app.include_router(build_router(sessions), prefix="/api")
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(f"/api/notes/{note}/reports", json={"reason": "spam"})
        assert created.status_code == 201 and created.json()["id"] > 0
        missing = await client.post("/api/notes/999/reports", json={"reason": "spam"})
        assert missing.status_code == 404
        bad = await client.post(f"/api/notes/{note}/reports", json={"reason": "boring"})
        assert bad.status_code == 422


def test_report_route_without_a_database() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        response = client.post("/api/notes/1/reports", json={"reason": "spam"})
    assert response.status_code == 503


async def test_moderation_commands(sessions: Sessions, note: int) -> None:
    assert await moderate.list_reports(sessions) == "No open reports."
    await report_note(sessions, note, "privacy", "has a\nphone number")
    listed = await moderate.list_reports(sessions)
    assert f"note {note} (key_point, public) on arXiv {PAPER_ID}v1 · privacy" in listed
    assert "Reader: has a phone number" in listed
    assert "Note: Mixtral beats Llama 2 70B" in listed
    assert await moderate.keep(sessions, note) == f"Kept note {note}; closed 1 report(s)."
    assert await moderate.remove(sessions, note) == f"Took down note {note}; closed 0 report(s)."


def test_moderation_command_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from pydantic import SecretStr

    assert moderate.main(["list"], settings=Settings(database_url=None)) == 1
    assert "PAPERBOARD_DATABASE_URL" in capsys.readouterr().err

    seen: list[Any] = []

    async def fake_run(database_url: str, action: Any) -> str:
        seen.append(database_url)
        if len(seen) == 3:
            raise ReportRejected("there is no note 9")
        return "done"

    monkeypatch.setattr(moderate, "run", fake_run)
    settings = Settings(database_url=SecretStr("postgresql+psycopg://db"))
    assert moderate.main(["list"], settings=settings) == 0
    assert moderate.main(["remove", "9"], settings=settings) == 0
    assert moderate.main(["keep", "9"], settings=settings) == 1
    output = capsys.readouterr()
    assert output.out == "done\ndone\n" and "there is no note 9" in output.err
