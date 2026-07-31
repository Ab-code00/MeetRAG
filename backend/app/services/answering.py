import re
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import AnswerGeneration
from app.schemas.search import AskResponse, Citation, SearchResponse
from app.services.openrouter import grounded_completion

SYSTEM_PROMPT = """You are MeetAI's grounded meeting assistant.
Answer only from the EVIDENCE blocks supplied by the user. Never use outside knowledge.
Every factual claim must cite one or more evidence markers exactly like [C1].
If the evidence does not answer the question, say that the meeting evidence is insufficient.
Do not invent people, dates, decisions, or action items. Be concise and direct."""


async def generate_grounded_answer(
    db: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    question: str,
    search: SearchResponse,
    correlation_id: str,
) -> AskResponse:
    settings = get_settings()
    if not search.results:
        return AskResponse(
            answer_id=None,
            answer="I could not find sufficient meeting evidence to answer that question.",
            citations=[],
            evidence_sufficient=False,
        )
    evidence_blocks = []
    citations_by_marker: dict[str, Citation] = {}
    for index, result in enumerate(search.results, start=1):
        marker = f"C{index}"
        evidence_blocks.append(
            f"[{marker}] Meeting: {result.meeting_title} ({result.meeting_id})\n"
            f"Time: {result.start_ms}-{result.end_ms} ms\n"
            f"Speakers: {', '.join(result.speaker_set)}\n{result.text}"
        )
        citations_by_marker[marker] = Citation(
            marker=marker,
            chunk_id=result.chunk_id,
            meeting_id=result.meeting_id,
            meeting_title=result.meeting_title,
            start_ms=result.start_ms,
            end_ms=result.end_ms,
            text=result.text,
        )
    user_prompt = f"QUESTION:\n{question}\n\nEVIDENCE:\n\n" + "\n\n".join(evidence_blocks)
    completion = await grounded_completion(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)
    referenced = list(dict.fromkeys(re.findall(r"\[(C\d+)\]", completion.text)))
    citations = [citations_by_marker[item] for item in referenced if item in citations_by_marker]
    evidence_sufficient = bool(citations)
    answer_text = completion.text
    if not evidence_sufficient:
        answer_text = "I could not produce an answer supported by cited meeting evidence."
    generation = AnswerGeneration(
        tenant_id=tenant_id,
        user_id=user_id,
        search_query_id=search.query_id,
        question=question,
        answer=answer_text,
        citations_json=[item.model_dump(mode="json") for item in citations],
        prompt_version=settings.answer_prompt_version,
        model=settings.openrouter_llm_model,
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
        estimated_cost_usd=0.0 if ":free" in settings.openrouter_llm_model else None,
        latency_ms=completion.latency_ms,
        correlation_id=correlation_id,
        created_at=datetime.now(UTC),
    )
    db.add(generation)
    await db.flush()
    return AskResponse(
        answer_id=generation.id,
        answer=answer_text,
        citations=citations,
        evidence_sufficient=evidence_sufficient,
    )

