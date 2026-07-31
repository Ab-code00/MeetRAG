"""Diagnose Qdrant search - what's in the collection vs what search finds."""
import asyncio
from qdrant_client import AsyncQdrantClient, models
from app.core.config import get_settings

s = get_settings()

async def main():
    client = AsyncQdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key, timeout=30)

    # 1. Get ALL points with metadata
    all_points, _ = await client.scroll(
        collection_name=s.qdrant_collection, limit=100,
        with_payload=True, with_vectors=False,
    )
    print(f"Total points in collection: {len(all_points)}")
    
    active = 0
    meeting_ids = set()
    for p in all_points:
        if p.payload.get("is_active") == True:
            active += 1
        meeting_ids.add(p.payload.get("meeting_id", ""))
    print(f"Active points (is_active=True): {active}")
    print(f"Meeting IDs in collection: {meeting_ids}")
    print(f"Tenant IDs: {set(p.payload.get('tenant_id','') for p in all_points)}")

    # 2. Test search WITHOUT score_threshold
    print("\n=== SEARCH WITH NO THRESHOLD ===")
    tenant = "dbf57318-60b9-40a6-bd74-51c96c444dda"
    dummy = [0.0] * s.embedding_dimension
    result = await client.query_points(
        collection_name=s.qdrant_collection,
        query=dummy,
        query_filter=models.Filter(must=[
            models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant)),
        ]),
        limit=10,
        with_payload=True,
    )
    print(f"Without is_active filter: {len(result.points)} points")
    for p in result.points[:5]:
        print(f"  score={p.score:.4f} meeting={p.payload.get('meeting_title','')} active={p.payload.get('is_active')}")

    # 3. With is_active=True filter
    result2 = await client.query_points(
        collection_name=s.qdrant_collection,
        query=dummy,
        query_filter=models.Filter(must=[
            models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant)),
            models.FieldCondition(key="is_active", match=models.MatchValue(value=True)),
        ]),
        limit=10,
        with_payload=True,
    )
    print(f"\nWith is_active=True filter: {len(result2.points)} points")
    for p in result2.points[:5]:
        print(f"  score={p.score:.4f} meeting={p.payload.get('meeting_title','')} active={p.payload.get('is_active')}")

    # 4. With is_active=True AND score_threshold=0.3
    result3 = await client.query_points(
        collection_name=s.qdrant_collection,
        query=dummy,
        query_filter=models.Filter(must=[
            models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant)),
            models.FieldCondition(key="is_active", match=models.MatchValue(value=True)),
        ]),
        limit=10,
        score_threshold=0.3,
        with_payload=True,
    )
    print(f"\nWith is_active=True + threshold=0.3: {len(result3.points)} points")
    for p in result3.points:
        print(f"  score={p.score:.4f} meeting={p.payload.get('meeting_title','')}")

    await client.close()

asyncio.run(main())
