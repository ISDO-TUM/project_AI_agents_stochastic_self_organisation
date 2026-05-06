import os
from typing import Any

from openai import AsyncOpenAI

from .base_provider import BaseLLMProvider
from .normalizer import NormalizedToolCall, extract_openai_tool_calls

_client: AsyncOpenAI | None = None


def _get_openai_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


class OpenAIProvider(BaseLLMProvider):
    def _get_client(self) -> AsyncOpenAI:
        return _get_openai_client()

    def _build_messages(self, prompt: str, system_prompt: str | None) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _build_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        return kwargs

    async def _send(self, kwargs: dict[str, Any]) -> Any:
        return await self._get_client().chat.completions.create(**kwargs)

    def _extract_tool_calls(self, response: Any) -> list[NormalizedToolCall]:
        return extract_openai_tool_calls(response.choices[0].message)

    def _extract_text(self, response: Any) -> str:
        return response.choices[0].message.content or ""

    def _append_assistant_and_tool_results(
        self,
        messages: list[dict[str, Any]],
        response: Any,
        tool_results: list[tuple[NormalizedToolCall, str]],
    ) -> None:
        messages.append(response.choices[0].message.model_dump())
        for tc, result in tool_results:
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})


async def call_openai(
    prompt: str,
    model: str = "gpt-4o-mini",
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_handler: Any | None = None,
) -> str:
    return await OpenAIProvider().call(
        prompt,
        model=model,
        system_prompt=system_prompt,
        tools=tools,
        tool_handler=tool_handler,
    )
