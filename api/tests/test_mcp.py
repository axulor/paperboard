import pytest
from fastapi.testclient import TestClient
from mcp import Client

from app import VERSION
from app.config import Settings
from app.main import create_app
from app.mcp.server import build_mcp_server

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}


@pytest.mark.anyio
async def test_server_identifies_itself() -> None:
    async with Client(build_mcp_server()) as client:
        assert client.server_info is not None
        assert client.server_info.name == "paperboard"
        assert client.server_info.version == VERSION


def test_http_initialize_from_localhost() -> None:
    with TestClient(create_app(), base_url="http://localhost") as client:
        response = client.post("/mcp", json=INITIALIZE, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "paperboard"


def test_http_accepts_configured_public_host() -> None:
    app = create_app(Settings(public_hosts=["paperboard.example"]))
    with TestClient(app, base_url="https://paperboard.example") as client:
        response = client.post("/mcp", json=INITIALIZE, headers=HEADERS)
    assert response.status_code == 200


def test_http_rejects_unknown_host() -> None:
    with TestClient(create_app(), base_url="http://evil.example") as client:
        response = client.post("/mcp", json=INITIALIZE, headers=HEADERS)
    assert response.status_code == 421
