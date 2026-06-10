"""Langfuse SDK entry point.

Auto-initializes from environment variables when the first decorated function runs:
  LANGFUSE_SECRET_KEY  - secret key from your Langfuse project settings
  LANGFUSE_PUBLIC_KEY  - public key from your Langfuse project settings
  LANGFUSE_HOST        - base URL of your instance (default: https://cloud.langfuse.com)

When keys are absent the SDK runs in no-op mode - no errors, no logging.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from langfuse.decorators import langfuse_context, observe

_metadata: ContextVar[dict[str, Any] | None] = ContextVar("langfuse_metadata", default=None)


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


__all__ = ["langfuse_context", "langfuse_metadata", "observe", "update_current_generation"]
