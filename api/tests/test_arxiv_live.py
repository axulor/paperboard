"""Calls the real arXiv API. Run by hand: uv run pytest -m live"""

from datetime import date

import pytest

from app.sources import ArxivAdapter, SearchQuery, SortOrder

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_get_known_paper() -> None:
    async with ArxivAdapter() as arxiv:
        [record] = await arxiv.get(["1706.03762"])
    assert record.title == "Attention Is All You Need"
    assert record.version >= 7


async def test_search_recent_papers() -> None:
    async with ArxivAdapter() as arxiv:
        result = await arxiv.search(
            SearchQuery(
                text='"kv cache"',
                sort=SortOrder.RECENT,
                submitted_from=date(2025, 1, 1),
                limit=5,
            )
        )
    assert result.total > 0
    assert 0 < len(result.records) <= 5
    assert all(r.published.date() >= date(2025, 1, 1) for r in result.records)
