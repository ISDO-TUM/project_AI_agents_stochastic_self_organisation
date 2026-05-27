"""OpenAI embedding utilities for semantic similarity."""

from __future__ import annotations

import logging
import math
from typing import Any

from openai import AsyncOpenAI

from .credentials import resolve_api_key, resolve_base_url

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "text-embedding-3-small"


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
    """
    if not texts:
        return []
    try:
        client = _get_embedding_client()
        response = await client.embeddings.create(
            input=texts,
            model=model,
            encoding_format="float",
        )
        sorted_data = sorted(response.data, key=lambda e: e.index)
        return [e.embedding for e in sorted_data]
    except Exception:
        logger.warning("Embedding API call failed; falling back to text similarity", exc_info=True)
        return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors. Pure Python, no numpy."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
