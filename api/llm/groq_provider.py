import os
from typing import Any

from groq import AsyncGroq

from .normalizer import extract_openai_tool_calls

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=os.environ["GROQ_API_KEY"])
    return _client


async def call_groq(
    prompt: str,
    model: str = "llama-3.3-70b-versatile",
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_handler: Any | None = None,
) -> str:
    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        kwargs["tools"] = tools
        kwargs["parallel_tool_calls"] = False

    max_iterations = 10
    for _ in range(max_iterations):
        response = await _get_client().chat.completions.create(**kwargs)
        message = response.choices[0].message

        tool_calls = extract_openai_tool_calls(message)
        if not tool_calls:
            return message.content or ""

        messages.append(
            {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [tc.model_dump() for tc in message.tool_calls],
            }
        )

        for tc in tool_calls:
            result = await tool_handler(tc.name, tc.arguments) if tool_handler else ""
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                }
            )
        kwargs["messages"] = messages

    return messages[-1].get("content", "") if messages else ""
