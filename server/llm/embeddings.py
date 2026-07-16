"""OpenAI embedding utilities for semantic similarity."""

from __future__ import annotations

import logging
import math
from typing import Any

from openai import AsyncOpenAI

from .credentials import resolve_api_key, resolve_base_url

logger = logging.getLogger(__name__)

DEFAULT_EMBED_MODEL = "text-embedding-3-small"
_DEFAULT_MODEL = DEFAULT_EMBED_MODEL  # backward-compatible alias


def _get_embedding_client() -> AsyncOpenAI:
    kwargs: dict[str, Any] = {"api_key": resolve_api_key("openai")}
    base_url = resolve_base_url("openai")
    if base_url:
        kwargs["base_url"] = base_url
    return AsyncOpenAI(**kwargs)


async def embed_texts(
    texts: list[str],
    model: str = _DEFAULT_MODEL,
) -> list[list[float]] | None:
    """Embed a batch of texts via OpenAI's embedding API.

    Returns a list of embedding vectors ordered to match the input list.
    Returns ``None`` on any failure so callers can fall back gracefully.

    Blank texts (LLMs occasionally pass an empty query/content) are never sent
    to the API — it rejects them with a 400, which would fail the *whole* batch.
    They come back as zero vectors, which every consumer already treats as
    "no embedding" (``cosine`` with a zero vector is 0.0). An all-blank batch
    returns ``None`` without an API round-trip.
    """
    if not texts:
        return []
    non_blank = [t for t in texts if t.strip()]
    if not non_blank:
        return None
    try:
        client = _get_embedding_client()
        response = await client.embeddings.create(
            input=non_blank,
            model=model,
            encoding_format="float",
        )
        sorted_data = sorted(response.data, key=lambda e: e.index)
        vectors = [e.embedding for e in sorted_data]
    except Exception:
        logger.warning("Embedding API call failed; falling back to text similarity", exc_info=True)
        return None
    if len(non_blank) == len(texts):
        return vectors
    zero = [0.0] * len(vectors[0])
    it = iter(vectors)
    return [next(it) if t.strip() else zero for t in texts]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]; 0.0 when either vector has no magnitude.

    Pure Python, no numpy. Used by both weighted opinion pooling and the
    phone-registry semantic search.
    """
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# Backward-compatible alias (introduced with weighted opinion pooling).
cosine_similarity = cosine
