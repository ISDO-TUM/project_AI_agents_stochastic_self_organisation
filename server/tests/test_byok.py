"""Integration tests for BYOK header plumbing and no-leak guarantees."""

from __future__ import annotations

import logging
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

_ALL_KEY_ENV = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "LLM_PROXY_API_KEY",
    "OPENAI_BASE_URL",
    "ANTHROPIC_BASE_URL",
    "GROQ_BASE_URL",
    "GEMINI_BASE_URL",
)

_OPENAI_AGENT = {
    "name": "Tester",
    "description": "",
    "system_prompt": "",
    "provider": "openai",
    "model": "gpt-4o-mini",
    "tools": [],
    "connections": [],
}


def _fake_openai_response(text: str) -> MagicMock:
    message = MagicMock()
    message.content = text
    message.tool_calls = None
    choice = MagicMock()
    choice.message = message
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _capturing_openai_ctor(
    captured: dict[str, object], text: str = "ok"
) -> Callable[..., MagicMock]:
    def _ctor(**kwargs: object) -> MagicMock:
        captured.update(kwargs)
        inst = MagicMock()
        inst.chat.completions.create = AsyncMock(return_value=_fake_openai_response(text))
        return inst

    return _ctor


async def _create_openai_agent(client: AsyncClient) -> str:
    resp = await client.post("/api/agents", json=_OPENAI_AGENT)
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def test_agent_run_uses_header_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    agent_id = await _create_openai_agent(client)
    captured: dict[str, object] = {}
    with patch(
        "server.llm.openai_provider.AsyncOpenAI",
        side_effect=_capturing_openai_ctor(captured, "hi"),
    ):
        resp = await client.post(
            f"/api/agents/{agent_id}/run",
            json={"prompt": "hello"},
            headers={"X-LLM-OpenAI-Key": "sk-header-123"},
        )
    assert resp.status_code == 200, resp.text
    assert captured["api_key"] == "sk-header-123"


async def test_agent_run_missing_key_returns_400(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in _ALL_KEY_ENV:
        monkeypatch.delenv(var, raising=False)
    agent_id = await _create_openai_agent(client)
    resp = await client.post(f"/api/agents/{agent_id}/run", json={"prompt": "x"})
    assert resp.status_code == 400


async def test_key_not_leaked_on_provider_error(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    agent_id = await _create_openai_agent(client)

    def _boom(**kwargs: object) -> MagicMock:
        inst = MagicMock()
        inst.chat.completions.create = AsyncMock(side_effect=RuntimeError("upstream boom"))
        return inst

    secret = "sk-leak-SECRET-DO-NOT-LOG"  # noqa: S105
    with patch("server.llm.openai_provider.AsyncOpenAI", side_effect=_boom):
        with caplog.at_level(logging.DEBUG):
            resp = await client.post(
                f"/api/agents/{agent_id}/run",
                json={"prompt": "x"},
                headers={"X-LLM-OpenAI-Key": secret},
            )
    assert resp.status_code == 502
    assert secret not in resp.text
    assert secret not in caplog.text


async def test_models_filtered_by_header_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in _ALL_KEY_ENV:
        monkeypatch.delenv(var, raising=False)
    resp = await client.get("/api/models", headers={"X-LLM-Anthropic-Key": "sk-a"})
    assert resp.status_code == 200
    providers = {m["provider"] for m in resp.json()}
    assert providers == {"anthropic"}


async def test_models_returns_sap_ids_with_base_url(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in _ALL_KEY_ENV:
        monkeypatch.delenv(var, raising=False)
    resp = await client.get(
        "/api/models",
        headers={
            "X-LLM-Anthropic-Key": "sk-a",
            "X-LLM-Anthropic-Base-Url": "http://proxy",
        },
    )
    assert resp.status_code == 200
    ids = {m["id"] for m in resp.json()}
    assert any(i.startswith("anthropic--") for i in ids)


async def test_models_empty_without_keys(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in _ALL_KEY_ENV:
        monkeypatch.delenv(var, raising=False)
    resp = await client.get("/api/models")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_simulation_propagates_key_through_gather(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    await _create_openai_agent(client)
    captured: dict[str, object] = {}
    with patch(
        "server.llm.openai_provider.AsyncOpenAI",
        side_effect=_capturing_openai_ctor(captured, "REASON: r\nVOTE: x"),
    ):
        resp = await client.post(
            "/api/simulation/run",
            json={"prompt": "hi", "rounds": 1, "mode": "voting"},
            headers={"X-LLM-OpenAI-Key": "sk-sim-key"},
        )
    assert resp.status_code == 200, resp.text
    assert captured.get("api_key") == "sk-sim-key"
