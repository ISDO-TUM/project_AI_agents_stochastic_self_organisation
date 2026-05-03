"""Tool registry – maps tool names to their schemas and handlers.

Each provider has a different format for tool definitions.  The registry
exposes helpers that return the correct shape for OpenAI/Groq and Anthropic.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from api.tools.builtin.file_access import (
    TOOL_DESCRIPTION,
    TOOL_NAME,
    TOOL_PARAMETERS,
)
from api.tools.builtin.file_access import (
    handle as file_access_handle,
)

_TOOLS: dict[str, dict[str, Any]] = {
    TOOL_NAME: {
        "description": TOOL_DESCRIPTION,
        "parameters": TOOL_PARAMETERS,
        "handler": file_access_handle,
    },
}


def list_tools() -> list[dict[str, Any]]:
    """Return all registered tools in a provider-agnostic format."""
    return [
        {
            "name": name,
            "description": entry["description"],
            "parameters": entry["parameters"],
        }
        for name, entry in _TOOLS.items()
    ]


def get_handler(tool_name: str) -> Callable[[dict[str, Any]], str]:
    """Return the handler function for a registered tool."""
    entry = _TOOLS.get(tool_name)
    if entry is None:
        raise KeyError(f"Unknown tool: {tool_name}")
    return cast(Callable[[dict[str, Any]], str], entry["handler"])


def get_openai_tools(tool_names: list[str]) -> list[dict[str, Any]]:
    """Return tool definitions in OpenAI/Groq function-calling format."""
    result: list[dict[str, Any]] = []
    for name in tool_names:
        entry = _TOOLS.get(name)
        if entry is None:
            continue
        result.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": entry["description"],
                    "parameters": entry["parameters"],
                },
            }
        )
    return result


def get_anthropic_tools(tool_names: list[str]) -> list[dict[str, Any]]:
    """Return tool definitions in Anthropic tool-use format."""
    result: list[dict[str, Any]] = []
    for name in tool_names:
        entry = _TOOLS.get(name)
        if entry is None:
            continue
        result.append(
            {
                "name": name,
                "description": entry["description"],
                "input_schema": entry["parameters"],
            }
        )
    return result
