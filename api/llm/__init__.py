"""LLM package - unified async call interface with tool support."""

from __future__ import annotations

from typing import Any

from api.tools.registry import get_anthropic_tools, get_openai_tools, make_dispatch

from .anthropic_provider import call_anthropic
from .groq_provider import call_groq
from .openai_provider import call_openai


async def call_agent(
    prompt: str,
    provider: str,
    model: str,
    system_prompt: str | None = None,
    tool_names: list[str] | None = None,
    files: dict[str, str] | None = None,
) -> str:
    """Call an LLM provider with optional system prompt, tools, and file context."""
    context: dict[str, Any] = {"files": files} if files else {}
    dispatch = make_dispatch(context) if tool_names else None

    if provider == "openai":
        tools = get_openai_tools(tool_names) if tool_names else None
        return await call_openai(
            prompt,
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            tool_handler=dispatch,
        )
    elif provider == "groq":
        tools = get_openai_tools(tool_names) if tool_names else None
        return await call_groq(
            prompt,
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            tool_handler=dispatch,
        )
    elif provider == "anthropic":
        tools = get_anthropic_tools(tool_names) if tool_names else None
        return await call_anthropic(
            prompt,
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            tool_handler=dispatch,
        )
    else:
        raise ValueError(f"Unsupported provider: {provider}")
