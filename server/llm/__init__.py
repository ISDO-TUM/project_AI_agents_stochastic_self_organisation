"""LLM package - unified async call interface with tool support."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from server.schemas import ToolCall
from server.tools.registry import create_tool_handler, get_tools_for_provider

from .anthropic_provider import call_anthropic
from .gemini_provider import call_gemini
from .groq_provider import call_groq
from .openai_provider import call_openai

PROVIDERS: dict[str, Callable[..., Coroutine[Any, Any, str]]] = {
    "openai": call_openai,
    "groq": call_groq,
    "anthropic": call_anthropic,
    "gemini": call_gemini,
}


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
    tool_handler = create_tool_handler(tool_context or {}, used_tools) if tool_names else None
    tools = get_tools_for_provider(provider, tool_names) if tool_names else None

    caller = PROVIDERS.get(provider)
    if caller is None:
        raise ValueError(f"Unsupported provider: {provider}. Choose from: {list(PROVIDERS)}")

    response = await caller(
        prompt,
        model=model,
        system_prompt=system_prompt,
        tools=tools,
        tool_handler=tool_handler,
    )

    return response, used_tools
