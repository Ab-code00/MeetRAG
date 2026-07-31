"""Test with REAL query + threshold=0.3 to see actual scores."""
import asyncio
import httpx
from qdrant_client import AsyncQdrantClient, models
from app.core.config import get_settings

s = get_settings()

async def main():
    client = AsyncQdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key, timeout=30)
    tenant = "dbf57318-60b9-40a6-bd74-51c96c444dda"
    
    # Test with different queries
    queries = [
        "who was from the pink city?",  # user's actual query
        "What was discussed in the meeting?",  # generic
        "QBR",  # might match QBR-MEET-44
        "test",  # might match Test-* meetings
    ]
    
    async with httpx.AsyncClient(timeout=30) as hc:
        headers = {
            "Authorization": f"Bearer {s.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        
        for query in queries:
            resp = await hc.post(
                f"{s.openrouter_base_url}/embeddings",
                headers=headers,
                json={"model": s.openrouter_embedding_model, "input": [query]},
            )
            vector = resp.json()["data"][0]["embedding"]
            
            # Search WITH threshold=0.3 (same as server)
            result = await client.query_points(
                collection_name=s.qdrant_collection,
                query=vector,
                query_filter=models.Filter(must=[
                    models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant)),
                    models.FieldCondition(key="is_active", match=models.MatchValue(value=True)),
                ]),
                limit=10,
                score_threshold=0.3,
                with_payload=True,
            )
            
            # Search WITHOUT threshold (to see all scores)
            result2 = await client.query_points(
                collection_name=s.qdrant_collection,
                query=vector,
                query_filter=models.Filter(must=[
                    models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant)),
                ]),
                limit=10,
                with_payload=True,
            )
            
            print(f"\nQuery: {query}")
            print(f"  With threshold=0.3: {len(result.points)} points")
            if result2.points:
                scores = [f"{p.score:.4f} ({p.payload.get('meeting_title','')})" for p in result2.points]
                print(f"  All scores: {', '.join(scores)}")
            else:
                print(f"  No points at all!")
    
    await client.close()

asyncio.run(main())
