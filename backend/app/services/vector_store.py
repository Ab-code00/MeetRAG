from __future__ import annotations

import structlog
from typing import Any

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
    """Create the Qdrant collection and payload indexes if they don't exist.
    Returns True if successful, False if Qdrant is unavailable."""
    client = qdrant_client()
    if client is None:
        return False

    settings = get_settings()
    try:
        if not await client.collection_exists(settings.qdrant_collection):
            await client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=models.VectorParams(
                    size=settings.embedding_dimension, distance=models.Distance.COSINE
                ),
            )
        for field_name, schema in (
            ("tenant_id", models.PayloadSchemaType.KEYWORD),
            ("meeting_id", models.PayloadSchemaType.KEYWORD),
            ("meeting_date", models.PayloadSchemaType.DATETIME),
            ("speaker_set", models.PayloadSchemaType.KEYWORD),
            ("project", models.PayloadSchemaType.KEYWORD),
            ("department", models.PayloadSchemaType.KEYWORD),
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


async def search_points(
    *, tenant_id: str, vector: list[float], filters: dict[str, Any], limit: int, score_threshold: float
) -> list[models.ScoredPoint]:
    """Search Qdrant for similar vectors. Returns empty list if Qdrant is unavailable."""
    client = qdrant_client()
    if client is None:
        logger.info("qdrant_search_skipped", reason="not_configured")
        return []

    settings = get_settings()
    try:
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
        result = await client.query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
            query_filter=models.Filter(must=must),
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
        )
        logger.info(
            "qdrant_search_debug",
            tenant_id=tenant_id,
            point_count=len(result.points),
            score_threshold=score_threshold,
            limit=limit,
        )
        if result.points:
            logger.info("qdrant_search_top_scores", scores=[round(p.score, 4) for p in result.points[:5]])
        else:
            logger.warning("qdrant_search_empty", reason="no_points_matched_filters_or_threshold")
        return result.points
    except Exception as exc:
        logger.warning("qdrant_search_failed", error=str(exc), tenant_id=tenant_id)
        return []
