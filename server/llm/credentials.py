"""Request-scoped LLM credentials (BYOK).

Credentials arrive as ``X-LLM-*`` request headers, are parsed into a
:class:`RequestCredentials` (keys held as ``SecretStr`` so they never appear in
logs or tracebacks), and published on a :class:`contextvars.ContextVar` for the
duration of one request. Provider clients read the current credentials at
construction time and are discarded when the request ends — nothing is persisted.

When no header is supplied the resolver falls back to environment variables, so
local development with a populated ``.env`` keeps working.

Precedence per provider: header provider key > header proxy key > env provider
key > env ``LLM_PROXY_API_KEY``.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextvars import ContextVar
from typing import Annotated

from fastapi import Header
from pydantic import BaseModel, Field, SecretStr

# provider -> (env key var, env base-url var)
_PROVIDER_ENV: dict[str, tuple[str, str]] = {
    "openai": ("OPENAI_API_KEY", "OPENAI_BASE_URL"),
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"),
    "groq": ("GROQ_API_KEY", "GROQ_BASE_URL"),
    "gemini": ("GEMINI_API_KEY", "GEMINI_BASE_URL"),
}


class MissingCredentialsError(Exception):
    """Raised when no API key is available for a provider (header or env)."""


class RequestCredentials(BaseModel):
    """Per-request LLM credentials. Keys are masked in repr via ``SecretStr``."""

    keys: dict[str, SecretStr] = Field(default_factory=dict)
    base_urls: dict[str, str] = Field(default_factory=dict)
    proxy_key: SecretStr | None = None

    def resolve_key(self, provider: str) -> str | None:
        """Header provider key > header proxy key > env provider key > env proxy key."""
        if provider in self.keys:
            return self.keys[provider].get_secret_value()
        if self.proxy_key is not None:
            return self.proxy_key.get_secret_value()
        env_key_var, _ = _PROVIDER_ENV[provider]
        return os.environ.get(env_key_var) or os.environ.get("LLM_PROXY_API_KEY")

    def resolve_base_url(self, provider: str) -> str | None:
        """Header base URL > env base URL > None (provider default)."""
        if provider in self.base_urls:
            return self.base_urls[provider]
        _, env_url_var = _PROVIDER_ENV[provider]
        return os.environ.get(env_url_var) or None

    def has_key(self, provider: str) -> bool:
        return self.resolve_key(provider) is not None


_current: ContextVar[RequestCredentials | None] = ContextVar("llm_credentials", default=None)


def current_credentials() -> RequestCredentials:
    """Credentials for the active request, or an env-only fallback."""
    creds = _current.get()
    return creds if creds is not None else RequestCredentials()


def resolve_api_key(provider: str) -> str:
    key = current_credentials().resolve_key(provider)
    if not key:
        raise MissingCredentialsError(
            f"No API key for provider '{provider}'. Provide it via the matching "
            "X-LLM-* header or set the corresponding environment variable."
        )
    return key


def resolve_base_url(provider: str) -> str | None:
    return current_credentials().resolve_base_url(provider)


def _build(
    *,
    openai_key: str | None,
    anthropic_key: str | None,
    groq_key: str | None,
    gemini_key: str | None,
    proxy_key: str | None,
    openai_base_url: str | None,
    anthropic_base_url: str | None,
    groq_base_url: str | None,
    gemini_base_url: str | None,
) -> RequestCredentials:
    raw_keys = {
        "openai": openai_key,
        "anthropic": anthropic_key,
        "groq": groq_key,
        "gemini": gemini_key,
    }
    raw_urls = {
        "openai": openai_base_url,
        "anthropic": anthropic_base_url,
        "groq": groq_base_url,
        "gemini": gemini_base_url,
    }
    keys = {p: SecretStr(v) for p, v in raw_keys.items() if v}
    base_urls = {p: v for p, v in raw_urls.items() if v}
    return RequestCredentials(
        keys=keys,
        base_urls=base_urls,
        proxy_key=SecretStr(proxy_key) if proxy_key else None,
    )


async def use_credentials(
    x_llm_openai_key: Annotated[str | None, Header()] = None,
    x_llm_anthropic_key: Annotated[str | None, Header()] = None,
    x_llm_groq_key: Annotated[str | None, Header()] = None,
    x_llm_gemini_key: Annotated[str | None, Header()] = None,
    x_llm_proxy_key: Annotated[str | None, Header()] = None,
    x_llm_openai_base_url: Annotated[str | None, Header()] = None,
    x_llm_anthropic_base_url: Annotated[str | None, Header()] = None,
    x_llm_groq_base_url: Annotated[str | None, Header()] = None,
    x_llm_gemini_base_url: Annotated[str | None, Header()] = None,
) -> AsyncIterator[None]:
    """FastAPI dependency: publish per-request credentials on the ContextVar."""
    creds = _build(
        openai_key=x_llm_openai_key,
        anthropic_key=x_llm_anthropic_key,
        groq_key=x_llm_groq_key,
        gemini_key=x_llm_gemini_key,
        proxy_key=x_llm_proxy_key,
        openai_base_url=x_llm_openai_base_url,
        anthropic_base_url=x_llm_anthropic_base_url,
        groq_base_url=x_llm_groq_base_url,
        gemini_base_url=x_llm_gemini_base_url,
    )
    token = _current.set(creds)
    try:
        yield
    finally:
        _current.reset(token)
