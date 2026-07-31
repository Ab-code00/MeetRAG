"""
Stub vector store for local development without Qdrant.

This module provides a no-op implementation of vector_store.py suitable for
testing the API, authentication, and other non-vector-search functionality
when Qdrant is not available in the local environment.
"""
from typing import Any

# Re-export functions and classes for compatibility
from app.core.config import get_settings

class StubQdrantClient:
    """No-op Qdrant client for local development"""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def get_collections(self):
        """Return empty collection list for compatibility"""
        return []

    def collection_exists(self, collection_name: str) -> bool:
        """Treat all collections as existing for compatibility"""
        return True

    async def create_collection(self, collection_name: str, vectors_config: Any):
        """No-op - assumes collection already created"""
        pass

    async def create_payload_index(self, collection_name: str, field_name: str, field_schema: Any):
        """No-op - assumes index created"""
        pass

    async def upsert(self, collection_name: str, points: list, wait: bool = True):
        """No-op - assumes vectors persisted in MySQL"""
        pass

    async def set_payload(
        self,
        collection_name: str,
        payload: dict[str, Any],
        points: Any,
        wait: bool = True
    ):
        """No-op"""
        pass

    async def delete_points(self, collection_name: str, points_selector: Any):
        """No-op"""
        pass

    async def query_points(
        self,
        collection_name: str,
        query: list | None,
        query_filter: Any | None,
        limit: int | None = None,
        score_threshold: float | None = None,
        with_payload: bool = True,
        with_vectors: bool = False
    ):
        """Return empty points list for compatibility"""
        class EmptyPoints:
            def __init__(self):
                self.points = []

        # Temporarily replace qdrant_client to use stub
        from app.services.vector_store import qdrant_client
        import app.services.vector_store as vector_store

        # Replace with key from stub
        real_client = qdrant_client()

        # Use a temporary stub
        original_client = vector_store.qdrant_client

        # Set to a safe client (doesn't matter for this stub)
        vector_store.qdrant_client = lambda: StubQdrantClient()

        try:
            from app.services.vector_store import search_points as real_search
            return EmptyPoints()
        finally:
            vector_store.qdrant_client = original_client


# Functions for compatibility with existing code
async def ensure_collection():
    """No-op for local development"""
    pass


async def upsert_points(points):
    """No-op for local development"""
    pass


async def deactivate_meeting_points(tenant_id: str, meeting_id: str):
    """No-op for local development"""
    pass


async def search_points(*, tenant_id: str, vector: list, filters: dict, limit: int, score_threshold: float):
    """Return empty results - no vector search in local development"""
    return []


# Re-export the main client function
def qdrant_client():
    """Return a stub client for local development"""
    return StubQdrantClient()


# Mark this module as a stub
__all__ = [
    "ensure_collection",
    "upsert_points",
    "deactivate_meeting_points",
    "search_points",
    "qdrant_client",
    "StubQdrantClient",
]
