"""Diagnose why Qdrant search returns empty results.

Replicates the exact flow used by the search endpoint.
"""
import asyncio
import httpx
from app.core.config import get_settings
from qdrant_client import AsyncQdrantClient, models

s = get_settings()
print("=== SETTINGS ===")
print(f"Qdrant URL: {s.qdrant_url}")
print(f"Qdrant collection: {s.qdrant_collection}")
print(f"Embedding model: {s.openrouter_embedding_model}")
print(f"Embed dim: {s.embedding_dimension}")
print(f"Score threshold: {s.retrieval_score_threshold}")
print(f"Top K: {s.retrieval_top_k}")


async def diag():
    client = AsyncQdrantClient(
        url=s.qdrant_url,
        api_key=s.qdrant_api_key or None,
        timeout=30,
    )

    # Step 1: Get collection info
    print("\n=== COLLECTION INFO ===")
    try:
        info = await client.get_collection(s.qdrant_collection)
        print(f"Points count: {info.points_count}")
        print(f"Vector dim: {info.config.params.vectors.size}")
        print(f"Distance: {info.config.params.vectors.distance}")
    except Exception as e:
        print(f"Failed to get collection: {e}")
        return

    # Step 2: Scroll ALL points to see what tenant_ids exist
    print("\n=== ALL POINTS IN COLLECTION ===")
    all_points, _ = await client.scroll(
        collection_name=s.qdrant_collection,
        limit=100,
        with_payload=True,
        with_vectors=False,
    )
    print(f"Total points in collection: {len(all_points)}")

    if not all_points:
        print("NO POINTS FOUND! The collection is empty.")
        await client.close()
        return

    # Show sample point
    p = all_points[0]
    print(f"\nSample point ID: {p.id}")
    print(f"Sample payload keys: {list(p.payload.keys())}")
    print(f"tenant_id: {p.payload.get('tenant_id', 'MISSING')}")
    print(f"is_active: {p.payload.get('is_active', 'MISSING')} (type: {type(p.payload.get('is_active')).__name__})")
    print(f"embedding_model: {p.payload.get('embedding_model', 'MISSING')}")

    # Show unique tenant_ids
    tenant_ids = set(p.payload.get("tenant_id", "") for p in all_points)
    print(f"\nUnique tenant_ids in collection: {tenant_ids}")

    # Step 3: Test search with NO score threshold (should always return something)
    for tid in sorted(tenant_ids):
        if not tid:
            continue
        print(f"\n=== SEARCH TEST for tenant: {tid} ===")
        must = [
            models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tid)),
            models.FieldCondition(key="is_active", match=models.MatchValue(value=True)),
        ]

        # Search with zero vector (no match, but should return lowest scored items)
        dummy = [0.0] * s.embedding_dimension
        result = await client.query_points(
            collection_name=s.qdrant_collection,
            query=dummy,
            query_filter=models.Filter(must=must),
            limit=5,
            score_threshold=0.0,
            with_payload=True,
        )
        print(f"  With threshold=0.0: {len(result.points)} points")
        if result.points:
            print(f"  Top score: {result.points[0].score}")
        else:
            print("  EMPTY! Check tenant_id or is_active filtering.")

        # Now search with NO threshold
        result2 = await client.query_points(
            collection_name=s.qdrant_collection,
            query=dummy,
            query_filter=models.Filter(must=must),
            limit=5,
            with_payload=True,
        )
        print(f"  Without threshold: {len(result2.points)} points")

    # Step 4: Test embedding a real query and searching
    print("\n=== REAL QUERY TEST ===")
    test_query = "What was discussed in the meeting?"
    print(f"Query: {test_query}")
    print(f"Using model: {s.openrouter_embedding_model}")

    async with httpx.AsyncClient(timeout=30) as hc:
        headers = {
            "Authorization": f"Bearer {s.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        resp = await hc.post(
            f"{s.openrouter_base_url}/embeddings",
            headers=headers,
            json={"model": s.openrouter_embedding_model, "input": [test_query]},
        )
        print(f"OpenRouter status: {resp.status_code}")
        if resp.is_error:
            print(f"OpenRouter error: {resp.text[:500]}")
        else:
            data = resp.json()
            vector = data["data"][0]["embedding"]
            print(f"Vector dimension: {len(vector)}")
            print(f"Vector first 5 values: {vector[:5]}")

            # Search with real vector, no threshold
            for tid in sorted(tenant_ids):
                if not tid:
                    continue
                must = [
                    models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tid)),
                    models.FieldCondition(key="is_active", match=models.MatchValue(value=True)),
                ]
                result = await client.query_points(
                    collection_name=s.qdrant_collection,
                    query=vector,
                    query_filter=models.Filter(must=must),
                    limit=5,
                    with_payload=True,
                )
                print(f"  Tenant {tid}: {len(result.points)} points")
                if result.points:
                    for pt in result.points[:3]:
                        print(f"    Score: {pt.score}, meeting: {pt.payload.get('meeting_title', '?')}")

    await client.close()


asyncio.run(diag())
