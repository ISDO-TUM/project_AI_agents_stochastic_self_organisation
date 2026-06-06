"""Ollama provider for locally-hosted models (e.g. the Qwen-based tabular model).

Ollama exposes an OpenAI-compatible API (default ``http://localhost:11434/v1``),
so this provider reuses :class:`OpenAIProvider`'s message/tool/response handling
and only swaps in a client pointed at the local endpoint. No API key is required
for a stock local Ollama install, so the key falls back to a dummy value when the
caller supplies none.
"""

import asyncio
import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

from openai import AsyncOpenAI

from .credentials import MissingCredentialsError, resolve_api_key, resolve_base_url
from .openai_provider import OpenAIProvider

#: Where a stock local Ollama install serves its OpenAI-compatible API.
_DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"

#: Ollama ignores the API key, but the OpenAI client requires a non-empty one.
_PLACEHOLDER_KEY = "ollama"

#: How long to wait when probing whether an Ollama server is up (seconds).
_PROBE_TIMEOUT = 0.3


def _is_loopback(base_url: str) -> bool:
    """True only if ``base_url``'s host resolves to a loopback address.

    Restricting Ollama to loopback keeps it usable for local development while
    removing it as a server-side request forgery vector in any deployed
    environment (a forged ``X-LLM-Ollama-Base-Url`` can only ever hit localhost).
    """
    host = urlparse(base_url).hostname
    if not host:
        return False
    try:
        # Resolve every address the host maps to; all must be loopback.
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            if not ipaddress.ip_address(addr).is_loopback:
                return False
        except ValueError:
            return False
    return bool(infos)


async def ollama_available(base_url: str) -> bool:
    """True if a loopback Ollama server accepts a TCP connection at ``base_url``.

    Used to auto-detect availability with zero configuration: present in local
    dev (``ollama serve`` running) and absent in production (nothing listening on
    the deployment host's loopback), so no env flag is needed in either place.
    """
    if not _is_loopback(base_url):
        return False
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
    otherwise fall back to the local default and a placeholder key. The endpoint
    is required to be loopback (see :func:`_is_loopback`).
    """
    base_url = resolve_base_url("ollama") or _DEFAULT_OLLAMA_BASE_URL
    if not _is_loopback(base_url):
        raise ValueError("Ollama is only available on a local (loopback) endpoint.")
    try:
        api_key = resolve_api_key("ollama")
    except MissingCredentialsError:
        api_key = _PLACEHOLDER_KEY
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


class OllamaProvider(OpenAIProvider):
    def _get_client(self) -> AsyncOpenAI:
        return _get_ollama_client()


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
