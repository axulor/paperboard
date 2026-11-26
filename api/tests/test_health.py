from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from app import VERSION
from app.config import Settings
from app.main import create_app


def test_health() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": VERSION}


def test_database_is_checked_at_startup_and_disposed_at_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "postgresql+psycopg://127.0.0.1/paperboard_test"
    engine = MagicMock(spec=AsyncEngine)
    connection = AsyncMock()
    engine.connect.return_value.__aenter__.return_value = connection
    create_engine = MagicMock(return_value=engine)
    monkeypatch.setattr("app.main.create_async_engine", create_engine)
    app = create_app(Settings(database_url=SecretStr(url)))

    with TestClient(app):
        create_engine.assert_called_once_with(url)
        connection.execute.assert_awaited_once()
        assert app.state.db_engine is engine
        engine.dispose.assert_not_awaited()

    engine.dispose.assert_awaited_once()
