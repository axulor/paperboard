from pathlib import Path
from typing import Any

import httpx2
import pytest
from mcp import Client
from mcp_types import TextContent

from app.mcp.server import build_mcp_server
from app.sources.arxiv import API_URL, HTML_URL, OAI_URL, PDF_URL
from tests.http_mock import MockHTTP, arxiv_adapter

FIXTURES = Path(__file__).parent / "fixtures" / "arxiv"
pytestmark = pytest.mark.anyio


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def xml(name: str) -> httpx2.Response:
    return httpx2.Response(200, text=fixture(name))


async def call(http: MockHTTP, tool: str, arguments: dict[str, Any]) -> tuple[bool, str]:
    async with arxiv_adapter(http) as arxiv, Client(build_mcp_server(arxiv)) as client:
        result = await client.call_tool(tool, arguments)
    [content] = result.content
    assert isinstance(content, TextContent)
    return bool(result.is_error), content.text


async def test_tools_are_listed_as_read_only(http: MockHTTP) -> None:
    async with arxiv_adapter(http) as arxiv, Client(build_mcp_server(arxiv)) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    assert set(tools) == {"find_sources", "check_paper", "search_topic"}
    for tool in tools.values():
        assert tool.annotations is not None and tool.annotations.read_only_hint
        assert tool.description is not None
        assert "arXiv" in tool.description and "论文" in tool.description


async def test_find_sources(http: MockHTTP) -> None:
    route = http.get(API_URL).mock(return_value=xml("search_recent.xml"))
    is_error, text = await call(
        http,
        "find_sources",
        {
            "query": "kv cache compression",
            "sort": "recent",
            "submitted_from": "2025-01-01",
            "submitted_to": "2026-12-31",
            "limit": 3,
        },
    )
    assert not is_error
    assert text.startswith(
        "arXiv: 736 papers for `kv cache compression` "
        "(newest first, submitted 2025-01-01 to 2026-12-31). Showing 1-3."
    )
    assert "1. LoomKV: Lossless KV Cache Compression" in text
    assert "arXiv 2611.32954v1 · submitted 2026-11-24 · cs.AI" in text
    assert text.endswith("More: call again with offset=3.")
    params = route.last_request.url.params
    assert params["sortBy"] == "submittedDate"
    assert params["max_results"] == "3"


async def test_find_sources_without_results(http: MockHTTP) -> None:
    http.get(API_URL).mock(return_value=xml("missing_id.xml"))
    is_error, text = await call(http, "find_sources", {"query": "nothing matches this"})
    assert not is_error
    assert text.startswith("arXiv: no papers found for `nothing matches this`")


async def test_find_sources_reports_arxiv_errors(http: MockHTTP) -> None:
    http.get(API_URL).mock(return_value=httpx2.Response(400, text=fixture("bad_query.xml")))
    is_error, text = await call(http, "find_sources", {"query": "anything"})
    assert is_error
    assert "Invalid query string" in text


async def test_check_paper(http: MockHTTP) -> None:
    http.get(API_URL).mock(return_value=xml("api_2401.04088.xml"))
    http.get(OAI_URL).mock(return_value=xml("oai_2401.04088.xml"))
    http.get(HTML_URL.format("2401.04088v1")).mock(
        return_value=httpx2.Response(
            200,
            content=(FIXTURES / "html_2401.04088v1.html").read_bytes(),
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )
    is_error, text = await call(http, "check_paper", {"paper": "arXiv:2401.04088"})
    assert not is_error
    lines = text.split("\n")
    assert lines[0] == "Mixtral of Experts"
    assert lines[1] == "arXiv 2401.04088 · latest version v1 · 1 version: v1 2024-01-08"
    assert "Withdrawn: no" in lines
    assert "License: CC BY 4.0" in lines
    assert (
        "Code, models and data linked from the paper: "
        "https://github.com/mistralai/mistral-src (repository)"
    ) in lines
    assert lines[-1] == (
        "Read: https://arxiv.org/abs/2401.04088v1 · "
        "full text (HTML): https://arxiv.org/html/2401.04088v1"
    )


async def test_check_paper_withdrawn_is_not_downloaded(http: MockHTTP) -> None:
    # No route for the full text: a download attempt would fail the test.
    http.get(API_URL).mock(return_value=xml("api_2611.30211.xml"))
    http.get(OAI_URL).mock(return_value=xml("oai_2611.30211.xml"))
    is_error, text = await call(http, "check_paper", {"paper": "2611.30211"})
    assert not is_error
    assert "Withdrawn: yes (This paper has been withdrawn" in text
    assert "Code, models and data linked from the paper: none in the metadata" in text


async def test_check_paper_without_full_text(http: MockHTTP) -> None:
    http.get(API_URL).mock(return_value=xml("api_2401.04088.xml"))
    http.get(OAI_URL).mock(return_value=xml("oai_2401.04088.xml"))
    http.get(HTML_URL.format("2401.04088v1")).mock(return_value=httpx2.Response(404))
    http.get(PDF_URL.format("2401.04088v1")).mock(return_value=httpx2.Response(404))
    is_error, text = await call(http, "check_paper", {"paper": "2401.04088"})
    assert not is_error
    assert "Code, models and data linked from the paper: none in the metadata" in text
    assert text.endswith("Full text could not be read: arXiv has no full text for 2401.04088v1")


@pytest.mark.parametrize(
    ("paper", "message"),
    [("2401.99999", "arXiv has no paper"), ("hello world", "not an arXiv identifier")],
)
async def test_check_paper_errors(http: MockHTTP, paper: str, message: str) -> None:
    http.get(API_URL).mock(return_value=xml("missing_id.xml"))
    is_error, text = await call(http, "check_paper", {"paper": paper})
    assert is_error
    assert message in text


def test_descriptions_and_instructions_match_the_skill_text() -> None:
    """skill/tool-descriptions.md is where the wording is edited."""
    import re

    from app.mcp import server

    text = (Path(__file__).parents[2] / "skill" / "tool-descriptions.md").read_text("utf-8")
    blocks = dict(re.findall(r"## (\w+)\n\n```text\n(.*?)\n```", text, re.DOTALL))
    assert blocks == {
        "find_sources": server.FIND_SOURCES,
        "check_paper": server.CHECK_PAPER,
        "search_topic": server.SEARCH_TOPIC,
        "post_note": server.POST_NOTE,
        "withdraw": server.WITHDRAW_NOTE,
        "instructions": server.INSTRUCTIONS,
    }


async def test_every_description_has_english_and_chinese_keywords(http: MockHTTP) -> None:
    # Some clients search tools by keyword before loading them.
    from app.mcp.server import INSTRUCTIONS

    async with arxiv_adapter(http) as arxiv, Client(build_mcp_server(arxiv)) as client:
        tools = (await client.list_tools()).tools
        assert client.instructions == INSTRUCTIONS
    for tool in tools:
        description = tool.description or ""
        assert len(description) <= 600, tool.name
        assert any(word in description for word in ("paper", "arXiv", "citation")), tool.name
        assert any(word in description for word in ("论文", "文献", "引用", "复现")), tool.name
