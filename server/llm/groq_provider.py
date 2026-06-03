from typing import Any

from groq import AsyncGroq

from .credentials import resolve_api_key, resolve_base_url
from .langfuse_setup import langfuse_context, observe
from .normalizer import NormalizedToolCall
from .openai_provider import OpenAIProvider


def _get_groq_client() -> AsyncGroq:
    """Build a per-request AsyncGroq client from the current credentials.

    When a base URL is set (header or env) the client points to that URL instead
    of Groq's public API — used to route calls through the local proxy.
    """
    kwargs: dict[str, Any] = {"api_key": resolve_api_key("groq")}
    base_url = resolve_base_url("groq")
    if base_url:
        kwargs["base_url"] = base_url
    return AsyncGroq(**kwargs)


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

    @observe(as_type="generation", name="groq")
    async def _send(self, kwargs: dict[str, Any]) -> Any:
        response = await self._get_client().chat.completions.create(**kwargs)
        usage = getattr(response, "usage", None)
        langfuse_context.update_current_observation(
            model=kwargs.get("model"),
            input=kwargs.get("messages"),
            usage={
                "input": getattr(usage, "prompt_tokens", None),
                "output": getattr(usage, "completion_tokens", None),
            }
            if usage
            else None,
        )
        return response

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
