"""Lab 07 API tests using an injected index, without loading real files."""

from contextlib import asynccontextmanager
import pytest
from fastapi.testclient import TestClient

from findex.index import DocMeta, Index, Posting
from findex.web.app import app, get_index


@pytest.fixture
def small_index():
    return Index(
        postings={"python": [Posting(0, 1), Posting(1, 1)], "java": [Posting(1, 1)]},
        doc_lengths={0: 2, 1: 3},
        doc_meta={0: DocMeta("a.txt", "Alpha", "Python is great"), 1: DocMeta("b.txt", "Beta", "Python and Java")},
    )


@pytest.fixture
def client(small_index):
    app.dependency_overrides[get_index] = lambda: small_index
    with TestClient(app) as test_client:
        test_client.app.state.index = small_index
        yield test_client
    app.dependency_overrides.clear()


def test_search_pagination(client):
    response = client.get("/search", params={"q": "python", "k": 1, "page": 2})
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert len(response.json()["results"]) == 1


@pytest.mark.parametrize(
    "params",
    [
        {"q": ""},
        {"q": "python", "k": 0},
        {"q": "python", "k": "abc"},
        {"q": "python", "page": 0},
        {"q": "python", "scorer": "invalid"},
    ],
)
def test_query_validation(client, params):
    response = client.get("/search", params=params)
    assert response.status_code == 422
    assert "detail" in response.json()


def test_doc_and_not_found(client):
    assert client.get("/docs/0").json()["title"] == "Alpha"
    assert client.get("/docs/123").status_code == 404
    assert client.get("/doc/123").status_code == 404


def test_stats_health_and_ui(client):
    assert client.get("/stats").json()["documents"] == 2
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/?q=python").status_code == 200
    assert client.get("/doc/0").status_code == 200
    assert client.get("/docs").status_code == 200


def test_health_503_without_index():
    @asynccontextmanager
    async def no_index_lifespan(application):
        application.state.index = None
        yield

    original = app.router.lifespan_context
    app.router.lifespan_context = no_index_lifespan
    try:
        with TestClient(app) as unready:
            assert unready.get("/health").status_code == 503
    finally:
        app.router.lifespan_context = original
