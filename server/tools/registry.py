"""Tool registry — register Tool instances, build provider payloads, dispatch calls."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from server.schemas import ToolCall
from server.tools.base import Tool
from server.tools.builtin.files import FilesTool
from server.tools.builtin.registry import RegistryTool

# ── registry ───────────────────────────────────────────────────────

_TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    _TOOLS[tool.name] = tool


def get_tool(name: str) -> Tool | None:
    return _TOOLS.get(name)


register(FilesTool())
register(RegistryTool())

# ── provider format builders ───────────────────────────────────────


def get_tools_for_provider(provider: str, tool_names: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for name in tool_names:
        tool = _TOOLS.get(name)
        if tool is None:
            continue
        if provider in ("openai", "groq", "ollama"):
            result.append(tool.to_openai())
        elif provider == "anthropic":
            result.append(tool.to_anthropic())
        elif provider == "gemini":
            result.append(tool.to_gemini())
    return result


# ── listing ────────────────────────────────────────────────────────


def list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.schema(),
        }
        for tool in _TOOLS.values()
    ]


# ── dispatcher with Pydantic validation ────────────────────────────


def create_tool_handler(
    context: dict[str, Any] | None = None,
    used_tools: list[ToolCall] | None = None,
) -> Callable[[str, dict[str, Any]], Awaitable[str]]:

    async def tool_handler(tool_name: str, arguments: dict[str, Any]) -> str:
        tool = _TOOLS.get(tool_name)
        if tool is None:
            return f"Unknown tool: {tool_name}"
        output: str = await tool.safe_execute(arguments, context)
        if used_tools is not None:
            used_tools.append(ToolCall(name=tool_name, input=arguments, output=output))
        return output

    return tool_handler
