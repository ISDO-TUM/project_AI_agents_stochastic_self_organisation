"""LLM package unified call interface with tool support."""

from __future__ import annotations

from typing import Any

from api.tools.registry import get_anthropic_tools, get_handler, get_openai_tools

from .anthropic_provider import call_anthropic
from .groq_provider import call_groq
from .openai_provider import call_openai


def _tool_handler(tool_name: str, arguments: dict[str, Any]) -> str:
    """Dispatch a tool call to the appropriate handler."""
    handler = get_handler(tool_name)
    return str(handler(arguments))


def call_agent(
    prompt: str,
    provider: str,
    model: str,
    system_prompt: str | None = None,
    tool_names: list[str] | None = None,
) -> str:
    """Call an LLM provider with optional system prompt and tools.

    This is the main entry point for agent execution.
    """
    if provider == "openai":
        tools = get_openai_tools(tool_names) if tool_names else None
        return call_openai(
            prompt,
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            tool_handler=_tool_handler if tools else None,
        )
    elif provider == "groq":
        tools = get_openai_tools(tool_names) if tool_names else None
        return call_groq(
            prompt,
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            tool_handler=_tool_handler if tools else None,
        )
    elif provider == "anthropic":
        tools = get_anthropic_tools(tool_names) if tool_names else None
        return call_anthropic(
            prompt,
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            tool_handler=_tool_handler if tools else None,
        )
    else:
        raise ValueError(f"Unsupported provider: {provider}")
