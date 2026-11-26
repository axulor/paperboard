"""Finding papers and the facts about one paper. Shared by the MCP tools and the REST API."""

from typing import Literal

import anyio
from pydantic import BaseModel

from app.sources import ArxivAdapter, SearchQuery, SearchResult, SourceError
from app.sources.base import PaperFacts
from app.sources.codelinks import CodeLink
from app.verify.fulltext import parse_fulltext


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
    arxiv: ArxivAdapter, paper: str, *, scan_full_text: bool = True
) -> PaperReport | None:
    """Facts about a paper; None if arXiv does not know it.

    With `scan_full_text`, the latest version is downloaded once to look for code links
    that only appear in the body. Withdrawn papers are not scanned: their latest version is a
    withdrawal notice.
    """
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
