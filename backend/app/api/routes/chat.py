import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import Auth, DbSession, correlation_id
from app.api.routes.meetings import _tenant_meeting
from app.core.config import get_settings
from app.models import ChatMessage, ChatSession
from app.schemas.chat import (
    ChatAskRequest,
    ChatMessageListResponse,
    ChatMessageResponse,
    ChatSessionCreateRequest,
    ChatSessionListResponse,
    ChatSessionResponse,
)
from app.schemas.search import AskResponse
from app.services.answering import generate_grounded_answer, generate_grounded_answer_stream
from app.services.audit import add_audit_log
from app.services.chat import (
    build_chat_messages,
    fetch_recent_history,
    message_to_response,
    scoped_search_request,
)
from app.services.openrouter import ModelProviderError
from app.services.retrieval import semantic_search

router = APIRouter(tags=["chat"])


def _sse(event: str, data: dict[str, Any]) -> str:
    """Serialize one Server-Sent Events frame."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _tenant_session(
    db: DbSession, session_id: str, tenant_id: str, user_id: str, for_update: bool = False
) -> ChatSession:
    statement = select(ChatSession).where(
        ChatSession.id == session_id,
        ChatSession.tenant_id == tenant_id,
        ChatSession.user_id == user_id,
        ChatSession.deleted_at.is_(None),
    )
    if for_update:
        statement = statement.with_for_update()
    session = await db.scalar(statement)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session


@router.post(
    "/meetings/{meeting_id}/chats",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_chat_session(
    meeting_id: str,
    payload: ChatSessionCreateRequest,
    request: Request,
    auth: Auth,
    db: DbSession,
) -> ChatSessionResponse:
    await _tenant_meeting(db, meeting_id, auth.tenant_id)
    session = ChatSession(
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        meeting_id=meeting_id,
        title=payload.title,
    )
    db.add(session)
    await db.flush()
    add_audit_log(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="CHAT_SESSION_CREATE",
        resource_type="chat_session",
        resource_id=session.id,
        correlation_id=correlation_id(request),
    )
    await db.commit()
    await db.refresh(session)
    return ChatSessionResponse(
        id=session.id,
        meeting_id=session.meeting_id,
        title=session.title,
        message_count=0,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.get("/meetings/{meeting_id}/chats", response_model=ChatSessionListResponse)
async def list_chat_sessions(
    meeting_id: str, auth: Auth, db: DbSession
) -> ChatSessionListResponse:
    await _tenant_meeting(db, meeting_id, auth.tenant_id)
    rows = (
        await db.execute(
            select(ChatSession, func.count(ChatMessage.id))
            .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
            .where(
                ChatSession.meeting_id == meeting_id,
                ChatSession.tenant_id == auth.tenant_id,
                ChatSession.user_id == auth.user_id,
                ChatSession.deleted_at.is_(None),
            )
            .group_by(ChatSession.id)
            .order_by(ChatSession.updated_at.desc())
        )
    ).all()
    items = [
        ChatSessionResponse(
            id=session.id,
            meeting_id=session.meeting_id,
            title=session.title,
            message_count=count,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
        for session, count in rows
    ]
    return ChatSessionListResponse(items=items, total=len(items))


@router.get("/chats/{session_id}/messages", response_model=ChatMessageListResponse)
async def list_chat_messages(
    session_id: str,
    auth: Auth,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChatMessageListResponse:
    """
    List messages newest-first with limit/offset pagination.

    The client reverses the page for display and fetches older pages by
    increasing ``offset``; ``has_more`` signals whether older messages exist.
    """
    await _tenant_session(db, session_id, auth.tenant_id, auth.user_id)
    total = await db.scalar(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.session_id == session_id,
            ChatMessage.tenant_id == auth.tenant_id,
        )
    )
    messages = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.tenant_id == auth.tenant_id,
                )
                .order_by(
                    ChatMessage.ordinal.desc(),
                    ChatMessage.created_at.desc(),
                    ChatMessage.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    items = [message_to_response(message) for message in messages]
    return ChatMessageListResponse(
        items=items,
        total=total or 0,
        has_more=offset + len(items) < (total or 0),
        limit=limit,
        offset=offset,
    )


@router.post("/chats/{session_id}/messages", response_model=ChatMessageResponse)
async def ask_in_chat(
    session_id: str,
    payload: ChatAskRequest,
    request: Request,
    auth: Auth,
    db: DbSession,
) -> ChatMessageResponse:
    session = await _tenant_session(db, session_id, auth.tenant_id, auth.user_id)
    settings = get_settings()
    history = await fetch_recent_history(
        db,
        session_id=session.id,
        tenant_id=auth.tenant_id,
        turns=settings.chat_history_turns,
    )
    try:
        search_response = await semantic_search(
            db,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            payload=scoped_search_request(payload.query, session.meeting_id, payload.top_k),
            correlation_id=correlation_id(request),
        )
        answer = await generate_grounded_answer(
            db,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            question=payload.query,
            search=search_response,
            correlation_id=correlation_id(request),
            history=history,
        )
    except ModelProviderError as exc:
        await db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Lock the session row and read the per-session ordinal counter. The
    # counter is read and written through the locked row (a current read), so
    # concurrent asks for the same session serialize here — the second request
    # sees the first request's committed counter. A plain MAX(ordinal) SELECT
    # would be a REPEATABLE-READ snapshot read and could return a stale value
    # (duplicate ordinal) when two asks overlap.
    session = await _tenant_session(
        db, session_id, auth.tenant_id, auth.user_id, for_update=True
    )
    next_ordinal = (session.last_message_ordinal or 0) + 1
    session.last_message_ordinal = next_ordinal + 1
    user_message, assistant_message = build_chat_messages(
        session_id=session.id,
        tenant_id=auth.tenant_id,
        ordinal=next_ordinal,
        question=payload.query,
        answer=answer.answer,
        citations=answer.citations,
        evidence_sufficient=answer.evidence_sufficient,
        search_query_id=search_response.query_id,
        answer_generation_id=answer.answer_id,
    )
    db.add_all([user_message, assistant_message])
    session.updated_at = datetime.now(UTC)
    add_audit_log(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="CHAT_ASK",
        resource_type="chat_session",
        resource_id=session.id,
        correlation_id=correlation_id(request),
        details={"evidence_sufficient": answer.evidence_sufficient},
    )
    await db.commit()
    return message_to_response(assistant_message)


@router.post("/chats/{session_id}/messages/stream")
async def ask_in_chat_stream(
    session_id: str,
    payload: ChatAskRequest,
    request: Request,
    auth: Auth,
    db: DbSession,
) -> StreamingResponse:
    """
    Ask a question and stream the answer over Server-Sent Events.

    Event protocol:

    - ``status``: ``{"message": str}`` — progress hints (searching, …)
    - ``delta``: ``{"text": str}`` — one token chunk of the answer
    - ``done``: ``{"message": ChatMessageResponse}`` — the persisted
      assistant message (citations included)
    - ``error``: ``{"message": str}`` — provider/answer failure; nothing was
      persisted for this turn

    The turn is persisted only after the stream completes, under the same
    ``SELECT ... FOR UPDATE`` ordinal reservation as the non-streaming route,
    so concurrent asks can't collide on the ``(session_id, ordinal)`` unique
    constraint. On client disconnect (``CancelledError``) nothing is written.
    """
    session = await _tenant_session(db, session_id, auth.tenant_id, auth.user_id)
    settings = get_settings()
    history = await fetch_recent_history(
        db,
        session_id=session.id,
        tenant_id=auth.tenant_id,
        turns=settings.chat_history_turns,
    )

    async def event_source() -> AsyncIterator[str]:
        try:
            yield _sse("status", {"message": "Searching the meeting transcript…"})
            search_response = await semantic_search(
                db,
                tenant_id=auth.tenant_id,
                user_id=auth.user_id,
                payload=scoped_search_request(payload.query, session.meeting_id, payload.top_k),
                correlation_id=correlation_id(request),
            )
            answer: AskResponse | None = None
            async for event in generate_grounded_answer_stream(
                db,
                tenant_id=auth.tenant_id,
                user_id=auth.user_id,
                question=payload.query,
                search=search_response,
                correlation_id=correlation_id(request),
                history=history,
            ):
                # Narrow on the payload type, not the "kind" tag — mypy can't
                # narrow a destructured tuple element via the sibling
                # discriminant.
                if isinstance(event[1], str):
                    yield _sse("delta", {"text": event[1]})
                else:
                    answer = event[1]
            if answer is None:
                raise ModelProviderError("Answer generation returned no result")
            # Re-select under FOR UPDATE to reserve ordinals through the locked
            # row; the counter is a current read, immune to REPEATABLE-READ
            # snapshot staleness.
            locked_session = await _tenant_session(
                db, session_id, auth.tenant_id, auth.user_id, for_update=True
            )
            next_ordinal = (locked_session.last_message_ordinal or 0) + 1
            locked_session.last_message_ordinal = next_ordinal + 1
            user_message, assistant_message = build_chat_messages(
                session_id=locked_session.id,
                tenant_id=auth.tenant_id,
                ordinal=next_ordinal,
                question=payload.query,
                answer=answer.answer,
                citations=answer.citations,
                evidence_sufficient=answer.evidence_sufficient,
                search_query_id=search_response.query_id,
                answer_generation_id=answer.answer_id,
            )
            db.add_all([user_message, assistant_message])
            locked_session.updated_at = datetime.now(UTC)
            add_audit_log(
                db,
                tenant_id=auth.tenant_id,
                user_id=auth.user_id,
                action="CHAT_ASK",
                resource_type="chat_session",
                resource_id=locked_session.id,
                correlation_id=correlation_id(request),
                details={"evidence_sufficient": answer.evidence_sufficient},
            )
            await db.commit()
            yield _sse("done", {"message": message_to_response(assistant_message).model_dump(mode="json")})
        except ModelProviderError as exc:
            await db.rollback()
            yield _sse("error", {"message": str(exc)})
        except Exception:
            await db.rollback()
            yield _sse("error", {"message": "Answer generation failed. Please try again."})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/chats/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(
    session_id: str, request: Request, auth: Auth, db: DbSession
) -> None:
    session = await _tenant_session(db, session_id, auth.tenant_id, auth.user_id)
    session.deleted_at = datetime.now(UTC)
    add_audit_log(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="CHAT_SESSION_DELETE",
        resource_type="chat_session",
        resource_id=session.id,
        correlation_id=correlation_id(request),
    )
    await db.commit()
