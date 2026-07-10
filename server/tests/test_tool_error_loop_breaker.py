"""BaseLLMProvider ends a turn early once a model stops recovering from
rejected tool calls, instead of silently burning the full iteration budget.

Found via a live run: an agent hit iterations=20/156s on a single turn after
getting a tool call rejected repeatedly and just retrying near-verbatim
instead of changing course — invisible in logs because tool calls only
logged at DEBUG (see server/llm/base_provider.py).
"""

from __future__ import annotations

from typing import Any

import pytest

from server.llm.base_provider import _MAX_CONSECUTIVE_ERROR_ITERATIONS, BaseLLMProvider
from server.llm.normalizer import NormalizedToolCall


class _FakeProvider(BaseLLMProvider):  # type: ignore[misc]
    """Minimal provider whose ``_send`` replays a scripted list of responses,
    each either a tool call or a final text — enough to drive ``_call_inner``
    without a real API."""

    def __init__(
        self, scripted_tool_calls: list[str | None], *, also_call_succeeding_tool: bool = False
    ) -> None:
        # None means "no more tool calls, return final text" for that turn.
        self._script = list(scripted_tool_calls)
        self._sent = 0
        self._also_call_succeeding_tool = also_call_succeeding_tool

    def _get_client(self) -> Any:
        raise NotImplementedError

    def _build_messages(self, prompt: str, system_prompt: str | None) -> list[dict[str, Any]]:
        return [{"role": "user", "content": prompt}]

    def _build_kwargs(
        self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        return {"model": model, "messages": messages}

    async def _send(self, kwargs: dict[str, Any]) -> Any:
        step = self._script[self._sent] if self._sent < len(self._script) else None
        self._sent += 1
        return step

    def _extract_tool_calls(self, response: Any) -> list[NormalizedToolCall]:
        if response is None:
            return []
        calls = [NormalizedToolCall(id="tc1", name="post_to_blackboard", arguments={})]
        if self._also_call_succeeding_tool:
            calls.append(NormalizedToolCall(id="tc2", name="read_blackboard", arguments={}))
        return calls

    def _extract_text(self, response: Any) -> str:
        return "final text" if response is None else "(mid-turn, no text yet)"

    def _append_assistant_and_tool_results(
        self,
        messages: list[dict[str, Any]],
        response: Any,
        tool_results: list[tuple[NormalizedToolCall, str]],
    ) -> None:
        messages.append({"role": "assistant", "content": str(response)})


async def _fake_tool_handler_always_error(name: str, args: dict[str, Any]) -> str:
    return '{"error": "you already posted 2 replies this round (cap: 2)."}'


async def _fake_tool_handler_recovers(name: str, args: dict[str, Any]) -> str:
    return '{"entry_id": "abc123"}'


async def _fake_tool_handler_one_tool_stuck(name: str, args: dict[str, Any]) -> str:
    """read_blackboard always succeeds; post_to_blackboard always errors —
    mirrors the live-run case where a benign call rides alongside a
    persistently-rejected one every iteration."""
    if name == "read_blackboard":
        return "some board digest"
    return '{"error": "you cannot refines your own entry."}'


@pytest.mark.asyncio
async def test_stops_early_after_consecutive_all_error_iterations() -> None:
    """A model that just keeps retrying a rejected tool call ends the turn at
    _MAX_CONSECUTIVE_ERROR_ITERATIONS instead of exhausting max_iterations."""
    provider = _FakeProvider(scripted_tool_calls=["call"] * 20)
    provider.max_iterations = 20

    _text, iterations = await provider._call_inner(
        "prompt", "test-model", tool_handler=_fake_tool_handler_always_error
    )

    assert iterations == _MAX_CONSECUTIVE_ERROR_ITERATIONS
    assert iterations < 20


@pytest.mark.asyncio
async def test_does_not_stop_early_when_calls_succeed() -> None:
    """A model whose tool calls succeed runs to completion normally — the
    breaker must never fire on a healthy turn."""
    provider = _FakeProvider(scripted_tool_calls=["call", "call", "call", None])
    provider.max_iterations = 20

    text, iterations = await provider._call_inner(
        "prompt", "test-model", tool_handler=_fake_tool_handler_recovers
    )

    assert text == "final text"
    assert iterations == 4


@pytest.mark.asyncio
async def test_a_single_recovery_resets_the_error_streak() -> None:
    """Two errors, then one success, then two more errors must NOT trip the
    breaker (which requires *consecutive* all-error iterations) — a model
    that's genuinely adapting shouldn't be cut off."""
    calls = {"n": 0}

    async def handler(name: str, args: dict[str, Any]) -> str:
        calls["n"] += 1
        if calls["n"] == 3:
            return '{"entry_id": "recovered"}'
        return '{"error": "rejected"}'

    provider = _FakeProvider(scripted_tool_calls=["call"] * 4 + [None])
    provider.max_iterations = 20

    text, iterations = await provider._call_inner("prompt", "test-model", tool_handler=handler)

    assert text == "final text"
    assert iterations == 5


@pytest.mark.asyncio
async def test_call_agent_default_max_iterations_unchanged() -> None:
    """No ``max_iterations`` override passed to ``_call_inner`` must behave
    exactly as before this task: the loop bound stays ``self.max_iterations``
    (20 by default). A provider that never errors and never stops calling
    tools on its own runs to exactly that many iterations."""
    provider = _FakeProvider(scripted_tool_calls=["call"] * 25)
    provider.max_iterations = 20

    _text, iterations = await provider._call_inner(
        "prompt", "test-model", tool_handler=_fake_tool_handler_recovers
    )

    assert iterations == 20
    assert iterations == provider.max_iterations


@pytest.mark.asyncio
async def test_call_agent_max_iterations_override_respected() -> None:
    """A per-call ``max_iterations`` override caps the loop below the
    provider's own default, even for a handler that would otherwise keep the
    turn going indefinitely (never errors, never returns a final tool-call-free
    response within the class default's budget)."""
    provider = _FakeProvider(scripted_tool_calls=["call"] * 25)
    provider.max_iterations = 20

    _text, iterations = await provider._call_inner(
        "prompt", "test-model", tool_handler=_fake_tool_handler_recovers, max_iterations=2
    )

    assert iterations == 2
    assert iterations < provider.max_iterations


@pytest.mark.asyncio
async def test_stops_early_when_one_tool_keeps_failing_even_while_others_succeed() -> None:
    """The exact gap a live run exposed: an iteration-level "all calls this
    iteration failed" check never trips if a harmless call (read_blackboard)
    rides alongside the one that's actually stuck (post_to_blackboard) every
    time — a real turn ran the full 20 iterations this way. Tracking each
    tool's own streak, reset only by THAT tool succeeding, must catch it."""
    provider = _FakeProvider(scripted_tool_calls=["call"] * 20, also_call_succeeding_tool=True)
    provider.max_iterations = 20

    _text, iterations = await provider._call_inner(
        "prompt", "test-model", tool_handler=_fake_tool_handler_one_tool_stuck
    )

    assert iterations == _MAX_CONSECUTIVE_ERROR_ITERATIONS
    assert iterations < 20
