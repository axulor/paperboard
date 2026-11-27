"""Readers' reports on notes, sent from the web pages."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.reports import MAX_DETAIL_CHARS, ReportReason, ReportRejected, report_note
from app.rest.papers import Problem


class ReportIn(BaseModel):
    reason: ReportReason
    detail: str = Field(default="", max_length=MAX_DETAIL_CHARS)


class ReportOut(BaseModel):
    id: int


def build_router(sessions: async_sessionmaker[AsyncSession] | None = None) -> APIRouter:
    router = APIRouter(tags=["notes"])

    @router.post(
        "/notes/{note_id}/reports",
        status_code=201,
        summary="Report a note that breaks the rules",
        responses={
            404: {"model": Problem, "description": "No such public note"},
            503: {"model": Problem, "description": "The database is not available"},
        },
    )
    async def post_report(note_id: Annotated[int, Path(ge=1)], report: ReportIn) -> ReportOut:
        if sessions is None:
            raise HTTPException(status_code=503, detail="the database is not available")
        try:
            return ReportOut(id=await report_note(sessions, note_id, report.reason, report.detail))
        except ReportRejected as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
