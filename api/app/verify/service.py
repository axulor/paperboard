from collections.abc import Sequence
from typing import Literal

import anyio
from pydantic import BaseModel

from app.sources.arxiv import ArxivAdapter
from app.verify.fulltext import parse_fulltext
from app.verify.quotes import QuoteCheck, QuoteError, check_quotes, validate_quote


class QuoteReport(BaseModel):
    """What is kept after checking: the quotes, where they are, and a hash of the text.

    The full text itself is discarded.
    """

    source: str
    source_id: str
    version: int
    format: Literal["html", "pdf"]
    url: str
    content_hash: str
    checks: list[QuoteCheck]


async def verify_quotes(
    arxiv: ArxivAdapter, paper: str, quotes: Sequence[str], *, version: int | None = None
) -> QuoteReport:
    """Download one version of an arXiv paper and check each quote against it.

    Quotes are validated before anything is downloaded. Without a version, in the argument or
    the identifier, the latest version is checked.
    """
    if not quotes:
        raise QuoteError("no quotes to check")
    for quote in quotes:
        validate_quote(quote)
    raw = await arxiv.fetch_fulltext(paper, version)
    document = await anyio.to_thread.run_sync(parse_fulltext, raw)
    return QuoteReport(
        source=document.source,
        source_id=document.source_id,
        version=document.version,
        format=document.format,
        url=document.url,
        content_hash=document.content_hash,
        checks=check_quotes(document, quotes),
    )
