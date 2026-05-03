"""LLM package - unified async call interface with tool support."""

from __future__ import annotations

from typing import Any

from api.schemas import ToolCall
from api.tools.registry import build_tool_dispatcher, get_anthropic_tools, get_openai_tools

from .anthropic_provider import call_anthropic
from .groq_provider import call_groq
from .openai_provider import call_openai


async def call_agent(
    prompt: str,
    provider: str,
    model: str,
    system_prompt: str | None = None,
    tool_names: list[str] | None = None,
    tool_context: dict[str, Any] | None = None,
) -> tuple[str, list[ToolCall]]:
    """Call an LLM provider with optional system prompt and tools.

    Returns a tuple of (response_text, tools_used).
    """
    used_tools: list[ToolCall] = []
    dispatch = build_tool_dispatcher(tool_context or {}, used_tools) if tool_names else None

    if provider == "openai":
        tools = get_openai_tools(tool_names) if tool_names else None
        response = await call_openai(
            prompt,
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            tool_handler=dispatch,
        )
    elif provider == "groq":
        tools = get_openai_tools(tool_names) if tool_names else None
        response = await call_groq(
            prompt,
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            tool_handler=dispatch,
        )
    elif provider == "anthropic":
        tools = get_anthropic_tools(tool_names) if tool_names else None
        response = await call_anthropic(
            prompt,
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            tool_handler=dispatch,
        )
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    return response, used_tools
