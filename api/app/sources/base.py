"""What every source adapter offers, and the record it returns.

An adapter forwards queries to one open platform's public API. It never stores full text and
never calls a language model.
"""

from collections.abc import Sequence
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field

from app.sources.codelinks import CodeLink


class SourceError(Exception):
    """Base class for adapter errors."""


class SourceQueryError(SourceError):
    """The query or identifier was rejected; retrying the same request will not help."""


class SourceUnavailable(SourceError):
    """The source could not be reached or kept failing after retries."""


class SortOrder(StrEnum):
    RELEVANCE = "relevance"
    RECENT = "recent"


class SearchQuery(BaseModel):
    text: str = Field(min_length=1, description="Keywords. Quoted phrases are kept together.")
    sort: SortOrder = SortOrder.RELEVANCE
    submitted_from: date | None = None
    submitted_to: date | None = None
    limit: int = Field(default=10, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class PaperRecord(BaseModel):
    """Bibliographic record of one version of a work, as the source reports it."""

    source: str
    source_id: str = Field(description="Identifier without version, e.g. 2401.12345")
    version: int
    title: str
    authors: list[str]
    abstract: str
    published: datetime = Field(description="When the first version was submitted")
    updated: datetime = Field(description="When this version was submitted")
    primary_category: str | None = None
    categories: list[str] = []
    comment: str | None = Field(default=None, description="Author comment, as written")
    journal_ref: str | None = None
    doi: str | None = None
    abs_url: str
    pdf_url: str | None = None


class VersionInfo(BaseModel):
    version: int
    submitted: datetime
    size_kb: int | None = None


class PaperFacts(BaseModel):
    """What the source itself says about a work, computed without any AI judgement."""

    source: str
    source_id: str
    title: str
    # Defaults keep reports cached before these fields existed readable.
    authors: list[str] = []
    abstract: str | None = Field(default=None, description="Abstract of the latest version")
    primary_category: str | None = Field(default=None, description="e.g. cs.CL")
    latest_version: int
    versions: list[VersionInfo]
    withdrawn: bool
    license: str | None = Field(default=None, description="Short name, e.g. CC BY 4.0")
    license_url: str | None = None
    comment: str | None = Field(default=None, description="Author comment of the latest version")
    journal_ref: str | None = None
    doi: str | None = None
    code_links: list[CodeLink] = Field(
        default=[], description="Links to code, models or data found in the metadata"
    )


class SearchResult(BaseModel):
    total: int
    offset: int
    records: list[PaperRecord]


class SourceAdapter(Protocol):
    name: str

    async def search(self, query: SearchQuery) -> SearchResult: ...

    async def get(self, ids: Sequence[str]) -> list[PaperRecord]:
        """Records for the given identifiers, in the order asked. Unknown ones are left out."""
        ...
