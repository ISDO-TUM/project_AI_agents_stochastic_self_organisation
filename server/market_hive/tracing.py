"""Optional Langfuse tracing for swarm runs — flag-gated, zero-overhead by default.

This is a separate, coarser-grained seam from ``server.llm.langfuse_setup``
(which already auto-instruments individual LLM calls via the ``@observe``
decorator inside each provider module): ``Tracer`` brackets the *run* and its
*phases* — one trace per run, one child span per phase — so a run's shape is
visible in Langfuse even without drilling into every LLM generation.

``get_tracer()`` returns ``NoopTracer`` unless both ``LANGFUSE_PUBLIC_KEY`` and
``LANGFUSE_SECRET_KEY`` are set — no ``langfuse.Langfuse`` client is ever
constructed on the unconfigured path, so there is no overhead (network,
memory, or otherwise) when tracing isn't configured.
"""

from __future__ import annotations

import os
from contextlib import AbstractContextManager
from typing import Any, Protocol


class Tracer(Protocol):
    def run_span(self, run_id: str) -> AbstractContextManager[None]:
        pass

    def phase_span(self, name: str) -> AbstractContextManager[None]:
        pass

    def turn(self, agent_id: str, round: int, tokens: int) -> None:
        pass


class _NoopSpan(AbstractContextManager[None]):
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc_info: object) -> None:
        return None


class NoopTracer:
    """Zero-overhead tracer used when Langfuse isn't configured."""

    def run_span(self, run_id: str) -> AbstractContextManager[None]:
        return _NoopSpan()

    def phase_span(self, name: str) -> AbstractContextManager[None]:
        return _NoopSpan()

    def turn(self, agent_id: str, round: int, tokens: int) -> None:
        return None


class _LangfuseSpan(AbstractContextManager[None]):
    def __init__(self, span: Any) -> None:
        self._span = span

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc_info: object) -> None:
        if self._span is not None:
            self._span.end()


class LangfuseTracer:
    """Wraps a ``langfuse.Langfuse`` client. Only constructed when configured
    (see ``get_tracer``) — the import is lazy so an unconfigured process never
    pays for it."""

    def __init__(self) -> None:
        from langfuse import Langfuse

        self._client = Langfuse()
        self._trace: Any = None

    def run_span(self, run_id: str) -> AbstractContextManager[None]:
        self._trace = self._client.trace(name="swarm_run", session_id=run_id)
        return _LangfuseSpan(None)  # the trace itself has no explicit .end()

    def phase_span(self, name: str) -> AbstractContextManager[None]:
        span = self._trace.span(name=name) if self._trace is not None else None
        return _LangfuseSpan(span)

    def turn(self, agent_id: str, round: int, tokens: int) -> None:
        if self._trace is None:
            return
        self._trace.span(name=f"turn:{agent_id}", metadata={"round": round, "tokens": tokens}).end()


def get_tracer() -> Tracer:
    """``NoopTracer`` unless both Langfuse keys are configured."""
    if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
        return LangfuseTracer()
    return NoopTracer()
