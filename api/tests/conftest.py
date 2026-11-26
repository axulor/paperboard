import pytest

from tests.http_mock import MockHTTP


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def http() -> MockHTTP:
    return MockHTTP()
