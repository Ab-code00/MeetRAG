"""Client-side sparse (BM25-style) vector generation for hybrid retrieval.

Qdrant applies the IDF weighting server-side via
``SparseVectorParams(modifier=Modifier.IDF)``; this module only tokenizes text
and produces term-frequency sparse vectors. Token ids are derived from a
deterministic hash so the same term maps to the same id at index time and at
query time (Qdrant computes IDF from the corpus it has indexed). Collisions
are rare and RRF fusion is tolerant of them.

Keeps useful tokens intact: identifiers like ``JIRA-421``, dotted versions
like ``v1.2.3``, and hashtags.
"""

import re
import zlib
from collections import Counter

from qdrant_client.models import SparseVector

_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9._#-]*")

_MAX_TOKEN_LENGTH = 40


def tokenize(text: str) -> list[str]:
    """Lowercase, punctuation-safe tokenization for BM25."""
    tokens = _TOKEN_PATTERN.findall(text.lower())
    return [token for token in tokens if len(token) <= _MAX_TOKEN_LENGTH]


def _token_id(token: str) -> int:
    return zlib.crc32(token.encode("utf-8")) & 0xFFFFFFFF


def sparse_vector(text: str) -> SparseVector:
    """
    Build a term-frequency sparse vector for ``text``.

    Empty text produces an empty sparse vector (a valid no-op for Qdrant).
    """
    counts: Counter[str] = Counter(tokenize(text))
    if not counts:
        return SparseVector(indices=[], values=[])
    by_index: dict[int, float] = {}
    for token, frequency in counts.items():
        index = _token_id(token)
        by_index[index] = by_index.get(index, 0.0) + frequency
    indices = sorted(by_index)
    return SparseVector(indices=indices, values=[by_index[index] for index in indices])
