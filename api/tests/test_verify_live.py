"""Checks quotes against the real arXiv. Run by hand: uv run pytest -m live"""

import pytest

from app.sources import ArxivAdapter
from app.verify import QuoteStatus, verify_quotes

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_quotes_in_a_real_paper() -> None:
    async with ArxivAdapter() as arxiv:
        report = await verify_quotes(
            arxiv,
            "1706.03762v7",
            [
                "We propose a new simple network architecture, the Transformer, based solely on "
                "attention mechanisms, dispensing with recurrence and convolutions entirely.",
                "We propose a novel network architecture, the Transformer, based solely on "
                "attention mechanisms, dispensing with recurrence and convolutions entirely.",
            ],
        )
    assert report.format == "html"
    found, near = report.checks
    assert found.status is QuoteStatus.FOUND
    assert found.anchor is not None and found.anchor.startswith(
        "https://arxiv.org/html/1706.03762v7#"
    )
    assert near.status is QuoteStatus.NEAR
    assert (
        near.matched_text is not None and "a new simple network architecture" in near.matched_text
    )
