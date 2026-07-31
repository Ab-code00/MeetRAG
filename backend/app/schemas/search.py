from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class SearchFilters(BaseModel):
    meeting_id: str | None = None
    speaker: str | None = Field(default=None, max_length=200)
    project: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    date_from: date | None = None
    date_to: date | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    top_k: int | None = Field(default=None, ge=1, le=20)


class SearchResult(BaseModel):
    chunk_id: str
    clean_chunk_id: str
    meeting_id: str
    meeting_title: str
    meeting_date: str | None
    start_ms: int
    end_ms: int
    speaker_set: list[str]
    text: str
    score: float
    metadata: dict[str, Any]


class SearchResponse(BaseModel):
    query_id: str
    results: list[SearchResult]
    latency_ms: int


class AskRequest(SearchRequest):
    pass


class Citation(BaseModel):
    marker: str
    chunk_id: str
    meeting_id: str
    meeting_title: str
    start_ms: int
    end_ms: int
    text: str


class AskResponse(BaseModel):
    answer_id: str | None
    answer: str
    citations: list[Citation]
    evidence_sufficient: bool

