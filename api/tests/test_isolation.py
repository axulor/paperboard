import sys

import pytest

from app.sources.arxiv import PDF_URL, RawFullText
from app.verify.fulltext import FullTextError, parse_fulltext, run_isolated
from tests import isolation_targets

GIB = 1024**3


def test_result_comes_back() -> None:
    assert run_isolated(isolation_targets.double, 21, timeout=30, memory_limit=0) == 42


def test_crash_fails_only_that_call() -> None:
    with pytest.raises(FullTextError, match="stopped unexpectedly"):
        run_isolated(isolation_targets.crash, timeout=30, memory_limit=0)


def test_hang_is_stopped() -> None:
    with pytest.raises(FullTextError, match="longer than"):
        run_isolated(isolation_targets.hang, timeout=3, memory_limit=0)


@pytest.mark.skipif(sys.platform == "win32", reason="memory limits need setrlimit")
def test_memory_limit() -> None:
    with pytest.raises(FullTextError, match="MemoryError"):
        run_isolated(isolation_targets.allocate, 4 * GIB, timeout=30, memory_limit=GIB)


def test_broken_pdf_is_reported() -> None:
    raw = RawFullText("2401.00001", 1, "pdf", PDF_URL.format("2401.00001v1"), b"not a pdf")
    with pytest.raises(FullTextError, match="could not parse"):
        parse_fulltext(raw)
