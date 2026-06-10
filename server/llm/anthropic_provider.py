from typing import Any

from anthropic import AsyncAnthropic

from .base_provider import BaseLLMProvider
from .credentials import resolve_api_key, resolve_base_url
from .langfuse_setup import observe, update_current_generation
from .normalizer import NormalizedToolCall, extract_anthropic_tool_calls

# max_tokens is required by the Anthropic API (no server-side default).
# Haiku 4.5 caps at 64k output; Sonnet 4.6 and Opus 4.7 cap at 64k output.
_DEFAULT_MAX_TOKENS = 1024


def _get_anthropic_client() -> AsyncAnthropic:
    """Build a per-request AsyncAnthropic client from the current credentials.

    When a base URL is set (header or env) the client points to that URL instead
    of Anthropic's public API — used to route calls through the local proxy.
    """
    kwargs: dict[str, Any] = {"api_key": resolve_api_key("anthropic")}
    base_url = resolve_base_url("anthropic")
    if base_url:
        kwargs["base_url"] = base_url
    return AsyncAnthropic(**kwargs)


class AnthropicProvider(BaseLLMProvider):
    def _get_client(self) -> AsyncAnthropic:
        return _get_anthropic_client()

    def _build_messages(self, prompt: str, system_prompt: str | None) -> list[dict[str, Any]]:
        return [{"role": "user", "content": prompt}]

    def _build_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": _DEFAULT_MAX_TOKENS,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        return kwargs

    async def call(
        self,
        prompt: str,
        model: str,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_handler: Any | None = None,
    ) -> str:
        messages = self._build_messages(prompt, system_prompt)
        kwargs = self._build_kwargs(model, messages, tools)
        if system_prompt:
            kwargs["system"] = system_prompt

        response: Any = None
        for _ in range(self.max_iterations):
            response = await self._send(kwargs)
            tool_calls = self._extract_tool_calls(response)

            if not tool_calls:
                return self._extract_text(response)

            results: list[tuple[NormalizedToolCall, str]] = []
            for tc in tool_calls:
                result = await tool_handler(tc.name, tc.arguments) if tool_handler else ""
                results.append((tc, result))

            self._append_assistant_and_tool_results(messages, response, results)
            kwargs["messages"] = messages

        return self._extract_text(response) if response else ""

    @observe(as_type="generation", name="anthropic")
    async def _send(self, kwargs: dict[str, Any]) -> Any:
        response = await self._get_client().messages.create(**kwargs)
        usage = getattr(response, "usage", None)
        update_current_generation(
            model=kwargs.get("model"),
            input=kwargs.get("messages"),
            usage={
                "input": getattr(usage, "input_tokens", None),
                "output": getattr(usage, "output_tokens", None),
            }
            if usage
            else None,
        )
        return response

    def _extract_tool_calls(self, response: Any) -> list[NormalizedToolCall]:
        return extract_anthropic_tool_calls(response)

    def _extract_text(self, response: Any) -> str:
        text_blocks = [b.text for b in response.content if hasattr(b, "text")]
        return "\n".join(text_blocks)

    def _append_assistant_and_tool_results(
        self,
        messages: list[dict[str, Any]],
        response: Any,
        tool_results: list[tuple[NormalizedToolCall, str]],
    ) -> None:
        assistant_content = []
        for b in response.content:
            if b.type == "tool_use":
                assistant_content.append(
                    {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
                )
            elif b.type == "text":
                assistant_content.append({"type": "text", "text": b.text})
        messages.append({"role": "assistant", "content": assistant_content})
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": tc.id, "content": result}
                    for tc, result in tool_results
                ],
            }
        )


async def call_anthropic(
    prompt: str,
    model: str = "claude-haiku-4-5-20251001",
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_handler: Any | None = None,
) -> str:
    return await AnthropicProvider().call(
        prompt,
        model=model,
        system_prompt=system_prompt,
        tools=tools,
        tool_handler=tool_handler,
    )
