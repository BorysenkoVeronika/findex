"""Pydantic models at the HTTP boundary."""

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    q: str = Field(min_length=1, max_length=200)
    k: int = Field(default=10, ge=1, le=100)
    scorer: str = "bm25"
    page: int = Field(default=1, ge=1)


class SearchResult(BaseModel):
    doc_id: int
    title: str
    score: float
    snippet: str


class SearchResponse(BaseModel):
    query: str
    total: int
    took_ms: float
    results: list[SearchResult]


class DocumentResponse(BaseModel):
    doc_id: int
    title: str
    path: str
    text: str


class StatsResponse(BaseModel):
    documents: int
    vocabulary: int
    tokens: int
    uptime_s: float
