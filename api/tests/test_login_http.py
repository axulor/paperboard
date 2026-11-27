"""The login connector over HTTP: bearer tokens, and which address serves which tools."""

from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.applications import Starlette
from starlette.types import Receive, Scope, Send

from app.config import Settings
from app.core.moderation import WordList
from app.core.notes import NotePolicy
from app.main import _by_path, create_app  # pyright: ignore[reportPrivateUsage]
from app.mcp.server import LOGIN_PATH, PUBLIC_PATH, Login, build_mcp_app, build_mcp_server
from app.sources import ArxivAdapter
from tests.test_mcp import HEADERS, INITIALIZE
from tests.test_write_tools import OneTokenVerifier

LIST_TOOLS: dict[str, Any] = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
POLICY = NotePolicy(notes_per_hour=30, blocked_words=WordList([]))


def connector(path: str) -> Starlette:
    # The database is never reached: listing tools and checking tokens do not use it here.
    sessions = async_sessionmaker(create_async_engine("postgresql+psycopg://x:x@127.0.0.1:9/x"))
    login = Login(verifier=OneTokenVerifier(1), policy=POLICY) if path == LOGIN_PATH else None
    server = build_mcp_server(ArxivAdapter(), sessions=sessions, login=login)
    return build_mcp_app(server, [], path)


def post(client: TestClient, path: str, body: dict[str, Any], token: str | None) -> Any:
    headers = HEADERS | ({"Authorization": f"Bearer {token}"} if token is not None else {})
    return client.post(path, json=body, headers=headers)


def tool_names(response: Any) -> set[str]:
    return {tool["name"] for tool in response.json()["result"]["tools"]}


def test_login_address_needs_a_valid_token() -> None:
    with TestClient(connector(LOGIN_PATH), base_url="http://localhost") as client:
        assert post(client, LOGIN_PATH, INITIALIZE, None).status_code == 401
        assert post(client, LOGIN_PATH, INITIALIZE, "wrong").status_code == 401
        response = post(client, LOGIN_PATH, INITIALIZE, "good")
        assert response.status_code == 200
        assert response.json()["result"]["serverInfo"]["name"] == "paperboard"
        names = tool_names(post(client, LOGIN_PATH, LIST_TOOLS, "good"))
    assert {"post_note", "withdraw", "search_topic"} <= names


def test_public_address_has_no_write_tools() -> None:
    with TestClient(connector(PUBLIC_PATH), base_url="http://localhost") as client:
        names = tool_names(post(client, PUBLIC_PATH, LIST_TOOLS, None))
    assert names == {"find_sources", "check_paper", "search_topic"}


def test_app_with_a_database_serves_both_addresses() -> None:
    # Building the app does not connect; the lifespan would.
    settings = Settings(database_url=SecretStr("postgresql+psycopg://x:x@127.0.0.1:9/x"))
    assert create_app(settings) is not None


def test_requests_are_sent_by_exact_path() -> None:
    seen: list[str] = []

    def app(name: str) -> Any:
        async def handle(scope: Scope, receive: Receive, send: Send) -> None:
            seen.append(name)

        return handle

    dispatch = _by_path({LOGIN_PATH: app("login")}, app("public"))

    async def run() -> None:
        for scope in (
            {"type": "http", "path": LOGIN_PATH},
            {"type": "http", "path": PUBLIC_PATH},
            {"type": "http", "path": LOGIN_PATH + "/x"},
            {"type": "lifespan"},
        ):
            await dispatch(scope, _receive, _send)

    anyio.run(run)
    assert seen == ["login", "public", "public", "public"]


async def _receive() -> Any:  # pragma: no cover - never called
    raise AssertionError


async def _send(message: Any) -> None:  # pragma: no cover - never called
    raise AssertionError


@pytest.mark.parametrize("token", [None, "wrong"])
def test_login_address_rejects_tool_calls_without_a_valid_token(token: str | None) -> None:
    with TestClient(connector(LOGIN_PATH), base_url="http://localhost") as client:
        response = post(client, LOGIN_PATH, LIST_TOOLS, token)
    assert response.status_code == 401
    assert "Bearer" in response.headers["www-authenticate"]
