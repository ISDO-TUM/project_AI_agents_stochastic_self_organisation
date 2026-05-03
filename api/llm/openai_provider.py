import os
from typing import Any

from openai import AsyncOpenAI

from .normalizer import extract_openai_tool_calls

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


async def call_openai(
    prompt: str,
    model: str = "gpt-4o-mini",
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

    max_iterations = 10
    for _ in range(max_iterations):
        response = await _get_client().chat.completions.create(**kwargs)
        message = response.choices[0].message

        tool_calls = extract_openai_tool_calls(message)
        if not tool_calls:
            return message.content or ""

        messages.append(message.model_dump())

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
