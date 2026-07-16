"""AnthropicProvider/GeminiProvider must match OpenAI/Groq's timeout +
observability behavior: the whole tool-call loop wrapped in
``asyncio.wait_for(timeout=self.timeout_seconds)``, with an elapsed-time
success log and a clear ``TimeoutError`` on expiry (see base_provider.py's
``call()``). Previously these two providers fully overrode ``call()`` with no
such wrapper — only the 30s heartbeat watchdog existed, so a hang was caught
only by the orchestrator's much coarser outer timeout, never the provider's
own budget.

These tests cover only the wrapper itself:
  - the non-timeout path returns the same value the unwrapped loop would
    (the wrap must be transparent for the common case)
  - a call whose ``_send`` never returns within ``timeout_seconds`` raises
    ``TimeoutError`` with the same message shape ``base_provider.py`` uses
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from server.llm.anthropic_provider import AnthropicProvider
from server.llm.gemini_provider import GeminiProvider


class _AnthropicBlock:
    """Minimal stand-in for an Anthropic content block (text or tool_use)."""

    def __init__(self, type_: str, **kwargs: Any) -> None:
        self.type = type_
        for key, value in kwargs.items():
            setattr(self, key, value)


# --- AnthropicProvider ------------------------------------------------------


async def test_anthropic_call_non_timeout_path_unchanged() -> None:
    """A normal (non-timeout) call returns the same extracted text the
    unwrapped loop always returned — the wrapper must be transparent."""
    provider = AnthropicProvider()

    async def fake_send(kwargs: dict[str, Any]) -> Any:
        return SimpleNamespace(content=[_AnthropicBlock("text", text="hello from anthropic")])

    provider._send = fake_send

    result = await provider.call("prompt", "claude-haiku-4-5-20251001")

    assert result == "hello from anthropic"


async def test_anthropic_call_times_out_when_send_hangs() -> None:
    """A ``_send`` that never returns within ``timeout_seconds`` must raise
    ``TimeoutError`` with the same message pattern as base_provider.py,
    instead of hanging until the orchestrator's much coarser outer timeout."""
    provider = AnthropicProvider()
    provider.timeout_seconds = 0.05

    async def hanging_send(kwargs: dict[str, Any]) -> Any:
        await asyncio.sleep(10)
        return SimpleNamespace(content=[])

    provider._send = hanging_send

    with pytest.raises(TimeoutError, match=r"exceeded the maximum allowed time \(0.05s\)"):
        await provider.call("prompt", "claude-haiku-4-5-20251001")


# --- GeminiProvider -----------------------------------------------------


async def test_gemini_call_non_timeout_path_unchanged() -> None:
    """A normal (non-timeout) call returns the same extracted text the
    unwrapped loop always returned — the wrapper must be transparent."""
    provider = GeminiProvider()

    async def fake_send(kwargs: dict[str, Any]) -> dict[str, Any]:
        return {"candidates": [{"content": {"parts": [{"text": "hello from gemini"}]}}]}

    provider._send = fake_send

    result = await provider.call("prompt", "gemini-2.0-flash")

    assert result == "hello from gemini"


async def test_gemini_call_times_out_when_send_hangs() -> None:
    """A ``_send`` that never returns within ``timeout_seconds`` must raise
    ``TimeoutError`` with the same message pattern as base_provider.py,
    instead of hanging until the orchestrator's much coarser outer timeout."""
    provider = GeminiProvider()
    provider.timeout_seconds = 0.05

    async def hanging_send(kwargs: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(10)
        return {"candidates": []}

    provider._send = hanging_send

    with pytest.raises(TimeoutError, match=r"exceeded the maximum allowed time \(0.05s\)"):
        await provider.call("prompt", "gemini-2.0-flash")
