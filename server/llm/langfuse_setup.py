"""Langfuse SDK entry point.

Auto-initializes from environment variables when the first decorated function runs:
  LANGFUSE_SECRET_KEY  - secret key from your Langfuse project settings
  LANGFUSE_PUBLIC_KEY  - public key from your Langfuse project settings
  LANGFUSE_HOST        - base URL of your instance (default: https://cloud.langfuse.com)

When keys are absent the SDK runs in no-op mode - no errors, no logging.

Rate limiting
─────────────
A single simulation fans out into dozens of concurrent agent LLM calls, each of
which emits a generation event. The SDK's stock batching (``flush_at=15`` events,
``flush_interval=0.5s``) turns that into a flood of tiny ingestion POSTs that trip
Langfuse Cloud's per-minute rate limiter (HTTP 429) on hosted deployments such as
Railway. We configure the client to batch far more aggressively — fewer, larger
requests — and to retry transient 429s with exponential backoff. Every value stays
overridable via the corresponding ``LANGFUSE_*`` environment variable so the
batching can be retuned on the deployment without a code change.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from langfuse.decorators import langfuse_context, observe

logger = logging.getLogger(__name__)

_metadata: ContextVar[dict[str, Any] | None] = ContextVar("langfuse_metadata", default=None)

# Batching defaults tuned for bursty, highly-concurrent simulation traffic. These
# raise the SDK's stock values (flush_at=15, flush_interval=0.5, max_retries=3) so
# events accumulate into a handful of large batches instead of many small ones.
# The matching LANGFUSE_* env var overrides each one on the deployment.
_DEFAULT_FLUSH_AT = 100  # events per batch before an eager flush (SDK default: 15)
_DEFAULT_FLUSH_INTERVAL = 5.0  # seconds a partial batch waits to fill (SDK default: 0.5)
_DEFAULT_MAX_RETRIES = 5  # retries with exponential backoff on 429/network errors (SDK default: 3)
_DEFAULT_TIMEOUT = 30  # seconds per ingestion request (SDK default: 20)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r — expected an integer", name, raw)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r — expected a number", name, raw)
        return default


def configure_langfuse() -> None:
    """Tune the Langfuse client for high-throughput, rate-limit-prone deployments.

    Idempotent and safe to call at import time. When no credentials are present
    the SDK stays in no-op mode, so this only affects batching when tracing is
    actually enabled. Threads is deliberately left at the SDK default (1): adding
    consumer threads would issue *more* concurrent ingestion requests, which works
    against the rate limiter rather than for it.
    """
    langfuse_context.configure(
        flush_at=_env_int("LANGFUSE_FLUSH_AT", _DEFAULT_FLUSH_AT),
        flush_interval=_env_float("LANGFUSE_FLUSH_INTERVAL", _DEFAULT_FLUSH_INTERVAL),
        max_retries=_env_int("LANGFUSE_MAX_RETRIES", _DEFAULT_MAX_RETRIES),
        timeout=_env_int("LANGFUSE_TIMEOUT", _DEFAULT_TIMEOUT),
    )


# Apply the tuned batching as soon as this module is imported — well before the
# first @observe-decorated call instantiates the background consumer.
configure_langfuse()


@contextmanager
def langfuse_metadata(metadata: dict[str, Any]) -> Iterator[None]:
    """Attach trial/agent metadata to observed LLM calls in this context."""
    current = _metadata.get() or {}
    token = _metadata.set({**current, **metadata})
    try:
        yield
    finally:
        _metadata.reset(token)


def update_current_generation(
    *,
    model: str | None,
    input: Any | None,
    usage: dict[str, int | None] | None,
) -> None:
    """Update the current Langfuse trace/observation with app metadata."""
    metadata = _metadata.get() or {}
    trial_id = metadata.get("trial_id")
    agent_id = metadata.get("agent_id")
    tags = [
        tag
        for tag in (
            f"trial:{trial_id}" if trial_id else None,
            f"agent:{agent_id}" if agent_id else None,
        )
        if tag
    ]
    if metadata:
        langfuse_context.update_current_trace(
            name="agent-llm-call",
            session_id=str(trial_id) if trial_id else None,
            metadata=metadata,
            tags=tags or None,
        )
    langfuse_context.update_current_observation(
        model=model,
        input=input,
        usage=usage,
        metadata=metadata or None,
        session_id=str(trial_id) if trial_id else None,
        tags=tags or None,
    )


__all__ = [
    "configure_langfuse",
    "langfuse_context",
    "langfuse_metadata",
    "observe",
    "update_current_generation",
]
