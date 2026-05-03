import os
from typing import Any

from anthropic import AsyncAnthropic

from .normalizer import extract_anthropic_tool_calls

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


async def call_anthropic(
    prompt: str,
    model: str = "claude-haiku-4-5-20251001",
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_handler: Any | None = None,
) -> str:
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": 1024,
        "messages": messages,
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    if tools:
        kwargs["tools"] = tools

    max_iterations = 10
    for _ in range(max_iterations):
        response = await _get_client().messages.create(**kwargs)

        tool_calls = extract_anthropic_tool_calls(response)

        if not tool_calls:
            text_blocks = [b.text for b in response.content if hasattr(b, "text")]
            return "\n".join(text_blocks)

        assistant_content = [
            b.model_dump() if hasattr(b, "model_dump") else {"type": b.type, "text": b.text}
            for b in response.content
        ]
        messages.append({"role": "assistant", "content": assistant_content})

        tool_results = []
        for tc in tool_calls:
            result = await tool_handler(tc.name, tc.arguments) if tool_handler else ""
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result,
                }
            )
        messages.append({"role": "user", "content": tool_results})
        kwargs["messages"] = messages

    text_blocks = [b.text for b in response.content if hasattr(b, "text")]
    return "\n".join(text_blocks)
