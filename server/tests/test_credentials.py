"""Unit tests for request-scoped BYOK credentials."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from server.llm.credentials import (
    MissingCredentialsError,
    RequestCredentials,
    _current,
    current_credentials,
    resolve_api_key,
    resolve_base_url,
    use_credentials,
)


def test_resolve_key_prefers_provider_over_proxy() -> None:
    creds = RequestCredentials(
        keys={"openai": SecretStr("sk-direct")}, proxy_key=SecretStr("proxy")
    )
    assert creds.resolve_key("openai") == "sk-direct"


def test_resolve_key_falls_back_to_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROXY_API_KEY", raising=False)
    creds = RequestCredentials(proxy_key=SecretStr("proxy"))
    assert creds.resolve_key("anthropic") == "proxy"


def test_resolve_key_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "env-groq")
    assert RequestCredentials().resolve_key("groq") == "env-groq"


def test_resolve_key_none_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROXY_API_KEY", raising=False)
    assert RequestCredentials().resolve_key("openai") is None


def test_secret_str_masked_in_repr() -> None:
    creds = RequestCredentials(keys={"openai": SecretStr("sk-supersecret")})
    assert "sk-supersecret" not in repr(creds)
    assert "**********" in repr(creds)


def test_resolve_base_url_header_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://env")
    creds = RequestCredentials(base_urls={"openai": "http://header"})
    assert creds.resolve_base_url("openai") == "http://header"


def test_resolve_api_key_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROXY_API_KEY", raising=False)
    token = _current.set(RequestCredentials())
    try:
        with pytest.raises(MissingCredentialsError):
            resolve_api_key("openai")
    finally:
        _current.reset(token)


def test_missing_error_message_has_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROXY_API_KEY", raising=False)
    token = _current.set(RequestCredentials())
    try:
        with pytest.raises(MissingCredentialsError) as exc:
            resolve_api_key("gemini")
    finally:
        _current.reset(token)
    assert "gemini" in str(exc.value)


async def test_use_credentials_sets_and_resets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROXY_API_KEY", raising=False)
    gen = use_credentials(
        x_llm_openai_key="sk-ctx",
        x_llm_anthropic_key=None,
        x_llm_groq_key=None,
        x_llm_gemini_key=None,
        x_llm_proxy_key=None,
        x_llm_openai_base_url=None,
        x_llm_anthropic_base_url=None,
        x_llm_groq_base_url=None,
        x_llm_gemini_base_url=None,
    )
    await gen.__anext__()
    assert current_credentials().resolve_key("openai") == "sk-ctx"
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    assert current_credentials().resolve_key("openai") is None


def test_resolve_base_url_module_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    token = _current.set(RequestCredentials(base_urls={"openai": "http://p"}))
    try:
        assert resolve_base_url("openai") == "http://p"
    finally:
        _current.reset(token)
