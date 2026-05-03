import json
import os
from typing import Any

from anthropic import Anthropic

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def call_anthropic(
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
        response = _get_client().messages.create(**kwargs)

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_use_blocks:
            text_blocks = [b.text for b in response.content if hasattr(b, "text")]
            return "\n".join(text_blocks)

        assistant_content = [
            b.model_dump() if hasattr(b, "model_dump") else {"type": b.type, "text": b.text}
            for b in response.content
        ]
        messages.append({"role": "assistant", "content": assistant_content})

        tool_results = []
        for block in tool_use_blocks:
            fn_name = block.name
            fn_args = block.input if isinstance(block.input, dict) else json.loads(block.input)
            result = tool_handler(fn_name, fn_args) if tool_handler else ""
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                }
            )
        messages.append({"role": "user", "content": tool_results})
        kwargs["messages"] = messages

    text_blocks = [b.text for b in response.content if hasattr(b, "text")]
    return "\n".join(text_blocks)
