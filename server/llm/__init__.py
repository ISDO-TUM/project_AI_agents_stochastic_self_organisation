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


def _format_tool_results_for_final_answer(tools_used: list[ToolCall]) -> str:
    blocks = []
    for idx, tool in enumerate(tools_used, start=1):
        input_summary = ", ".join(f"{key}={value!r}" for key, value in tool.input.items())
        blocks.append(
            f"Tool result {idx}: {tool.name}({input_summary})\n"
            f"{tool.output.strip() or '[empty result]'}"
        )
    return "\n\n".join(blocks)


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

    if not response.strip() and used_tools:
        final_prompt = (
            f"{prompt}\n\n"
            "You already used tools and received the following results:\n\n"
            f"{_format_tool_results_for_final_answer(used_tools)}\n\n"
            "Now provide your final answer using the tool results above. "
            "Do not call any tools. If the task requires a structured answer format, "
            "follow that format exactly."
        )
        response = await caller(
            final_prompt,
            model=model,
            system_prompt=system_prompt,
            tools=None,
            tool_handler=None,
        )

    return response, used_tools
