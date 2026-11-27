"""Papers and their notes for the web pages. Same logic and cache as the MCP tools."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.notes import PaperNotes, paper_notes
from app.core.papers import PaperReport, check_paper
from app.sources import ArxivAdapter, SourceError
from app.sources.arxiv import parse_arxiv_id
from app.sources.base import SourceQueryError


class Problem(BaseModel):
    detail: str


def build_router(
    arxiv: ArxivAdapter, *, sessions: async_sessionmaker[AsyncSession] | None = None
) -> APIRouter:
    router = APIRouter(tags=["papers"])

    # Before the paper route: its {paper:path} would also match ".../notes".
    @router.get(
        "/papers/arxiv/{paper:path}/notes",
        summary="Public notes on one arXiv paper, newest first",
        responses={404: {"model": Problem, "description": "Not an arXiv id"}},
    )
    async def get_arxiv_paper_notes(
        paper: Annotated[str, Path(description="arXiv id, with or without version")],
        limit: Annotated[int, Query(ge=1, le=200, description="How many notes to return")] = 100,
    ) -> PaperNotes:
        try:
            source_id = parse_arxiv_id(paper).base
        except SourceQueryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if sessions is None:
            return PaperNotes(counts={}, latest=[])
        return await paper_notes(sessions, arxiv.name, source_id, limit=limit)

    @router.get(
        "/papers/arxiv/{paper:path}",
        summary="Facts about one arXiv paper",
        responses={
            404: {"model": Problem, "description": "Not an arXiv id, or arXiv has no such paper"},
            503: {"model": Problem, "description": "arXiv could not be reached"},
        },
    )
    async def get_arxiv_paper(
        paper: Annotated[
            str,
            Path(description="arXiv id, with or without version: 2401.12345, hep-th/9901001v2"),
        ],
    ) -> PaperReport:
        try:
            report = await check_paper(arxiv, paper, sessions=sessions)
        except SourceQueryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SourceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if report is None:
            raise HTTPException(status_code=404, detail=f"arXiv has no paper {paper!r}")
        return report

    return router
