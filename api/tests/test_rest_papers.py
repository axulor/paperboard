from collections.abc import Iterator
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.sources.arxiv import API_URL, HTML_URL, OAI_URL, PDF_URL
from tests.http_mock import MockHTTP, arxiv_adapter

FIXTURES = Path(__file__).parent / "fixtures" / "arxiv"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def client(http: MockHTTP) -> Iterator[TestClient]:
    app = create_app(Settings(database_url=None), arxiv=arxiv_adapter(http, max_attempts=1))
    with TestClient(app) as client:
        yield client


def test_paper_facts_and_full_text(http: MockHTTP, client: TestClient) -> None:
    http.get(API_URL).mock(return_value=httpx2.Response(200, content=fixture("api_2401.04088.xml")))
    http.get(OAI_URL).mock(return_value=httpx2.Response(200, content=fixture("oai_2401.04088.xml")))
    http.get(HTML_URL.format("2401.04088v1")).mock(
        return_value=httpx2.Response(
            200,
            content=fixture("html_2401.04088v1.html"),
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )

    response = client.get("/api/papers/arxiv/2401.04088v1")

    assert response.status_code == 200
    body = response.json()
    assert body["facts"]["source_id"] == "2401.04088"
    assert body["facts"]["title"] == "Mixtral of Experts"
    assert body["facts"]["authors"][0] == "Albert Q. Jiang"
    assert body["facts"]["license"] == "CC BY 4.0"
    assert body["full_text_format"] == "html"
    assert body["full_text_url"] == "https://arxiv.org/html/2401.04088v1"
    assert [link["url"] for link in body["code_links"]] == [
        "https://github.com/mistralai/mistral-src"
    ]


def test_old_style_id_with_a_slash(http: MockHTTP, client: TestClient) -> None:
    http.get(API_URL).mock(return_value=httpx2.Response(200, content=fixture("by_id.xml")))
    http.get(OAI_URL).mock(
        return_value=httpx2.Response(200, content=fixture("oai_hep-th_9901001.xml"))
    )
    http.get(HTML_URL.format("hep-th/9901001v3")).mock(return_value=httpx2.Response(404))
    http.get(PDF_URL.format("hep-th/9901001v3")).mock(return_value=httpx2.Response(404))

    response = client.get("/api/papers/arxiv/hep-th/9901001")

    assert response.status_code == 200
    body = response.json()
    assert body["facts"]["source_id"] == "hep-th/9901001"
    assert body["full_text_url"] is None
    assert body["full_text_problem"]


def test_unknown_paper(http: MockHTTP, client: TestClient) -> None:
    http.get(API_URL).mock(return_value=httpx2.Response(200, content=fixture("missing_id.xml")))

    response = client.get("/api/papers/arxiv/2401.99999")

    assert response.status_code == 404
    assert "2401.99999" in response.json()["detail"]


def test_not_an_arxiv_id(client: TestClient) -> None:
    response = client.get("/api/papers/arxiv/not-a-paper")

    assert response.status_code == 404
    assert "not an arXiv identifier" in response.json()["detail"]


def test_arxiv_unavailable(http: MockHTTP, client: TestClient) -> None:
    http.get(API_URL).mock(return_value=httpx2.Response(503))

    response = client.get("/api/papers/arxiv/2401.04088")

    assert response.status_code == 503


def test_notes_without_a_database_are_empty(client: TestClient) -> None:
    response = client.get("/api/papers/arxiv/2401.04088/notes")
    assert response.status_code == 200
    assert response.json() == {"counts": {}, "latest": [], "total": 0}


def test_topics_without_a_database(client: TestClient) -> None:
    assert client.get("/api/topics").json() == []
    assert client.get("/api/topics/1").status_code == 404


def test_sitemap_without_a_database(client: TestClient) -> None:
    assert client.get("/api/sitemap").json() == {"papers": [], "topics": []}
