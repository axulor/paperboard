"""Papers for the web pages. Same logic and cache as the check_paper tool."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.papers import PaperReport, check_paper
from app.sources import ArxivAdapter, SourceError
from app.sources.base import SourceQueryError


class Problem(BaseModel):
    detail: str


def build_router(
    arxiv: ArxivAdapter, *, sessions: async_sessionmaker[AsyncSession] | None = None
) -> APIRouter:
    router = APIRouter(tags=["papers"])

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
