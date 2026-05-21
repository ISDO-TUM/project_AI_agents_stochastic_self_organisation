"""Normalize tool calls from different provider response formats."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class NormalizedToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


def extract_openai_tool_calls(message: Any) -> list[NormalizedToolCall]:
    if not message.tool_calls:
        return []
    return [
        NormalizedToolCall(
            id=tc.id,
            name=tc.function.name,
            arguments=json.loads(tc.function.arguments),
        )
        for tc in message.tool_calls
    ]


def extract_anthropic_tool_calls(response: Any) -> list[NormalizedToolCall]:
    return [
        NormalizedToolCall(
            id=b.id,
            name=b.name,
            arguments=b.input if isinstance(b.input, dict) else json.loads(b.input),
        )
        for b in response.content
        if b.type == "tool_use"
    ]


def extract_gemini_tool_calls(response: dict[str, Any]) -> list[NormalizedToolCall]:
    """Extract function calls from a Gemini generateContent response.

    Gemini does not issue unique tool-call IDs, so ``id`` is set to the
    function name. This is safe because Gemini does not allow the same
    function to be called twice in a single turn.
    """
    calls = []
    for candidate in response.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            fc = part.get("functionCall")
            if not fc:
                continue
            calls.append(
                NormalizedToolCall(
                    id=fc["name"],
                    name=fc["name"],
                    arguments=fc.get("args", {}),
                )
            )
    return calls
