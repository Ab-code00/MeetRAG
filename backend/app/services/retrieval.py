import time
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Meeting, QdrantDocument, SearchQuery, TranscriptChunk, TranscriptChunkClean
from app.schemas.search import SearchRequest, SearchResponse, SearchResult
from app.services.openrouter import embed_texts
from app.services.sparse import sparse_vector
from app.services.vector_store import hybrid_search_points


async def semantic_search(
    db: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    payload: SearchRequest,
    correlation_id: str,
) -> SearchResponse:
    started = time.perf_counter()
    settings = get_settings()
    logger = structlog.get_logger()

    vector = (await embed_texts([payload.query]))[0]
    sparse = sparse_vector(payload.query)
    logger.info(
        "semantic_search_debug",
        query=payload.query[:100],
        vector_dim=len(vector),
        vector_preview=[round(v, 4) for v in vector[:3]],
        sparse_terms=len(sparse.indices),
        embedding_model=settings.openrouter_embedding_model,
        tenant_id=tenant_id,
        score_threshold=settings.retrieval_score_threshold,
        top_k=payload.top_k or settings.retrieval_top_k,
    )

    filter_data = payload.filters.model_dump(mode="json", exclude_none=True)
    hits = await hybrid_search_points(
        tenant_id=tenant_id,
        dense_vector=vector,
        sparse_vector=sparse,
        filters=filter_data,
        limit=payload.top_k or settings.retrieval_top_k,
        candidate_count=settings.retrieval_hybrid_candidates,
        score_threshold=settings.retrieval_score_threshold,
    )
    logger.info(
        "semantic_search_points_found",
        count=len(hits),
        tenant_id=tenant_id,
    )
    hit_payloads = [hit.payload or {} for hit in hits]
    hit_order = {
        str(payload.get("clean_chunk_id")): index for index, payload in enumerate(hit_payloads)
    }
    unit_clean_ids = list(hit_order)
    results: list[SearchResult] = []
    if unit_clean_ids:
        rows = (
            await db.execute(
                select(QdrantDocument, TranscriptChunk, TranscriptChunkClean, Meeting)
                .join(TranscriptChunk, TranscriptChunk.id == QdrantDocument.chunk_id)
                .join(TranscriptChunkClean, TranscriptChunkClean.id == QdrantDocument.clean_chunk_id)
                .join(Meeting, Meeting.id == QdrantDocument.meeting_id)
                .where(
                    QdrantDocument.clean_chunk_id.in_(unit_clean_ids),
                    QdrantDocument.embedding_model == settings.openrouter_embedding_model,
                    QdrantDocument.tenant_id == tenant_id,
                    TranscriptChunk.tenant_id == tenant_id,
                    TranscriptChunkClean.tenant_id == tenant_id,
                    Meeting.tenant_id == tenant_id,
                    QdrantDocument.is_active.is_(True),
                    TranscriptChunk.is_active.is_(True),
                    Meeting.deleted_at.is_(None),
                )
            )
        ).all()
        rows = sorted(rows, key=lambda row: hit_order[row[0].clean_chunk_id])
        score_by_unit = {str(payload.get("clean_chunk_id")): float(hit.score) for hit, payload in zip(hits, hit_payloads, strict=True)}
        dense_by_unit = {str(payload.get("clean_chunk_id")): payload.get("dense_score") for payload in hit_payloads}
        matched_by_unit = {
            str(payload.get("clean_chunk_id")): payload.get("matched_type", "CONTEXT")
            for payload in hit_payloads
        }
        for document, chunk, clean, meeting in rows:
            unit_id = str(document.clean_chunk_id)
            results.append(
                SearchResult(
                    chunk_id=chunk.id,
                    clean_chunk_id=clean.id,
                    meeting_id=meeting.id,
                    meeting_title=meeting.title,
                    meeting_date=meeting.meeting_date.isoformat() if meeting.meeting_date else None,
                    start_ms=chunk.start_ms,
                    end_ms=chunk.end_ms,
                    speaker_set=chunk.speaker_set,
                    text=clean.cleaned_text,
                    score=score_by_unit.get(unit_id, 0.0),
                    metadata={
                        "project": meeting.project,
                        "department": meeting.department,
                        "cleaning_version": clean.cleaning_version,
                        "chunk_strategy_version": chunk.chunk_strategy_version,
                        "embedding_model": document.embedding_model,
                        "matched_type": matched_by_unit.get(unit_id, "CONTEXT"),
                        "dense_score": dense_by_unit.get(unit_id),
                        "turn_span": [chunk.turn_start, chunk.turn_end],
                    },
                )
            )
    latency_ms = round((time.perf_counter() - started) * 1000)
    query = SearchQuery(
        tenant_id=tenant_id,
        user_id=user_id,
        query_text=payload.query,
        filters_json=filter_data,
        result_chunk_ids=[item.chunk_id for item in results],
        result_count=len(results),
        embedding_model=settings.openrouter_embedding_model,
        latency_ms=latency_ms,
        correlation_id=correlation_id,
        created_at=datetime.now(UTC),
    )
    db.add(query)
    await db.flush()
    return SearchResponse(query_id=query.id, results=results, latency_ms=latency_ms)
