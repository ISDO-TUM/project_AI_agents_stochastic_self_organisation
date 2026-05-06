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
