from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest

from app.sources import SourceError
from app.sources.arxiv import (
    API_URL,
    HTML_URL,
    OAI_URL,
    RawFullText,
    license_name,
    parse_oai_record,
)
from app.verify.fulltext import parse_fulltext
from tests.http_mock import MockHTTP, arxiv_adapter

FIXTURES = Path(__file__).parent / "fixtures" / "arxiv"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def mock_arxiv(http: MockHTTP, api: str, oai: str) -> None:
    http.get(API_URL).mock(return_value=httpx2.Response(200, text=fixture(api)))
    http.get(OAI_URL).mock(return_value=httpx2.Response(200, text=fixture(oai)))


@pytest.mark.parametrize(
    ("url", "name"),
    [
        ("http://creativecommons.org/licenses/by/4.0/", "CC BY 4.0"),
        ("http://creativecommons.org/licenses/by-nc-sa/4.0/", "CC BY-NC-SA 4.0"),
        ("http://creativecommons.org/publicdomain/zero/1.0/", "CC0 1.0"),
        ("http://arxiv.org/licenses/nonexclusive-distrib/1.0/", "arXiv non-exclusive license"),
        ("http://arxiv.org/licenses/assumed-1991-2003/", "arXiv assumed license (1991-2003)"),
        (None, None),
    ],
)
def test_license_name(url: str | None, name: str | None) -> None:
    assert license_name(url) == name


def test_parse_oai_record(http: MockHTTP) -> None:
    record = parse_oai_record(fixture("oai_1706.03762.xml"))
    assert record is not None
    assert [v.version for v in record.versions] == [1, 2, 3, 4, 5, 6, 7]
    assert record.versions[0].submitted == datetime(2017, 6, 12, 17, 57, 34, tzinfo=UTC)
    assert record.versions[0].size_kb == 1102
    assert record.license_url == "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"


def test_parse_oai_record_unknown_id() -> None:
    assert parse_oai_record(fixture("oai_missing.xml")) is None


def test_parse_oai_record_other_error(http: MockHTTP) -> None:
    xml = (
        '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">'
        '<error code="badArgument">Illegal argument</error></OAI-PMH>'
    )
    with pytest.raises(SourceError, match="badArgument"):
        parse_oai_record(xml)


@pytest.mark.anyio
async def test_facts_of_a_paper_with_many_versions(http: MockHTTP) -> None:
    mock_arxiv(http, "by_id.xml", "oai_1706.03762.xml")
    async with arxiv_adapter(http) as arxiv:
        facts = await arxiv.facts("https://arxiv.org/abs/1706.03762v2")
    assert facts is not None
    assert facts.source_id == "1706.03762"
    assert facts.title == "Attention Is All You Need"
    assert facts.latest_version == 7
    assert len(facts.versions) == 7
    assert facts.withdrawn is False
    assert facts.license == "arXiv non-exclusive license"
    assert facts.comment == "15 pages, 5 figures"
    assert facts.code_links == []


@pytest.mark.anyio
async def test_facts_of_an_old_paper_without_license(http: MockHTTP) -> None:
    mock_arxiv(http, "by_id.xml", "oai_hep-th_9901001.xml")
    async with arxiv_adapter(http) as arxiv:
        facts = await arxiv.facts("hep-th/9901001")
    assert facts is not None
    assert [v.version for v in facts.versions] == [1, 2, 3]
    assert facts.license is None
    assert facts.journal_ref == "Prog.Theor.Phys.101:1155-1164,1999"
    assert facts.doi == "10.1143/PTP.101.1155"


@pytest.mark.anyio
async def test_withdrawn_version_newer_than_oai(http: MockHTTP) -> None:
    # OAI is updated daily: it still lists only v1 while the API already has the withdrawal.
    mock_arxiv(http, "api_2611.30211.xml", "oai_2611.30211.xml")
    async with arxiv_adapter(http) as arxiv:
        facts = await arxiv.facts("2611.30211")
    assert facts is not None
    assert facts.latest_version == 2
    assert [v.version for v in facts.versions] == [1, 2]
    assert facts.versions[1].size_kb is None
    assert facts.withdrawn is True
    assert facts.comment is not None and "withdrawn" in facts.comment


@pytest.mark.anyio
async def test_facts_when_oai_has_no_record_yet(http: MockHTTP) -> None:
    mock_arxiv(http, "api_2611.30211.xml", "oai_missing.xml")
    async with arxiv_adapter(http) as arxiv:
        facts = await arxiv.facts("2611.30211")
    assert facts is not None
    assert [v.version for v in facts.versions] == [2]
    assert facts.license is None


@pytest.mark.anyio
async def test_facts_of_an_unknown_paper(http: MockHTTP) -> None:
    http.get(API_URL).mock(return_value=httpx2.Response(200, text=fixture("missing_id.xml")))
    oai = http.get(OAI_URL)
    async with arxiv_adapter(http) as arxiv:
        assert await arxiv.facts("2401.99999") is None
    assert not oai.called


@pytest.mark.anyio
async def test_facts_license_and_comment_of_a_cc_paper(http: MockHTTP) -> None:
    mock_arxiv(http, "api_2401.04088.xml", "oai_2401.04088.xml")
    async with arxiv_adapter(http) as arxiv:
        facts = await arxiv.facts("2401.04088")
    assert facts is not None
    assert facts.license == "CC BY 4.0"
    assert facts.comment == "See more details at https://mistral.ai/news/mixtral-of-experts/"
    assert facts.code_links == []  # the code link is only in the full text


def test_code_links_in_full_text() -> None:
    raw = RawFullText(
        "2401.04088",
        1,
        "html",
        HTML_URL.format("2401.04088v1"),
        (FIXTURES / "html_2401.04088v1.html").read_bytes(),
    )
    document = parse_fulltext(raw)
    assert "https://github.com/mistralai/mistral-src" in document.links
    assert [link.url for link in document.code_links()] == [
        "https://github.com/mistralai/mistral-src"
    ]
