from datetime import UTC, date, datetime
from pathlib import Path

import httpx2
import pytest

from app.sources import SearchQuery, SortOrder, SourceQueryError, SourceUnavailable
from app.sources.arxiv import (
    API_URL,
    USER_AGENT,
    ArxivId,
    build_search_query,
    parse_arxiv_id,
)
from tests.http_mock import MockHTTP, arxiv_adapter

FIXTURES = Path(__file__).parent / "fixtures" / "arxiv"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2401.12345", ArxivId("2401.12345")),
        ("2401.12345v2", ArxivId("2401.12345", 2)),
        ("0704.0001", ArxivId("0704.0001")),
        ("arXiv:2401.12345", ArxivId("2401.12345")),
        ("  ARXIV:2401.12345v3 ", ArxivId("2401.12345", 3)),
        ("https://arxiv.org/abs/2401.12345v2", ArxivId("2401.12345", 2)),
        ("http://arxiv.org/abs/1706.03762v7", ArxivId("1706.03762", 7)),
        ("https://arxiv.org/pdf/2401.12345.pdf", ArxivId("2401.12345")),
        ("https://arxiv.org/html/2401.12345v1/", ArxivId("2401.12345", 1)),
        ("https://export.arxiv.org/abs/2401.12345?context=cs", ArxivId("2401.12345")),
        ("hep-th/9901001", ArxivId("hep-th/9901001")),
        ("hep-th/9901001v3", ArxivId("hep-th/9901001", 3)),
        ("math.GT/0309136", ArxivId("math.GT/0309136")),
        ("cond-mat/0102536v1", ArxivId("cond-mat/0102536", 1)),
    ],
)
def test_parse_arxiv_id(text: str, expected: ArxivId) -> None:
    assert parse_arxiv_id(text) == expected


@pytest.mark.parametrize(
    "text", ["", "2401.123", "2401.123456", "2401.12345v0", "10.1145/3292500", "hello world"]
)
def test_parse_arxiv_id_rejects_other_text(text: str) -> None:
    with pytest.raises(SourceQueryError):
        parse_arxiv_id(text)


def test_arxiv_id_str_round_trips() -> None:
    assert str(ArxivId("2401.12345", 2)) == "2401.12345v2"
    assert str(ArxivId("hep-th/9901001")) == "hep-th/9901001"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("KV cache compression", "all:kv AND all:cache AND all:compression"),
        ('"kv cache" quantization', 'all:"kv cache" AND all:quantization'),
        ("sparse AND attention OR (x)", "all:sparse AND all:attention AND all:x"),
        ("low-rank all:hack", "all:low-rank AND all:all AND all:hack"),
        ('"and" or', "all:and"),
    ],
)
def test_build_search_query(text: str, expected: str) -> None:
    assert build_search_query(SearchQuery(text=text)) == expected


def test_build_search_query_with_dates() -> None:
    query = SearchQuery(text="kv cache", submitted_from=date(2025, 1, 1))
    assert build_search_query(query) == (
        "all:kv AND all:cache AND submittedDate:[202501010000 TO 299912312359]"
    )
    query = SearchQuery(text="kv", submitted_to=date(2020, 6, 30))
    assert build_search_query(query) == "all:kv AND submittedDate:[199101010000 TO 202006302359]"


def test_build_search_query_needs_a_term() -> None:
    with pytest.raises(SourceQueryError):
        build_search_query(SearchQuery(text="() AND"))


@pytest.mark.anyio
async def test_get_parses_records_in_asked_order(http: MockHTTP) -> None:
    route = http.get(API_URL).mock(return_value=httpx2.Response(200, text=fixture("by_id.xml")))
    async with arxiv_adapter(http) as arxiv:
        records = await arxiv.get(["hep-th/9901001", "arXiv:1706.03762"])

    request = route.last_request
    assert request.url.params["id_list"] == "hep-th/9901001,1706.03762"
    assert request.url.params["max_results"] == "2"
    assert request.headers["User-Agent"] == USER_AGENT

    old, attention = records
    assert attention.source == "arxiv"
    assert attention.source_id == "1706.03762"
    assert attention.version == 7
    assert attention.title == "Attention Is All You Need"
    assert attention.authors[0] == "Ashish Vaswani"
    assert len(attention.authors) == 8
    assert attention.abstract.startswith("The dominant sequence transduction models")
    assert attention.published == datetime(2017, 6, 12, 17, 57, 34, tzinfo=UTC)
    assert attention.updated == datetime(2023, 8, 2, 0, 41, 18, tzinfo=UTC)
    assert attention.primary_category == "cs.CL"
    assert attention.categories == ["cs.CL", "cs.LG"]
    assert attention.comment == "15 pages, 5 figures"
    assert attention.doi is None
    assert attention.abs_url == "https://arxiv.org/abs/1706.03762v7"
    assert attention.pdf_url == "https://arxiv.org/pdf/1706.03762v7"

    assert old.source_id == "hep-th/9901001"
    assert old.version == 3
    assert old.journal_ref == "Prog.Theor.Phys.101:1155-1164,1999"
    assert old.doi == "10.1143/PTP.101.1155"
    assert old.abstract.startswith("We explicitly give")  # leading whitespace removed


@pytest.mark.anyio
async def test_get_leaves_out_unknown_ids(http: MockHTTP) -> None:
    http.get(API_URL).mock(return_value=httpx2.Response(200, text=fixture("missing_id.xml")))
    async with arxiv_adapter(http) as arxiv:
        assert await arxiv.get(["2401.99999"]) == []


@pytest.mark.anyio
async def test_get_with_no_ids_sends_nothing(http: MockHTTP) -> None:
    async with arxiv_adapter(http) as arxiv:
        assert await arxiv.get([]) == []


@pytest.mark.anyio
async def test_search_sends_query_and_parses_results(http: MockHTTP) -> None:
    route = http.get(API_URL).mock(
        return_value=httpx2.Response(200, text=fixture("search_recent.xml"))
    )
    query = SearchQuery(
        text="kv cache compression",
        sort=SortOrder.RECENT,
        submitted_from=date(2025, 1, 1),
        submitted_to=date(2026, 12, 31),
        limit=3,
        offset=0,
    )
    async with arxiv_adapter(http) as arxiv:
        result = await arxiv.search(query)

    params = route.last_request.url.params
    assert params["search_query"] == (
        "all:kv AND all:cache AND all:compression AND submittedDate:[202501010000 TO 202612312359]"
    )
    assert params["sortBy"] == "submittedDate"
    assert params["sortOrder"] == "descending"
    assert params["max_results"] == "3"
    assert params["start"] == "0"

    assert result.total == 736
    assert result.offset == 0
    assert len(result.records) == 3
    assert result.records[0].source_id == "2611.32954"
    assert result.records[0].title.startswith("LoomKV")
    dates = [r.published for r in result.records]
    assert dates == sorted(dates, reverse=True)


@pytest.mark.anyio
async def test_rejected_query_reports_arxivs_message(http: MockHTTP) -> None:
    http.get(API_URL).mock(return_value=httpx2.Response(400, text=fixture("bad_query.xml")))
    async with arxiv_adapter(http) as arxiv:
        with pytest.raises(SourceQueryError, match="Invalid query string"):
            await arxiv.search(SearchQuery(text="anything"))


@pytest.mark.anyio
async def test_retries_server_errors_then_succeeds(http: MockHTTP) -> None:
    route = http.get(API_URL).mock(
        side_effect=[
            httpx2.Response(503),
            httpx2.ConnectTimeout("timeout"),
            httpx2.Response(200, text=fixture("missing_id.xml")),
        ]
    )
    async with arxiv_adapter(http) as arxiv:
        assert await arxiv.get(["2401.99999"]) == []
    assert route.call_count == 3


@pytest.mark.anyio
async def test_gives_up_after_max_attempts(http: MockHTTP) -> None:
    route = http.get(API_URL).mock(return_value=httpx2.Response(503))
    async with arxiv_adapter(http) as arxiv:
        with pytest.raises(SourceUnavailable):
            await arxiv.get(["2401.12345"])
    assert route.call_count == 3


def test_retry_after_is_capped() -> None:
    from app.sources.arxiv import MAX_RETRY_AFTER_SECONDS, retry_after_seconds

    assert retry_after_seconds({"Retry-After": "5"}) == 5.0
    assert retry_after_seconds({"Retry-After": "3600"}) == MAX_RETRY_AFTER_SECONDS
    assert retry_after_seconds({"Retry-After": "soon"}) == 0.0
    assert retry_after_seconds({}) == 0.0
