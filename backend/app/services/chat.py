from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatMessage
from app.models.enums import ChatRole
from app.schemas.chat import ChatMessageResponse
from app.schemas.search import Citation, SearchFilters, SearchRequest


async def fetch_recent_history(
    db: AsyncSession,
    *,
    session_id: str,
    tenant_id: str,
    turns: int,
) -> list[tuple[str, str]]:
    """
    Load the most recent ``turns`` question/answer exchanges in chat order.

    Returns ``(role, content)`` pairs with role in ``{"user", "assistant"}``.
    The in-flight turn is persisted only after the LLM completes, so this
    naturally returns just the prior conversation.
    """
    if turns <= 0:
        return []
    rows = (
        await db.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.tenant_id == tenant_id,
            )
            .order_by(
                ChatMessage.ordinal.desc(),
                ChatMessage.created_at.desc(),
                ChatMessage.id.desc(),
            )
            .limit(turns * 2)
        )
    ).all()
    return [
        (message.role.value.lower(), message.content)
        for message in reversed(list(rows))
    ]


def scoped_search_request(query: str, meeting_id: str, top_k: int | None = None) -> SearchRequest:
    """
    Build a search request hard-scoped to a single meeting.

    The meeting scope is injected server-side from the chat session; the
    client can never influence which meeting is searched.
    """
    return SearchRequest(
        query=query,
        filters=SearchFilters(meeting_id=meeting_id),
        top_k=top_k,
    )


def build_chat_messages(
    *,
    session_id: str,
    tenant_id: str,
    ordinal: int,
    question: str,
    answer: str,
    citations: list[Citation],
    evidence_sufficient: bool,
    search_query_id: str,
    answer_generation_id: str | None,
) -> tuple[ChatMessage, ChatMessage]:
    """
    Build the USER and ASSISTANT message pair for one chat turn.

    The user message takes ``ordinal`` and the assistant message takes
    ``ordinal + 1`` so conversation order is deterministic regardless of the
    second-precision ``created_at`` column.
    """
    now = datetime.now(UTC)
    user_message = ChatMessage(
        tenant_id=tenant_id,
        session_id=session_id,
        ordinal=ordinal,
        role=ChatRole.USER,
        content=question,
        search_query_id=search_query_id,
        created_at=now,
    )
    assistant_message = ChatMessage(
        tenant_id=tenant_id,
        session_id=session_id,
        ordinal=ordinal + 1,
        role=ChatRole.ASSISTANT,
        content=answer,
        citations_json=[item.model_dump(mode="json") for item in citations],
        evidence_sufficient=evidence_sufficient,
        search_query_id=search_query_id,
        answer_generation_id=answer_generation_id,
        created_at=now,
    )
    return user_message, assistant_message


def message_to_response(message: ChatMessage) -> ChatMessageResponse:
    citations = [Citation(**item) for item in (message.citations_json or [])]
    return ChatMessageResponse(
        id=message.id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        citations=citations,
        evidence_sufficient=message.evidence_sufficient,
        created_at=message.created_at,
    )
