"""Tests for the LLM provider connectivity endpoints."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast
from unittest.mock import patch

import pytest
from httpx import AsyncClient

import server.llm as llm_module
from server.llm import call_agent
from server.schemas import ToolCall


async def test_openai_success(client: AsyncClient) -> None:
    with patch("server.routes.test.call_openai", return_value="Hello from OpenAI"):
        response = await client.post("/api/test/openai", json={"prompt": "Hello"})
    assert response.status_code == 200
    assert response.json() == {"response": "Hello from OpenAI"}


async def test_openai_provider_error(client: AsyncClient) -> None:
    with patch("server.routes.test.call_openai", side_effect=RuntimeError("connection refused")):
        response = await client.post("/api/test/openai", json={"prompt": "Hello"})
    assert response.status_code == 502
    assert response.json()["detail"] == "LLM provider unavailable"


async def test_openai_missing_prompt(client: AsyncClient) -> None:
    response = await client.post("/api/test/openai", json={})
    assert response.status_code == 422


async def test_anthropic_success(client: AsyncClient) -> None:
    with patch("server.routes.test.call_anthropic", return_value="Hello from Anthropic"):
        response = await client.post("/api/test/anthropic", json={"prompt": "Hello"})
    assert response.status_code == 200
    assert response.json() == {"response": "Hello from Anthropic"}


async def test_anthropic_provider_error(client: AsyncClient) -> None:
    with patch("server.routes.test.call_anthropic", side_effect=RuntimeError("auth failed")):
        response = await client.post("/api/test/anthropic", json={"prompt": "Hello"})
    assert response.status_code == 502
    assert response.json()["detail"] == "LLM provider unavailable"


async def test_anthropic_missing_prompt(client: AsyncClient) -> None:
    response = await client.post("/api/test/anthropic", json={})
    assert response.status_code == 422


async def test_groq_success(client: AsyncClient) -> None:
    with patch("server.routes.test.call_groq", return_value="Hello from Groq"):
        response = await client.post("/api/test/groq", json={"prompt": "Hello"})
    assert response.status_code == 200
    assert response.json() == {"response": "Hello from Groq"}


async def test_groq_provider_error(client: AsyncClient) -> None:
    with patch("server.routes.test.call_groq", side_effect=RuntimeError("rate limited")):
        response = await client.post("/api/test/groq", json={"prompt": "Hello"})
    assert response.status_code == 502
    assert response.json()["detail"] == "LLM provider unavailable"


async def test_groq_missing_prompt(client: AsyncClient) -> None:
    response = await client.post("/api/test/groq", json={})
    assert response.status_code == 422


async def test_error_detail_does_not_leak_internal_message(client: AsyncClient) -> None:
    """502 responses must not expose raw exception messages to the client."""
    internal_message = "internal-error-detail-not-for-clients"
    with patch("server.routes.test.call_openai", side_effect=RuntimeError(internal_message)):
        response = await client.post("/api/test/openai", json={"prompt": "Hello"})
    assert response.status_code == 502
    assert internal_message not in response.json()["detail"]


async def test_call_agent_retries_blank_tool_response_without_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_provider(
        prompt: str,
        **kwargs: object,
    ) -> str:
        calls.append({"prompt": prompt, **kwargs})
        if kwargs["tools"]:
            used_tools = cast(
                Callable[[str, dict[str, Any]], Awaitable[str]],
                kwargs["tool_handler"],
            )
            result = await used_tools("files", {"action": "read", "file_name": "org.txt"})
            assert "Clara Jensen" in result
            return ""
        assert "Clara Jensen" in prompt
        return "REASON: File says Clara Jensen has code Z.\nVOTE: Clara Jensen"

    monkeypatch.setitem(llm_module.PROVIDERS, "openai", fake_provider)

    response, tools_used = await call_agent(
        "Who has code Z?",
        provider="openai",
        model="fake",
        tool_names=["files"],
        tool_context={"files": {"org.txt": "Clara Jensen has code Z."}},
    )

    assert response.endswith("VOTE: Clara Jensen")
    assert tools_used == [
        ToolCall(
            name="files",
            input={"action": "read", "file_name": "org.txt"},
            output="Clara Jensen has code Z.",
        )
    ]
    assert len(calls) == 2
    assert calls[1]["tools"] is None
