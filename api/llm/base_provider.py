"""Base provider with template method for the tool-call loop."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .normalizer import NormalizedToolCall


class BaseLLMProvider(ABC):
    """Template for LLM providers — subclasses override formatting hooks."""

    max_iterations: int = 10

    @abstractmethod
    def _get_client(self) -> Any: ...

    @abstractmethod
    def _build_messages(self, prompt: str, system_prompt: str | None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def _build_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def _send(self, kwargs: dict[str, Any]) -> Any: ...

    @abstractmethod
    def _extract_tool_calls(self, response: Any) -> list[NormalizedToolCall]: ...

    @abstractmethod
    def _extract_text(self, response: Any) -> str: ...

    @abstractmethod
    def _append_assistant_and_tool_results(
        self,
        messages: list[dict[str, Any]],
        response: Any,
        tool_results: list[tuple[NormalizedToolCall, str]],
    ) -> None: ...

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
