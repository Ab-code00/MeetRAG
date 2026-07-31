from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ChatRole
from app.schemas.search import Citation


class ChatSessionCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=300)


class ChatSessionResponse(BaseModel):
    id: str
    meeting_id: str
    title: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime


class ChatSessionListResponse(BaseModel):
    items: list[ChatSessionResponse]
    total: int


class ChatMessageResponse(BaseModel):
    id: str
    session_id: str
    role: ChatRole
    content: str
    citations: list[Citation] = Field(default_factory=list)
    evidence_sufficient: bool | None = None
    created_at: datetime


class ChatMessageListResponse(BaseModel):
    items: list[ChatMessageResponse]
    total: int
    has_more: bool
    limit: int
    offset: int


class ChatAskRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)
