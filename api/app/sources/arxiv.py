"""arXiv adapter: search and fetch records through the arXiv API (export.arxiv.org).

arXiv asks API clients for at most one request every three seconds over a single connection;
`ArxivAdapter` enforces that with one shared `RateLimiter` per instance, so the app should keep
one instance per process. Metadata from the API is CC0. Full text is not fetched here.
"""

import asyncio
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from itertools import batched
from types import TracebackType
from typing import Self
from xml.etree.ElementTree import Element, ParseError

import httpx
from defusedxml import ElementTree

from app import VERSION
from app.sources.base import (
    PaperRecord,
    SearchQuery,
    SearchResult,
    SortOrder,
    SourceError,
    SourceQueryError,
    SourceUnavailable,
)
from app.sources.ratelimit import RateLimiter

API_URL = "https://export.arxiv.org/api/query"
USER_AGENT = f"PaperBoard/{VERSION} (+https://github.com/axulor/paperboard)"
MIN_INTERVAL_SECONDS = 3.0
MAX_IDS_PER_REQUEST = 100

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

# New-style identifiers (since 2007): YYMM.NNNN, five digits since 2015.
# Old-style: archive[.SUBCLASS]/YYMMNNN, e.g. hep-th/9901001, math.GT/0309136.
_ID_RE = re.compile(
    r"(?P<base>\d{4}\.\d{4,5}|[a-z]+(?:-[a-z]+)*(?:\.[A-Z]{2})?/\d{7})(?:v(?P<version>[1-9]\d*))?"
)
_URL_PREFIX = re.compile(r"^https?://(?:www\.|export\.)?arxiv\.org/(?:abs|pdf|html)/", re.I)
_ARXIV_PREFIX = re.compile(r"^arxiv:", re.I)

_TOKEN_RE = re.compile(r'"([^"]+)"|(\S+)')
_UNSAFE_CHARS = re.compile(r"[^\w.+-]")
_OPERATORS = {"and", "or", "not", "andnot"}


@dataclass(frozen=True)
class ArxivId:
    base: str
    version: int | None = None

    def __str__(self) -> str:
        return self.base if self.version is None else f"{self.base}v{self.version}"


def parse_arxiv_id(text: str) -> ArxivId:
    """Accepts 2401.12345, 2401.12345v2, arXiv:2401.12345, abs/pdf/html URLs and old-style ids."""
    s = _URL_PREFIX.sub("", text.strip())
    s = _ARXIV_PREFIX.sub("", s)
    s = s.split("?", 1)[0].split("#", 1)[0].rstrip("/").removesuffix(".pdf")
    match = _ID_RE.fullmatch(s)
    if match is None:
        raise SourceQueryError(f"not an arXiv identifier: {text!r}")
    version = match.group("version")
    return ArxivId(match.group("base"), int(version) if version else None)


def build_search_query(query: SearchQuery) -> str:
    """Turn free text into an arXiv search_query: every term must appear (AND).

    Quoted phrases stay together. Characters with a meaning in arXiv's query syntax are removed,
    and boolean operators typed as words are dropped, so user text cannot change the query's
    structure.
    """
    parts: list[str] = []
    for phrase, word in _TOKEN_RE.findall(query.text):
        if phrase:
            term = _clean(phrase)
            if term:
                parts.append(f'all:"{term}"' if " " in term else f"all:{term}")
            continue
        for piece in _clean(word).split():
            piece = piece.strip(".+-")
            if piece and piece not in _OPERATORS:
                parts.append(f"all:{piece}")
    if not parts:
        raise SourceQueryError(f"no searchable terms in {query.text!r}")
    if query.submitted_from or query.submitted_to:
        start = (query.submitted_from or date(1991, 1, 1)).strftime("%Y%m%d") + "0000"
        end = (query.submitted_to or date(2999, 12, 31)).strftime("%Y%m%d") + "2359"
        parts.append(f"submittedDate:[{start} TO {end}]")
    return " AND ".join(parts)


def _clean(text: str) -> str:
    return " ".join(_UNSAFE_CHARS.sub(" ", text).split()).strip(".+-").lower()


def _sort_params(sort: SortOrder) -> dict[str, str]:
    if sort is SortOrder.RECENT:
        return {"sortBy": "submittedDate", "sortOrder": "descending"}
    return {"sortBy": "relevance", "sortOrder": "descending"}


def _text(element: Element, path: str) -> str | None:
    found = element.find(path, _NS)
    if found is None or found.text is None:
        return None
    return " ".join(found.text.split()) or None


def _required(element: Element, path: str) -> str:
    value = _text(element, path)
    if value is None:
        raise SourceError(f"arXiv entry is missing {path}")
    return value


def _parse_entry(entry: Element) -> PaperRecord:
    entry_id = _required(entry, "atom:id")
    if "/api/errors" in entry_id:
        raise SourceQueryError(_text(entry, "atom:summary") or "arXiv rejected the query")
    arxiv_id = parse_arxiv_id(entry_id)
    version = arxiv_id.version or 1
    primary = entry.find("arxiv:primary_category", _NS)
    pdf_url = next(
        (
            link.get("href")
            for link in entry.findall("atom:link", _NS)
            if link.get("title") == "pdf"
        ),
        None,
    )
    return PaperRecord(
        source="arxiv",
        source_id=arxiv_id.base,
        version=version,
        title=_required(entry, "atom:title"),
        authors=[
            name
            for author in entry.findall("atom:author", _NS)
            if (name := _text(author, "atom:name"))
        ],
        abstract=_text(entry, "atom:summary") or "",
        published=datetime.fromisoformat(_required(entry, "atom:published")),
        updated=datetime.fromisoformat(_required(entry, "atom:updated")),
        primary_category=primary.get("term") if primary is not None else None,
        categories=[term for c in entry.findall("atom:category", _NS) if (term := c.get("term"))],
        comment=_text(entry, "arxiv:comment"),
        journal_ref=_text(entry, "arxiv:journal_ref"),
        doi=_text(entry, "arxiv:doi"),
        abs_url=f"https://arxiv.org/abs/{arxiv_id.base}v{version}",
        pdf_url=pdf_url,
    )


def parse_feed(xml: str) -> SearchResult:
    """Parse an API response. Raises SourceQueryError if arXiv reported an error entry."""
    try:
        root = ElementTree.fromstring(xml)
    except ParseError as exc:
        raise SourceError("arXiv returned a response that is not valid XML") from exc
    records = [_parse_entry(entry) for entry in root.findall("atom:entry", _NS)]
    return SearchResult(
        total=int(_text(root, "opensearch:totalResults") or len(records)),
        offset=int(_text(root, "opensearch:startIndex") or 0),
        records=records,
    )


def _retry_after_seconds(response: httpx.Response) -> float:
    try:
        return float(response.headers.get("Retry-After", "0"))
    except ValueError:
        return 0.0


class ArxivAdapter:
    name = "arxiv"

    def __init__(
        self,
        *,
        base_url: str = API_URL,
        min_interval: float = MIN_INTERVAL_SECONDS,
        timeout: float = 30.0,
        max_attempts: int = 3,
        retry_backoff: float = MIN_INTERVAL_SECONDS,
        limiter: RateLimiter | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url
        self._limiter = limiter or RateLimiter(min_interval)
        self._max_attempts = max_attempts
        self._retry_backoff = retry_backoff
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search(self, query: SearchQuery) -> SearchResult:
        params = {
            "search_query": build_search_query(query),
            "start": str(query.offset),
            "max_results": str(query.limit),
            **_sort_params(query.sort),
        }
        return parse_feed(await self._fetch(params))

    async def get(self, ids: Sequence[str]) -> list[PaperRecord]:
        asked = list(dict.fromkeys(parse_arxiv_id(i) for i in ids))
        found: dict[tuple[str, int], PaperRecord] = {}
        for chunk in batched(asked, MAX_IDS_PER_REQUEST):
            params = {"id_list": ",".join(map(str, chunk)), "max_results": str(len(chunk))}
            for record in parse_feed(await self._fetch(params)).records:
                found[(record.source_id, record.version)] = record

        results: list[PaperRecord] = []
        for arxiv_id in asked:
            if arxiv_id.version is not None:
                record = found.get((arxiv_id.base, arxiv_id.version))
            else:
                versions = [r for (base, _), r in found.items() if base == arxiv_id.base]
                record = max(versions, key=lambda r: r.version, default=None)
            if record is not None:
                results.append(record)
        return results

    async def _fetch(self, params: Mapping[str, str]) -> str:
        delay = 0.0
        last_error: Exception | None = None
        for _ in range(self._max_attempts):
            if delay:
                await asyncio.sleep(delay)
            try:
                async with self._limiter.slot():
                    response = await self._client.get(self._base_url, params=params)
            except httpx.TransportError as exc:
                last_error = exc
                delay = max(delay * 2, self._retry_backoff)
                continue

            if response.status_code == 200:
                return response.text
            if response.status_code == 429 or response.status_code >= 500:
                last_error = SourceUnavailable(f"arXiv answered HTTP {response.status_code}")
                delay = max(delay * 2, self._retry_backoff, _retry_after_seconds(response))
                continue
            # Other 4xx: arXiv explains the problem in an error entry.
            try:
                parse_feed(response.text)
            except SourceQueryError:
                raise
            except SourceError:
                pass
            raise SourceQueryError(f"arXiv rejected the request (HTTP {response.status_code})")

        raise SourceUnavailable(
            f"arXiv did not answer after {self._max_attempts} attempts"
        ) from last_error
