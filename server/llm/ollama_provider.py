"""Ollama provider for locally-hosted models (e.g. the Qwen-based tabular model).

Ollama exposes an OpenAI-compatible API (default ``http://localhost:11434/v1``),
so this provider reuses :class:`OpenAIProvider`'s message/tool/response handling
and only swaps in a client pointed at the local endpoint. No API key is required
for a stock local Ollama install, so the key falls back to a dummy value when the
caller supplies none.
"""

import asyncio
import json
import re
import uuid
from typing import Any
from urllib.parse import urlparse

from openai import AsyncOpenAI

from .credentials import MissingCredentialsError, resolve_api_key, resolve_base_url
from .normalizer import NormalizedToolCall
from .openai_provider import OpenAIProvider

#: Where a stock local Ollama install serves its OpenAI-compatible API.
_DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"

#: Ollama ignores the API key, but the OpenAI client requires a non-empty one.
_PLACEHOLDER_KEY = "ollama"

#: How long to wait when probing whether an Ollama server is up (seconds).
#: Generous enough for a LAN host, not just loopback.
_PROBE_TIMEOUT = 1.5


def _normalize_base_url(base_url: str) -> str:
    """Ensure the OpenAI-compatible ``/v1`` path is present.

    Ollama serves the OpenAI API under ``/v1``; users often enter just the host
    and port (e.g. ``http://192.168.0.107:11434``), so append ``/v1`` when no
    path is given rather than letting the request 404.
    """
    trimmed = base_url.rstrip("/")
    if not urlparse(trimmed).path:
        return f"{trimmed}/v1"
    return trimmed


async def ollama_available(base_url: str) -> bool:
    """True if an Ollama server accepts a TCP connection at ``base_url``.

    Used to auto-detect availability with zero configuration: present when an
    ``ollama serve`` is reachable at the configured endpoint and absent
    otherwise, so no env flag is needed in any environment.
    """
    parsed = urlparse(base_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 11434
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=_PROBE_TIMEOUT
        )
    except (TimeoutError, OSError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


def _get_ollama_client() -> AsyncOpenAI:
    """Build an AsyncOpenAI client aimed at the local Ollama endpoint.

    Base URL and key come from the request/env credentials when present
    (``OLLAMA_BASE_URL`` / ``OLLAMA_API_KEY`` or the ``X-LLM-Ollama-*`` headers),
    otherwise fall back to the local default and a placeholder key. Any reachable
    endpoint is allowed (loopback, LAN, or remote).
    """
    base_url = _normalize_base_url(resolve_base_url("ollama") or _DEFAULT_OLLAMA_BASE_URL)
    try:
        api_key = resolve_api_key("ollama")
    except MissingCredentialsError:
        api_key = _PLACEHOLDER_KEY
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


# Small quantized local models frequently emit tool calls as plain text in the
# content field instead of the structured ``tool_calls`` field (the GGUF chat
# template fails to parse them). These patterns recover such "leaked" calls.
_TOOL_CALL_TAG_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _coerce_tool_call(obj: Any) -> NormalizedToolCall | None:
    """Turn a parsed JSON object into a tool call if it looks like one."""
    if not isinstance(obj, dict):
        return None
    name = obj.get("name")
    args = obj.get("arguments", obj.get("parameters"))
    if not isinstance(name, str) or not name:
        return None
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    if not isinstance(args, dict):
        return None
    return NormalizedToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name=name, arguments=args)


def _parse_text_tool_calls(content: str) -> list[NormalizedToolCall]:
    """Recover tool calls a local model emitted as text in its content.

    Handles ``<tool_call>{...}</tool_call>`` tags, ```json fenced blocks, one
    JSON object per line, and a whole-content JSON object. Identical calls are
    de-duplicated. Returns ``[]`` when nothing looks like a tool call.
    """
    if not content or '"name"' not in content:
        return []
    candidates: list[str] = []
    candidates += _TOOL_CALL_TAG_RE.findall(content)
    candidates += _JSON_FENCE_RE.findall(content)
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            candidates.append(line)
    stripped = content.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)

    calls: list[NormalizedToolCall] = []
    seen: set[str] = set()
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        tc = _coerce_tool_call(obj)
        if tc is None:
            continue
        key = f"{tc.name}:{json.dumps(tc.arguments, sort_keys=True)}"
        if key in seen:
            continue
        seen.add(key)
        calls.append(tc)
    return calls


class OllamaProvider(OpenAIProvider):
    def _get_client(self) -> AsyncOpenAI:
        return _get_ollama_client()

    def _extract_tool_calls(self, response: Any) -> list[NormalizedToolCall]:
        # Prefer the structured tool_calls field; fall back to parsing any tool
        # call the model leaked into its text content.
        calls = super()._extract_tool_calls(response)
        if calls:
            return calls
        return _parse_text_tool_calls(self._extract_text(response) or "")

    def _append_assistant_and_tool_results(
        self,
        messages: list[dict[str, Any]],
        response: Any,
        tool_results: list[tuple[NormalizedToolCall, str]],
    ) -> None:
        message = response.choices[0].message
        if getattr(message, "tool_calls", None):
            # Structured call: use the standard OpenAI assistant + tool messages.
            super()._append_assistant_and_tool_results(messages, response, tool_results)
            return
        # Leaked-into-content call: a `tool` role with no matching assistant
        # tool_call would be rejected, so record the assistant text and feed the
        # results back as a user turn instead.
        messages.append({"role": "assistant", "content": message.content or ""})
        combined = "\n\n".join(
            f"Result of `{tc.name}({json.dumps(tc.arguments)})`:\n{result}"
            for tc, result in tool_results
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    "Here are the results of the tools you requested. Use them to "
                    "answer now; do not emit tool-call JSON again.\n\n" + combined
                ),
            }
        )


async def call_ollama(
    prompt: str,
    model: str = "hf.co/QuantFactory/TableGPT2-7B-GGUF:Q4_K_M",
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_handler: Any | None = None,
) -> str:
    return await OllamaProvider().call(
        prompt,
        model=model,
        system_prompt=system_prompt,
        tools=tools,
        tool_handler=tool_handler,
    )
