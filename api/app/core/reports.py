"""Readers' reports on notes, and taking notes down.

A report stores the reason and what the reader wrote, nothing about the reader. A moderator
takes the note down (it is no longer shown; replies to it say so) or keeps it.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Note, NoteReport, Paper

ReportReason = Literal["spam", "illegal", "privacy", "misleading", "other"]
MAX_DETAIL_CHARS = 500


class ReportRejected(ValueError):
    """The report was not stored, or the note does not exist."""


class OpenReport(BaseModel):
    id: int
    note_id: int
    reason: ReportReason
    detail: str
    created_at: datetime
    note_kind: str
    note_status: str
    note_body: str
    source_id: str
    version: int


async def report_note(
    sessions: async_sessionmaker[AsyncSession],
    note_id: int,
    reason: ReportReason,
    detail: str = "",
) -> int:
    """Store a report on a public note; returns its id."""
    detail = detail.strip()
    if len(detail) > MAX_DETAIL_CHARS:
        raise ReportRejected(f"detail has more than {MAX_DETAIL_CHARS} characters")
    async with sessions.begin() as session:
        note = await session.get(Note, note_id)
        if note is None or note.status != "public":
            raise ReportRejected(f"there is no public note {note_id}")
        report = NoteReport(note_id=note_id, reason=reason, detail=detail)
        session.add(report)
        await session.flush()
        return report.id


async def open_reports(
    sessions: async_sessionmaker[AsyncSession], *, limit: int = 100
) -> list[OpenReport]:
    """Reports nobody has handled yet, oldest first."""
    async with sessions() as session:
        rows = await session.execute(
            select(NoteReport, Note, Paper.source_id)
            .join(Note, Note.id == NoteReport.note_id)
            .join(Paper, Paper.id == Note.paper_id)
            .where(NoteReport.resolution.is_(None))
            .order_by(NoteReport.created_at, NoteReport.id)
            .limit(limit)
        )
        return [
            OpenReport.model_validate(
                {
                    "id": report.id,
                    "note_id": note.id,
                    "reason": report.reason,
                    "detail": report.detail,
                    "created_at": report.created_at,
                    "note_kind": note.kind,
                    "note_status": note.status,
                    "note_body": note.body,
                    "source_id": source_id,
                    "version": note.paper_version,
                }
            )
            for report, note, source_id in rows
        ]


async def take_down(sessions: async_sessionmaker[AsyncSession], note_id: int) -> int:
    """Stop showing a note and close its open reports; returns how many were closed."""
    async with sessions.begin() as session:
        note = await session.get(Note, note_id, with_for_update=True)
        if note is None:
            raise ReportRejected(f"there is no note {note_id}")
        note.status = "removed"
        return await _resolve(session, note_id, "removed")


async def keep_note(sessions: async_sessionmaker[AsyncSession], note_id: int) -> int:
    """Close a note's open reports without taking it down; returns how many were closed."""
    async with sessions.begin() as session:
        if await session.get(Note, note_id) is None:
            raise ReportRejected(f"there is no note {note_id}")
        return await _resolve(session, note_id, "kept")


async def _resolve(
    session: AsyncSession, note_id: int, resolution: Literal["removed", "kept"]
) -> int:
    result = await session.execute(
        update(NoteReport)
        .where(NoteReport.note_id == note_id, NoteReport.resolution.is_(None))
        .values(resolution=resolution, resolved_at=datetime.now(UTC))
        .returning(NoteReport.id)
    )
    return len(result.all())
