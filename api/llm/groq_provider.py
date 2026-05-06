import os
from typing import Any

from groq import AsyncGroq

from .normalizer import NormalizedToolCall
from .openai_provider import OpenAIProvider

_client: AsyncGroq | None = None


def _get_groq_client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=os.environ["GROQ_API_KEY"])
    return _client


class GroqProvider(OpenAIProvider):
    """Groq uses the OpenAI-compatible format with minor tweaks."""

    def _get_client(self) -> Any:
        return _get_groq_client()

    def _build_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        kwargs = super()._build_kwargs(model, messages, tools)
        if tools:
            kwargs["parallel_tool_calls"] = False
        return kwargs

    def _append_assistant_and_tool_results(
        self,
        messages: list[dict[str, Any]],
        response: Any,
        tool_results: list[tuple[NormalizedToolCall, str]],
    ) -> None:
        message = response.choices[0].message
        messages.append(
            {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [tc.model_dump() for tc in message.tool_calls],
            }
        )
        for tc, result in tool_results:
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})


async def call_groq(
    prompt: str,
    model: str = "llama-3.3-70b-versatile",
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_handler: Any | None = None,
) -> str:
    return await GroqProvider().call(
        prompt,
        model=model,
        system_prompt=system_prompt,
        tools=tools,
        tool_handler=tool_handler,
    )
