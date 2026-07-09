"""Tool registry — register Tool instances, build provider payloads, dispatch calls."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from server.tools.base import Tool
from server.tools.builtin.files import FilesTool
from server.tools.builtin.registry import RegistryTool
from server.tools.builtin.rpt_chat import RPTChatTool
from server.tools.builtin.rpt_predict import RPTPredictTool
from server.tools.builtin.table import TableMutateTool, TableQueryTool
from server.tools.builtin.table_predict import TablePredictTool

if TYPE_CHECKING:
    from server.schemas import ToolCall

# ── registry ───────────────────────────────────────────────────────

_TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    _TOOLS[tool.name] = tool


def get_tool(name: str) -> Tool | None:
    return _TOOLS.get(name)


# Cross-engine builtins register here. Engine-specific tools self-register from
# their own package (e.g. ``server.market_hive.tools``) so this shared registry
# never imports an engine — the dependency only points engine → shared.
_BUILTIN_TOOLS: tuple[Tool, ...] = (
    FilesTool(),
    RegistryTool(),
    TableQueryTool(),
    TableMutateTool(),
    RPTPredictTool(),
    RPTChatTool(),
    TablePredictTool(),
)
for _tool in _BUILTIN_TOOLS:
    register(_tool)

# The cross-engine builtins are the only tools whose runtime context every engine
# provides. Engine-specific tools (e.g. the market_hive blackboard tools, which
# read ``ctx["db"]``/``run_id``) self-register into the same shared registry, so
# an agent configured with one of them would otherwise be offered it in an engine
# that never populates that context — raising ``KeyError`` mid-run. Engines that
# don't own those tools filter an agent's tool list against this set.
BUILTIN_TOOL_NAMES: frozenset[str] = frozenset(tool.name for tool in _BUILTIN_TOOLS)

# ── provider format builders ───────────────────────────────────────


def get_tools_for_provider(provider: str, tool_names: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for name in tool_names:
        tool = _TOOLS.get(name)
        if tool is None:
            continue
        if provider in ("openai", "groq"):
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
            from server.schemas import ToolCall

            used_tools.append(ToolCall(name=tool_name, input=arguments, output=output))
        return output

    return tool_handler
