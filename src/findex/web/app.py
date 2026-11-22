"""ASGI routes, request validation, dependency injection, and HTML UI."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator, Awaitable, Callable
from functools import lru_cache
from html import escape
import logging
from pathlib import Path
import re
import time
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from findex.index import Index
from findex.query import parse
from findex.search import BM25, TfIdf, search as ranked_search
from findex.store import load
from findex.web.models import DocumentResponse, SearchResponse, SearchResult, StatsResponse
from findex.web.settings import Settings

logger = logging.getLogger("findex.web")
_WEB_ROOT = Path(__file__).resolve().parent
_templates = Jinja2Templates(directory=str(_WEB_ROOT / "templates"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    app.state.index = None
    app.state.started = time.monotonic()
    try:
        app.state.index = load(settings.index_path)
        logger.info("Loaded index from %s", settings.index_path)
    except (OSError, ValueError) as exc:
        logger.error("Index unavailable: %s", exc)
    try:
        yield
    finally:
        app.state.index = None
        logger.info("Index released")


app = FastAPI(title="Findex", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(_WEB_ROOT / "static")), name="static")


@app.middleware("http")
async def request_ids(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    identifier = request.headers.get("X-Request-ID") or uuid4().hex
    request.state.request_id = identifier
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Request failed request_id=%s path=%s", identifier, request.url.path)
        response = JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": identifier})
    response.headers["X-Request-ID"] = identifier
    logger.info(
        "request_id=%s method=%s path=%s status=%s", identifier, request.method, request.url.path, response.status_code
    )
    return response


def get_index(request: Request) -> Index:
    index: Index | None = getattr(request.app.state, "index", None)
    if index is None:
        raise HTTPException(status_code=503, detail="Search index unavailable")
    return index


IndexDep = Annotated[Index, Depends(get_index)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
ScorerName = Literal["bm25", "tfidf"]


def _compute(index: Index, q: str, k: int, scorer: ScorerName, page: int) -> SearchResponse:
    start = time.perf_counter()
    try:
        matches = parse(q).evaluate(index)
        ordered = ranked_search(index, q, scorer=BM25() if scorer == "bm25" else TfIdf(), k=page * k)
    except (ValueError, SyntaxError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid query: {exc}") from exc
    results = [
        SearchResult(doc_id=r.doc_id, title=r.title, score=r.score, snippet=r.snippet)
        for r in ordered[(page - 1) * k : page * k]
    ]
    return SearchResponse(
        query=q, total=len(matches), took_ms=round((time.perf_counter() - start) * 1000, 3), results=results
    )


@app.get("/search", response_model=SearchResponse)
def search_route(
    index: IndexDep,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    k: Annotated[int, Query(ge=1, le=100)] = 10,
    scorer: ScorerName = "bm25",
    page: Annotated[int, Query(ge=1)] = 1,
) -> SearchResponse:
    """Blocking ranking deliberately uses a sync route (FastAPI thread pool)."""
    return _compute(index, q, k, scorer, page)


@app.get("/search-async", response_model=SearchResponse, include_in_schema=False)
async def search_async_benchmark(
    index: IndexDep,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    k: Annotated[int, Query(ge=1, le=100)] = 10,
    scorer: ScorerName = "bm25",
    page: Annotated[int, Query(ge=1)] = 1,
) -> SearchResponse:
    """Benchmark comparison: async route with thread offloading."""
    return await asyncio.to_thread(_compute, index, q, k, scorer, page)


@app.get("/docs/{doc_id}", response_model=DocumentResponse)
def document_api(doc_id: int, index: IndexDep) -> DocumentResponse:
    meta = index.doc_meta.get(doc_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse(doc_id=doc_id, title=meta.title, path=meta.path, text=meta.text)


@app.get("/stats", response_model=StatsResponse)
def stats_route(index: IndexDep, request: Request) -> StatsResponse:
    return StatsResponse(
        documents=index.num_docs,
        vocabulary=len(index),
        tokens=sum(index.doc_lengths.values()),
        uptime_s=round(time.monotonic() - getattr(request.app.state, "started", time.monotonic()), 3),
    )


@app.get("/health")
def health(request: Request) -> dict[str, str]:
    if getattr(request.app.state, "index", None) is None:
        raise HTTPException(status_code=503, detail="Search index unavailable")
    return {"status": "ok"}


def _highlight(snippet: str) -> str:
    """Escape stored text before converting the indexer's **term** marks to HTML."""
    safe = escape(snippet)
    return re.sub(r"\*\*(.+?)\*\*", r"<mark>\1</mark>", safe)


@app.get("/", response_class=HTMLResponse)
def homepage(
    request: Request,
    index: IndexDep,
    q: str = "",
    page: Annotated[int, Query(ge=1)] = 1,
) -> HTMLResponse:
    response = _compute(index, q, 10, "bm25", page) if q.strip() else None
    results = (
        [
            {"doc_id": r.doc_id, "title": r.title, "score": r.score, "snippet_html": _highlight(r.snippet)}
            for r in response.results
        ]
        if response
        else []
    )
    return _templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "query": q,
            "results": results,
            "page": page,
            "total": response.total if response else 0,
            "has_next": bool(response and page * 10 < response.total),
            "has_previous": page > 1,
        },
    )


@app.get("/doc/{doc_id}", response_class=HTMLResponse)
def document_page(doc_id: int, request: Request, index: IndexDep) -> HTMLResponse:
    meta = index.doc_meta.get(doc_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return _templates.TemplateResponse(request=request, name="document.html", context={"doc": meta, "doc_id": doc_id})
