"""Unit tests for server.market_hive.tracing (flag-gated Langfuse tracing)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from server.market_hive.tracing import LangfuseTracer, NoopTracer, get_tracer


def test_unconfigured_env_returns_noop_tracer_without_constructing_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    with patch("langfuse.Langfuse", side_effect=AssertionError("must not construct")) as ctor:
        tracer = get_tracer()

    assert isinstance(tracer, NoopTracer)
    ctor.assert_not_called()


def test_noop_tracer_spans_are_true_no_ops() -> None:
    tracer = NoopTracer()
    with tracer.run_span("r1"):
        with tracer.phase_span("auction"):
            pass
    tracer.turn("a1", 2, 100)  # must not raise


def test_configured_env_constructs_langfuse_client_and_records_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")

    mock_trace = MagicMock()
    mock_span = MagicMock()
    mock_trace.span.return_value = mock_span
    mock_client = MagicMock()
    mock_client.trace.return_value = mock_trace

    with patch("langfuse.Langfuse", return_value=mock_client) as ctor:
        tracer = get_tracer()
        assert isinstance(tracer, LangfuseTracer)
        with tracer.run_span("r1"):
            with tracer.phase_span("auction"):
                pass
            with tracer.phase_span("round_2"):
                pass
        tracer.turn("a1", 2, 100)

    ctor.assert_called_once()
    mock_client.trace.assert_called_once_with(name="swarm_run", session_id="r1")
    assert mock_trace.span.call_count == 3  # auction, round_2, turn
    # mock_trace.span(...) returns the same mock every call, so all three
    # spans' .end() calls land on it: the two phase-span exits plus turn's own.
    assert mock_span.end.call_count == 3
