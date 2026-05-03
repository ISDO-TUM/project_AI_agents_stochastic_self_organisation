import json
import os
from typing import Any

from groq import AsyncGroq

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=os.environ["GROQ_API_KEY"])
    return _client


async def call_groq(
    prompt: str,
    model: str = "llama-3.1-8b-instant",
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

        if not message.tool_calls:
            return message.content or ""

        messages.append(message.model_dump())

        for tool_call in message.tool_calls:
            fn_name = tool_call.function.name
            fn_args = json.loads(tool_call.function.arguments)
            result = await tool_handler(fn_name, fn_args) if tool_handler else ""
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
            )
        kwargs["messages"] = messages

    return messages[-1].get("content", "") if messages else ""
