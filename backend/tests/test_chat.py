from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.api.routes.chat import _sse
from app.models import ChatMessage
from app.models.enums import ChatRole
from app.schemas.chat import ChatAskRequest
from app.schemas.search import Citation, SearchResponse, SearchResult
from app.services.answering import (
    _build_evidence,
    _truncated_history,
    generate_grounded_answer_stream,
)
from app.services.chat import build_chat_messages, message_to_response, scoped_search_request
from app.services.openrouter import _build_messages

CITATION_DICT = {
    "marker": "C1",
    "chunk_id": "chunk-1",
    "meeting_id": "meeting-1",
    "meeting_title": "Weekly Sync",
    "start_ms": 1000,
    "end_ms": 4000,
    "text": "We decided to ship on Friday.",
}


def test_scoped_search_request_forces_meeting_filter() -> None:
    request = scoped_search_request("who decided to ship?", "meeting-1", top_k=5)
    assert request.query == "who decided to ship?"
    assert request.filters.meeting_id == "meeting-1"
    assert request.top_k == 5


def test_scoped_search_request_defaults_top_k() -> None:
    request = scoped_search_request("hello?", "meeting-1")
    assert request.top_k is None
    assert request.filters.meeting_id == "meeting-1"


def test_build_chat_messages_creates_user_assistant_pair() -> None:
    citation = Citation(**CITATION_DICT)
    user_message, assistant_message = build_chat_messages(
        session_id="session-1",
        tenant_id="tenant-1",
        ordinal=3,
        question="When do we ship?",
        answer="We ship on Friday. [C1]",
        citations=[citation],
        evidence_sufficient=True,
        search_query_id="query-1",
        answer_generation_id="answer-1",
    )
    assert user_message.role == ChatRole.USER
    assert user_message.content == "When do we ship?"
    assert user_message.ordinal == 3
    assert user_message.search_query_id == "query-1"
    assert user_message.answer_generation_id is None
    assert assistant_message.role == ChatRole.ASSISTANT
    assert assistant_message.content == "We ship on Friday. [C1]"
    assert assistant_message.ordinal == 4
    assert assistant_message.evidence_sufficient is True
    assert assistant_message.search_query_id == "query-1"
    assert assistant_message.answer_generation_id == "answer-1"
    assert assistant_message.citations_json == [CITATION_DICT]


def test_build_chat_messages_no_citations() -> None:
    _, assistant_message = build_chat_messages(
        session_id="session-1",
        tenant_id="tenant-1",
        ordinal=1,
        question="What?",
        answer="Insufficient evidence.",
        citations=[],
        evidence_sufficient=False,
        search_query_id="query-1",
        answer_generation_id=None,
    )
    assert assistant_message.citations_json == []
    assert assistant_message.evidence_sufficient is False


def test_message_to_response_round_trip() -> None:
    message = ChatMessage(
        tenant_id="tenant-1",
        session_id="session-1",
        ordinal=1,
        role=ChatRole.ASSISTANT,
        content="We ship on Friday. [C1]",
        citations_json=[CITATION_DICT],
        evidence_sufficient=True,
        search_query_id="query-1",
        answer_generation_id="answer-1",
        created_at=datetime.now(UTC),
    )
    message.id = "message-1"
    response = message_to_response(message)
    assert response.id == "message-1"
    assert response.role == ChatRole.ASSISTANT
    assert response.evidence_sufficient is True
    assert len(response.citations) == 1
    assert response.citations[0].marker == "C1"
    assert response.citations[0].chunk_id == "chunk-1"


def test_chat_ask_request_rejects_short_query() -> None:
    with pytest.raises(ValidationError):
        ChatAskRequest(query="x")


def test_sse_event_formatting() -> None:
    frame = _sse("delta", {"text": "hello"})
    assert frame == 'event: delta\ndata: {"text": "hello"}\n\n'


def test_sse_event_formatting_serializes_datetimes() -> None:
    frame = _sse("done", {"when": datetime.now(UTC)})
    assert frame.startswith("event: done\ndata: {")
    assert "when" in frame
    assert frame.endswith("\n\n")


def test_build_evidence_caps_prompt_blocks_and_length() -> None:
    """The LLM prompt gets at most N truncated blocks, but all results stay citable."""
    results = [
        SearchResult(
            chunk_id=f"chunk-{i}",
            clean_chunk_id=f"clean-{i}",
            meeting_id="meeting-1",
            meeting_title="Weekly Sync",
            meeting_date=None,
            start_ms=0,
            end_ms=1000,
            speaker_set=["A"],
            text="The team discussed the rollout plan. " * 200,
            score=1.0,
            metadata={},
        )
        for i in range(1, 9)
    ]
    search = SearchResponse(query_id="query-1", results=results, latency_ms=1)
    blocks, citations = _build_evidence(search, max_blocks=5, max_chars=120)
    assert len(blocks) == 5
    assert len(citations) == 8  # every marker still resolves
    assert all(len(block) < 400 for block in blocks)  # truncated, not raw 15k chars
    # Truncation lands on a sentence boundary when possible.
    assert all("." in block for block in blocks)


def test_build_messages_orders_system_history_user() -> None:
    messages = _build_messages(
        system_prompt="sys",
        history=[("user", "q1"), ("assistant", "a1"), ("user", "q2")],
        user_prompt="q3",
    )
    assert messages == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "user", "content": "q3"},
    ]


def test_build_messages_without_history() -> None:
    messages = _build_messages(system_prompt="sys", history=None, user_prompt="q")
    assert messages == [{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}]


def test_truncated_history_caps_each_message() -> None:
    truncated = _truncated_history(
        [("user", "long " * 1000), ("assistant", "short")], max_chars=100
    )
    assert truncated is not None
    assert len(truncated) == 2
    assert truncated[0][0] == "user"
    assert len(truncated[0][1]) <= 100
    assert truncated[1] == ("assistant", "short")


def test_truncated_history_strips_stale_citation_markers() -> None:
    truncated = _truncated_history(
        [("assistant", "TCS provides solutions. [C1]"), ("user", "was this his answer?")],
        max_chars=500,
    )
    assert truncated == [("assistant", "TCS provides solutions."), ("user", "was this his answer?")]


def test_truncated_history_empty_or_none() -> None:
    assert _truncated_history(None, 100) is None
    assert _truncated_history([], 100) is None


def test_build_evidence_short_results_are_not_truncated() -> None:
    search = SearchResponse(
        query_id="query-1",
        results=[
            SearchResult(
                chunk_id="chunk-1",
                clean_chunk_id="clean-1",
                meeting_id="meeting-1",
                meeting_title="Weekly Sync",
                meeting_date=None,
                start_ms=0,
                end_ms=1000,
                speaker_set=["A"],
                text="We decided to ship on Friday.",
                score=1.0,
                metadata={},
            )
        ],
        latency_ms=1,
    )
    blocks, citations = _build_evidence(search, max_blocks=5, max_chars=2000)
    assert blocks[0].endswith("We decided to ship on Friday.")
    assert citations["C1"].text == "We decided to ship on Friday."


async def test_generate_grounded_answer_stream_no_evidence_yields_single_result() -> None:
    search = SearchResponse(query_id="query-1", results=[], latency_ms=1)
    events = [
        event
        async for event in generate_grounded_answer_stream(
            None,  # db is never touched on the no-evidence path
            tenant_id="tenant-1",
            user_id="user-1",
            question="what happened?",
            search=search,
            correlation_id="corr-1",
        )
    ]
    assert len(events) == 1
    kind, answer = events[0]
    assert kind == "result"
    assert answer.answer_id is None
    assert answer.evidence_sufficient is False
    assert answer.citations == []
    assert "meeting evidence" in answer.answer
