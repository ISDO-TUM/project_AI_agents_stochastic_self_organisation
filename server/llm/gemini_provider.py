"""Gemini LLM provider.

Gemini is implemented via direct ``httpx`` REST calls rather than the
``google-genai`` SDK because the SDK does not support a custom base URL,
making it incompatible with proxy routing. The proxy endpoint shape is:

    POST <GEMINI_BASE_URL>/v1beta/models/{model}:generateContent

Tool calling uses Gemini's ``functionDeclarations`` / ``functionResponse``
format, which differs from OpenAI and Anthropic:
  - Tools are sent as ``tools: [{functionDeclarations: [...]}]``
  - The model replies with ``functionCall`` parts (role ``model``)
  - Results are returned as ``functionResponse`` parts (role ``user``)

The API key is sent as a Bearer token in the ``Authorization`` header,
consistent with how the proxy authenticates all providers.
"""

from typing import Any, cast

import httpx

from .base_provider import BaseLLMProvider
from .credentials import resolve_api_key, resolve_base_url
from .normalizer import NormalizedToolCall, extract_gemini_tool_calls

_DEFAULT_MAX_TOKENS = 1024


def _get_base_url() -> str:
    return resolve_base_url("gemini") or "https://generativelanguage.googleapis.com"


def _get_api_key() -> str:
    return resolve_api_key("gemini")


class GeminiProvider(BaseLLMProvider):
    """Gemini provider using the REST generateContent endpoint.

    Stateless — a new ``httpx`` client is opened per request because Gemini
    has no persistent SDK client to cache.
    """

    def _get_client(self) -> None:
        return None

    def _build_messages(self, prompt: str, system_prompt: str | None) -> list[dict[str, Any]]:
        return [{"role": "user", "parts": [{"text": prompt}]}]

    def _build_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "contents": messages,
            "generationConfig": {"maxOutputTokens": _DEFAULT_MAX_TOKENS},
        }
        if tools:
            body["tools"] = [{"functionDeclarations": tools}]
        return {"model": model, "body": body}

    async def _send(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        model = kwargs["model"]
        body = kwargs["body"]
        base_url = _get_base_url()
        api_key = _get_api_key()
        url = f"{base_url}/v1beta/models/{model}:generateContent"
        # Proxy expects Bearer token; Google's direct API expects x-goog-api-key.
        using_proxy = bool(resolve_base_url("gemini"))
        headers = (
            {"Authorization": f"Bearer {api_key}"} if using_proxy else {"x-goog-api-key": api_key}
        )
        async with httpx.AsyncClient() as client:
            req = client.build_request("POST", url, json=body, headers=headers)
            response = await client.send(req)
            if not response.is_success:
                raise RuntimeError(f"Gemini {response.status_code}: {response.text}")
            return cast(dict[str, Any], response.json())

    def _extract_tool_calls(self, response: dict[str, Any]) -> list[NormalizedToolCall]:
        return extract_gemini_tool_calls(response)

    def _extract_text(self, response: dict[str, Any]) -> str:
        parts = []
        for candidate in response.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if "text" in part and not part.get("thought", False):
                    parts.append(part["text"])
        return "\n".join(parts)

    def _append_assistant_and_tool_results(
        self,
        messages: list[dict[str, Any]],
        response: dict[str, Any],
        tool_results: list[tuple[NormalizedToolCall, str]],
    ) -> None:
        # Replay the model's function call turn, excluding thought parts.
        # Gemini 2.5 thinking models generate thought parts before tool calls;
        # echoing them back in history confuses the model and breaks subsequent replies.
        model_parts = []
        for candidate in response.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if not part.get("thought", False):
                    model_parts.append(part)
        messages.append({"role": "model", "parts": model_parts})

        # One functionResponse part per tool result
        result_parts = [
            {
                "functionResponse": {
                    "name": tc.name,
                    "response": {"name": tc.name, "content": result},
                }
            }
            for tc, result in tool_results
        ]
        messages.append({"role": "user", "parts": result_parts})

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
            kwargs["body"]["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        response: dict[str, Any] = {}
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
            kwargs["body"]["contents"] = messages

        return self._extract_text(response)


async def call_gemini(
    prompt: str,
    model: str = "gemini-2.0-flash",
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_handler: Any | None = None,
) -> str:
    return await GeminiProvider().call(
        prompt,
        model=model,
        system_prompt=system_prompt,
        tools=tools,
        tool_handler=tool_handler,
    )
