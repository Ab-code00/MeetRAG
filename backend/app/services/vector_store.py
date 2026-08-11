from __future__ import annotations

from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient, models

from app.core.config import get_settings

logger = structlog.get_logger()


def _is_qdrant_configured() -> bool:
    """Check whether Qdrant Cloud/Server URL is configured."""
    settings = get_settings()
    return bool(settings.qdrant_url)


def qdrant_client() -> AsyncQdrantClient | None:
    """
    Return a new Qdrant async client, or ``None`` if Qdrant is not configured.

    Not cached — the pipeline may run in a thread (with its own event loop),
    while search runs in the main async context.  A fresh client each time
    avoids cross-event-loop issues.  Client creation is lightweight
    (HTTP config only; connection pools are established lazily).
    """
    if not _is_qdrant_configured():
        return None
    settings = get_settings()
    try:
        return AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
            timeout=30,
        )
    except Exception as exc:
        logger.warning("qdrant_client_creation_failed", error=str(exc))
        return None


async def ensure_collection() -> bool:
    """
    Create the Qdrant collection and payload indexes if they don't exist.

    The collection uses hybrid vectors: a named dense vector plus a BM25-style
    sparse vector (Qdrant applies IDF server-side). A legacy dense-only
    collection is detected and recreated in place with the hybrid schema.
    Returns True if successful, False if Qdrant is unavailable.
    """
    client = qdrant_client()
    if client is None:
        return False

    settings = get_settings()
    try:
        exists = await client.collection_exists(settings.qdrant_collection)
        if exists:
            info = await client.get_collection(settings.qdrant_collection)
            params = getattr(info.config, "params", None)
            has_sparse = bool(getattr(params, "sparse_vectors", None))
            if not has_sparse:
                logger.warning(
                    "qdrant_collection_recreating_hybrid",
                    collection=settings.qdrant_collection,
                    reason="legacy_dense_only_schema",
                )
                await client.delete_collection(settings.qdrant_collection)
                exists = False
        if not exists:
            await client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config={
                    "dense": models.VectorParams(
                        size=settings.embedding_dimension, distance=models.Distance.COSINE
                    )
                },
                sparse_vectors_config={
                    "sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )
            # Payload indexes only need to exist once. Re-issuing
            # create_payload_index on every search/upsert would make Qdrant
            # return a 409 per field per call (caught below) — ~10 wasted
            # round-trips on every search and every embed batch.
            for field_name, schema in (
                ("tenant_id", models.PayloadSchemaType.KEYWORD),
                ("meeting_id", models.PayloadSchemaType.KEYWORD),
                ("meeting_date", models.PayloadSchemaType.DATETIME),
                ("speaker_set", models.PayloadSchemaType.KEYWORD),
                ("project", models.PayloadSchemaType.KEYWORD),
                ("department", models.PayloadSchemaType.KEYWORD),
                ("chunk_type", models.PayloadSchemaType.KEYWORD),
                ("turn_start", models.PayloadSchemaType.INTEGER),
                ("turn_end", models.PayloadSchemaType.INTEGER),
                ("is_active", models.PayloadSchemaType.BOOL),
            ):
                try:
                    await client.create_payload_index(
                        collection_name=settings.qdrant_collection,
                        field_name=field_name,
                        field_schema=schema,
                    )
                except Exception as exc:
                    if "already exists" not in str(exc).lower():
                        raise
        return True
    except Exception as exc:
        logger.warning("qdrant_ensure_collection_failed", error=str(exc))
        return False


async def upsert_points(points: list[models.PointStruct]) -> bool:
    """Upsert vectors into Qdrant. Returns True on success, False if unavailable."""
    if not points:
        return True
    client = qdrant_client()
    if client is None:
        logger.info("qdrant_upsert_skipped", count=len(points), reason="not_configured")
        return False
    try:
        await ensure_collection()
        await client.upsert(
            collection_name=get_settings().qdrant_collection,
            points=points,
            wait=True,
        )
        return True
    except Exception as exc:
        logger.warning("qdrant_upsert_failed", error=str(exc), count=len(points))
        return False


async def deactivate_meeting_points(tenant_id: str, meeting_id: str) -> bool:
    """Mark all Qdrant points for a meeting as inactive. Returns True on success."""
    client = qdrant_client()
    if client is None:
        return False
    try:
        await ensure_collection()
        await client.set_payload(
            collection_name=get_settings().qdrant_collection,
            payload={"is_active": False},
            points=models.Filter(
                must=[
                    models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id)),
                    models.FieldCondition(key="meeting_id", match=models.MatchValue(value=meeting_id)),
                ]
            ),
            wait=True,
        )
        return True
    except Exception as exc:
        logger.warning("qdrant_deactivate_failed", error=str(exc))
        return False


async def hybrid_search_points(
    *,
    tenant_id: str,
    dense_vector: list[float] | None,
    sparse_vector: models.SparseVector | None,
    filters: dict[str, Any],
    limit: int,
    candidate_count: int,
    score_threshold: float,
) -> list[models.ScoredPoint]:
    """
    Hybrid dense + BM25-sparse search with Reciprocal Rank Fusion.

    Each hit is resolved to its **parent context chunk** (a matched TURN point
    is replaced by the CONTEXT chunk that contains it, per chunking_strategy.md
    §4), deduplicated, and scored with normalized RRF. Returns ScoredPoints
    whose payload/score describe the parent context unit.

    Returns empty list if Qdrant is unavailable.
    """
    client = qdrant_client()
    if client is None:
        logger.info("qdrant_search_skipped", reason="not_configured")
        return []

    settings = get_settings()
    try:
        # Ensure the hybrid collection exists before querying with named
        # vectors: a legacy dense-only collection (unnamed vector) would make
        # ``using="dense"`` error and every search silently return empty.
        await ensure_collection()
        query_filter = _build_filter(filters, tenant_id)

        # Run both indices independently (Python-side RRF keeps the fusion
        # explicit and unit-testable).
        ranked_lists: list[list[models.ScoredPoint]] = []
        if dense_vector:
            dense_result = await client.query_points(
                collection_name=settings.qdrant_collection,
                query=dense_vector,
                using="dense",
                query_filter=query_filter,
                limit=candidate_count,
                score_threshold=score_threshold,
                with_payload=True,
            )
            ranked_lists.append(dense_result.points)
        if sparse_vector is not None and (sparse_vector.indices or sparse_vector.values):
            sparse_result = await client.query_points(
                collection_name=settings.qdrant_collection,
                query=sparse_vector,
                using="sparse",
                query_filter=query_filter,
                limit=candidate_count,
                with_payload=True,
            )
            ranked_lists.append(sparse_result.points)

        hits = rrf_fuse(ranked_lists, dense_index=0)
        hits = hits[:limit]
        logger.info(
            "qdrant_hybrid_search_debug",
            tenant_id=tenant_id,
            lists=len(ranked_lists),
            dense_candidates=len(ranked_lists[0]) if ranked_lists else 0,
            unit_count=len(hits),
            score_threshold=score_threshold,
            limit=limit,
        )
        if not hits:
            logger.warning("qdrant_search_empty", reason="no_points_matched_filters_or_threshold")
        return hits
    except Exception as exc:
        logger.warning("qdrant_search_failed", error=str(exc), tenant_id=tenant_id)
        return []


def _build_filter(filters: dict[str, Any], tenant_id: str) -> models.Filter:
    """Tenant-scoped Qdrant filter with optional metadata filters."""
    must: list[models.Condition] = [
        models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id)),
        models.FieldCondition(key="is_active", match=models.MatchValue(value=True)),
    ]
    for field in ("meeting_id", "speaker", "project", "department"):
        if value := filters.get(field):
            key = "speaker_set" if field == "speaker" else field
            must.append(models.FieldCondition(key=key, match=models.MatchValue(value=value)))
    if filters.get("date_from") or filters.get("date_to"):
        must.append(
            models.FieldCondition(
                key="meeting_date",
                range=models.DatetimeRange(
                    gte=filters.get("date_from"), lte=filters.get("date_to")
                ),
            )
        )
    return models.Filter(must=must)


def rrf_fuse(
    ranked_lists: list[list[models.ScoredPoint]], *, k: int = 60, dense_index: int = 0
) -> list[models.ScoredPoint]:
    """
    Fuse ranked point lists with Reciprocal Rank Fusion, resolving each hit to
    its parent context chunk and deduplicating by ``clean_chunk_id``.

    ``dense_index`` marks which list carries dense cosine scores (so sparse
    scores are never labeled as dense). The returned score is the unit's RRF
    contribution normalized to ~[0, 1]. For a unit matched only through TURN
    points, the carried payload keeps the parent's ``clean_chunk_id``; other
    payload fields reflect the best-ranked match and are revalidated against
    MySQL by the retrieval layer.
    """
    non_empty_count = sum(1 for points in ranked_lists if points)
    if non_empty_count == 0:
        return []

    rrf_scores: dict[str, float] = {}
    dense_scores: dict[str, float] = {}
    matched_type: dict[str, str] = {}
    best_point: dict[str, models.ScoredPoint] = {}

    for list_index, points in enumerate(ranked_lists):
        if not points:
            continue
        is_dense = list_index == dense_index
        for rank, point in enumerate(points, start=1):
            payload = point.payload or {}
            if payload.get("chunk_type") == "TURN":
                unit_clean_id = str(payload.get("parent_clean_chunk_id") or "")
            else:
                unit_clean_id = str(payload.get("clean_chunk_id") or "")
            if not unit_clean_id:
                continue
            contribution = 1.0 / (k + rank)
            rrf_scores[unit_clean_id] = rrf_scores.get(unit_clean_id, 0.0) + contribution
            if payload.get("chunk_type") == "TURN":
                matched_type[unit_clean_id] = "TURN"
            else:
                matched_type.setdefault(unit_clean_id, "CONTEXT")
            if is_dense and unit_clean_id not in dense_scores:
                dense_scores[unit_clean_id] = float(point.score)
            if best_point.get(unit_clean_id) is None:
                best_point[unit_clean_id] = point

    # Normalize: max RRF with ``n`` non-empty lists is n/(k+1).
    normalization = (k + 1) / non_empty_count
    fused: list[models.ScoredPoint] = []
    for unit_clean_id, raw in sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True):
        point = best_point[unit_clean_id]
        payload = dict(point.payload or {})
        payload["clean_chunk_id"] = unit_clean_id
        payload["dense_score"] = dense_scores.get(unit_clean_id)
        payload["matched_type"] = matched_type.get(unit_clean_id, "CONTEXT")
        fused.append(
            models.ScoredPoint(
                id=point.id,
                version=point.version,
                score=min(1.0, raw * normalization),
                payload=payload,
                vector=point.vector,
            )
        )
    return fused
