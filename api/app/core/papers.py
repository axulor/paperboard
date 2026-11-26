"""Finding papers and the facts about one paper. Shared by the MCP tools and the REST API."""

from datetime import UTC, datetime, timedelta
from typing import Literal

import anyio
from pydantic import BaseModel
from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Paper
from app.sources import ArxivAdapter, SearchQuery, SearchResult, SourceError
from app.sources.arxiv import parse_arxiv_id
from app.sources.base import PaperFacts
from app.sources.codelinks import CodeLink
from app.verify.fulltext import parse_fulltext

PAPER_CACHE_TTL = timedelta(hours=24)


class PaperReport(BaseModel):
    facts: PaperFacts
    code_links: list[CodeLink]
    """From the metadata and, when it could be read, the full text."""
    full_text_url: str | None = None
    full_text_format: Literal["html", "pdf"] | None = None
    full_text_problem: str | None = None


async def find_sources(arxiv: ArxivAdapter, query: SearchQuery) -> SearchResult:
    return await arxiv.search(query)


async def check_paper(
    arxiv: ArxivAdapter,
    paper: str,
    *,
    scan_full_text: bool = True,
    sessions: async_sessionmaker[AsyncSession] | None = None,
) -> PaperReport | None:
    """Facts about a paper; None if arXiv does not know it.

    With `scan_full_text`, the latest version is downloaded once to look for code links
    that only appear in the body. Withdrawn papers are not scanned: their latest version is a
    withdrawal notice. The cache stores complete reports.
    """
    if sessions is None or not scan_full_text:
        return await _fetch_paper(arxiv, paper, scan_full_text=scan_full_text)

    source_id = parse_arxiv_id(paper).base
    cached = await _read_cached_report(sessions, arxiv.name, source_id)
    if cached is not None:
        return cached

    # Order concurrent results by source version, then by when the fetch began.
    fetched_at = datetime.now(UTC)
    report = await _fetch_paper(arxiv, source_id, scan_full_text=True)
    if report is None or report.full_text_problem is not None:
        return report
    return await _store_cached_report(sessions, report, fetched_at)


async def _read_cached_report(
    sessions: async_sessionmaker[AsyncSession], source: str, source_id: str
) -> PaperReport | None:
    async with sessions() as session:
        row = await session.scalar(
            select(Paper).where(
                Paper.source == source,
                Paper.source_id == source_id,
                Paper.fetched_at > datetime.now(UTC) - PAPER_CACHE_TTL,
            )
        )
        return _report_from_row(row) if row is not None else None


def _report_from_row(row: Paper) -> PaperReport:
    return PaperReport.model_validate(
        {
            "facts": row.facts,
            "code_links": row.code_links,
            "full_text_url": row.full_text_url,
            "full_text_format": row.full_text_format,
        }
    )


async def _store_cached_report(
    sessions: async_sessionmaker[AsyncSession], report: PaperReport, fetched_at: datetime
) -> PaperReport:
    facts = report.facts
    fields = {
        "title": facts.title,
        "latest_version": facts.latest_version,
        "facts": facts.model_dump(mode="json"),
        "code_links": [link.model_dump(mode="json") for link in report.code_links],
        "full_text_url": report.full_text_url,
        "full_text_format": report.full_text_format,
        "fetched_at": fetched_at,
    }
    statement = insert(Paper).values(source=facts.source, source_id=facts.source_id, **fields)
    fetched = statement.excluded
    upsert = statement.on_conflict_do_update(
        index_elements=[Paper.source, Paper.source_id],
        set_={name: fetched[name] for name in fields},
        where=tuple_(Paper.latest_version, Paper.fetched_at)
        < tuple_(fetched.latest_version, fetched.fetched_at),
    ).returning(Paper.id)
    async with sessions.begin() as session:
        if await session.scalar(upsert) is not None:
            return report
        # A newer report won the conflict. Return the same version as the cache.
        query = select(Paper).where(
            Paper.source == facts.source, Paper.source_id == facts.source_id
        )
        return _report_from_row((await session.scalars(query)).one())


async def _fetch_paper(
    arxiv: ArxivAdapter, paper: str, *, scan_full_text: bool
) -> PaperReport | None:
    facts = await arxiv.facts(paper)
    if facts is None:
        return None
    report = PaperReport(facts=facts, code_links=list(facts.code_links))
    if not scan_full_text or facts.withdrawn:
        return report
    try:
        raw = await arxiv.fetch_fulltext(facts.source_id, facts.latest_version)
        document = await anyio.to_thread.run_sync(parse_fulltext, raw)
    except SourceError as exc:
        report.full_text_problem = str(exc)
        return report
    known = {link.url.lower() for link in report.code_links}
    report.code_links += [link for link in document.code_links() if link.url.lower() not in known]
    report.full_text_url = document.url
    report.full_text_format = document.format
    return report
