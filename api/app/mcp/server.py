from datetime import date
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from pydantic import Field
from starlette.applications import Starlette

from app import VERSION
from app.core.papers import check_paper, find_sources
from app.mcp.render import render_paper, render_search
from app.sources import ArxivAdapter, SearchQuery, SortOrder, SourceError

LOCAL_HOSTS = ["localhost", "127.0.0.1", "[::1]", "localhost:*", "127.0.0.1:*", "[::1]:*"]
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)

FIND_SOURCES = """\
Search arXiv for papers on a topic, most relevant or newest first, optionally within a \
submission date range. Use it to find literature on a topic, to check whether something has \
already been studied, or to see the latest papers and progress in a field. \
在 arXiv 上按关键词找论文：找文献、查某个方向有没有人研究过、看最新的论文和进展。
Write the query in English; put "quoted phrases" in quotes. Results are short: title, id, \
date, authors and the start of the abstract."""

CHECK_PAPER = """\
Facts about one arXiv paper, taken from arXiv's own records: its versions and dates, whether \
it was withdrawn, its license, the authors' comment (often the venue), journal reference, \
DOI, and links to code, models or datasets found in the metadata and the full text. Use it \
before citing, recommending or reproducing a paper, or when asked whether a paper's code is \
available. 查一篇论文的事实：版本、是否撤回、许可证、作者备注、代码链接；引用、推荐或复现之前先查。
Accepts an arXiv id (2401.12345, 2401.12345v2, arXiv:2401.12345) or an arxiv.org link."""


def build_mcp_server(arxiv: ArxivAdapter) -> MCPServer:
    """The PaperBoard connector."""
    server = MCPServer(name="paperboard", title="PaperBoard", version=VERSION)

    @server.tool(
        name="find_sources",
        title="Find papers",
        description=FIND_SOURCES,
        annotations=READ_ONLY,
        structured_output=False,
    )
    async def find_sources_tool(
        query: Annotated[str, Field(description="Keywords in English", min_length=1)],
        sort: Annotated[
            Literal["relevance", "recent"], Field(description="relevance, or recent = newest")
        ] = "relevance",
        submitted_from: Annotated[
            date | None, Field(description="Only papers submitted on or after this date")
        ] = None,
        submitted_to: Annotated[
            date | None, Field(description="Only papers submitted on or before this date")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=25, description="How many papers to return")] = 10,
        offset: Annotated[int, Field(ge=0, description="Skip this many, for the next page")] = 0,
    ) -> str:
        search = SearchQuery(
            text=query,
            sort=SortOrder(sort),
            submitted_from=submitted_from,
            submitted_to=submitted_to,
            limit=limit,
            offset=offset,
        )
        try:
            return render_search(search, await find_sources(arxiv, search))
        except SourceError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        name="check_paper",
        title="Check a paper",
        description=CHECK_PAPER,
        annotations=READ_ONLY,
        structured_output=False,
    )
    async def check_paper_tool(
        paper: Annotated[str, Field(description="arXiv id or arxiv.org link", min_length=1)],
    ) -> str:
        try:
            report = await check_paper(arxiv, paper)
        except SourceError as exc:
            raise ToolError(str(exc)) from exc
        if report is None:
            raise ToolError(f"arXiv has no paper {paper!r}")
        return render_paper(report)

    return server


def build_mcp_app(server: MCPServer, public_hosts: list[str]) -> Starlette:
    """Streamable HTTP app serving the connector at /mcp.

    Stateless with plain JSON responses: any worker can answer any request, and clients that do
    not speak SSE still work. Host checking guards against DNS rebinding; only localhost and the
    configured public hosts are accepted.
    """
    hosts = LOCAL_HOSTS + public_hosts
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=[f"http://{h}" for h in hosts] + [f"https://{h}" for h in public_hosts],
    )
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=security,
    )
