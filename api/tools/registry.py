"""Tool registry - maps tool names to their schemas and handlers.

Each provider has a different format for tool definitions.  The registry
exposes helpers that return the correct shape for OpenAI/Groq and Anthropic.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from api.schemas import ToolCall
from api.tools.builtin.files import (
    TOOL_DESCRIPTION,
    TOOL_NAME,
    TOOL_PARAMETERS,
)
from api.tools.builtin.files import (
    context_hint as files_context_hint,
)
from api.tools.builtin.files import (
    handle as files_handle,
)
from api.tools.builtin.files import (
    load_context as files_load_context,
)

_TOOLS: dict[str, dict[str, Any]] = {
    TOOL_NAME: {
        "description": TOOL_DESCRIPTION,
        "parameters": TOOL_PARAMETERS,
        "handler": files_handle,
        "context_hint": files_context_hint,
        "context_loader": files_load_context,
    },
}


async def build_tool_context(tool_names: list[str], raw_context: dict[str, Any]) -> dict[str, Any]:
    """Call each tool's context_loader and merge the results into one context dict."""
    context: dict[str, Any] = {}
    for name in tool_names:
        entry = _TOOLS.get(name)
        if entry is None:
            continue
        loader = entry.get("context_loader")
        if loader is not None:
            context.update(await loader(raw_context))
    return context


def build_tools_system_prompt(tool_names: list[str], context: dict[str, Any]) -> str:
    """Build a system-prompt block describing available tools and their runtime context.

    Each tool may declare a *context_hint* callable that contributes a snippet
    (e.g. listing attached files).  Returns an empty string if nothing to inject.
    """
    lines: list[str] = []
    tool_lines: list[str] = []
    hint_lines: list[str] = []

    for name in tool_names:
        entry = _TOOLS.get(name)
        if entry is None:
            continue
        tool_lines.append(f"- {name}: {entry['description']}")
        hint_fn = entry.get("context_hint")
        if hint_fn is not None:
            hint = hint_fn(context)
            if hint:
                hint_lines.append(hint)

    if not tool_lines:
        return ""

    lines.append("You have access to the following tools:")
    lines.extend(tool_lines)
    if hint_lines:
        lines.append("")
        lines.extend(hint_lines)

    return "\n".join(lines)


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


def build_tool_dispatcher(
    context: dict[str, Any] | None = None,
    used_tools: list[ToolCall] | None = None,
) -> Callable[[str, dict[str, Any]], Awaitable[str]]:
    """Return an async tool dispatcher that forwards context to every handler.

    If *used_tools* is provided, a ToolCall record is appended to it on each call.
    """

    async def dispatch(tool_name: str, arguments: dict[str, Any]) -> str:
        entry = _TOOLS.get(tool_name)
        if entry is None:
            return f"Unknown tool: {tool_name}"
        output = str(await entry["handler"](arguments, context))
        if used_tools is not None:
            used_tools.append(ToolCall(name=tool_name, input=arguments, output=output))
        return output

    return dispatch


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
