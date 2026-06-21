"""Base provider with template method for the tool-call loop."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

from .normalizer import NormalizedToolCall

logger = logging.getLogger(__name__)

# Maximum wall-clock seconds for a single complete agent call (all tool
# iterations included).  Prevents runaway loops from blocking indefinitely.
_DEFAULT_TIMEOUT_SECONDS = 60


class BaseLLMProvider(ABC):
    """Template for LLM providers — subclasses override formatting hooks."""

    # Reduced from 10: limits how many tool-call round-trips a single agent
    # call may perform, capping both cost and latency exposure.
    max_iterations: int = 20

    # Per-call timeout in seconds.  Subclasses may override.
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS

    @abstractmethod
    def _get_client(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    def _build_messages(self, prompt: str, system_prompt: str | None) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def _build_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def _send(self, kwargs: dict[str, Any]) -> Any:
        raise NotImplementedError

    @abstractmethod
    def _extract_tool_calls(self, response: Any) -> list[NormalizedToolCall]:
        raise NotImplementedError

    @abstractmethod
    def _extract_text(self, response: Any) -> str:
        raise NotImplementedError

    @abstractmethod
    def _append_assistant_and_tool_results(
        self,
        messages: list[dict[str, Any]],
        response: Any,
        tool_results: list[tuple[NormalizedToolCall, str]],
    ) -> None:
        raise NotImplementedError

    async def call(
        self,
        prompt: str,
        model: str,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_handler: Any | None = None,
    ) -> str:
        logger.debug("LLM call start — model=%s tools=%s", model, list(tools or []))
        try:
            result = await asyncio.wait_for(
                self._call_inner(prompt, model, system_prompt, tools, tool_handler),
                timeout=self.timeout_seconds,
            )
            logger.debug("LLM call complete — model=%s", model)
            return result
        except TimeoutError as err:
            logger.error("LLM call timed out after %ds — model=%s", self.timeout_seconds, model)
            raise TimeoutError(
                f"The LLM call exceeded the maximum allowed time ({self.timeout_seconds}s). "
                "Please try again with a shorter prompt or fewer tools."
            ) from err
        except Exception:
            logger.exception("LLM call failed — model=%s", model)
            raise

    async def _call_inner(
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
        for iteration in range(self.max_iterations):
            logger.debug("LLM send iteration %d — model=%s", iteration + 1, model)
            response = await self._send(kwargs)
            tool_calls = self._extract_tool_calls(response)

            if not tool_calls:
                return self._extract_text(response)

            results: list[tuple[NormalizedToolCall, str]] = []
            for tc in tool_calls:
                logger.debug("Tool call — name=%s args=%s", tc.name, tc.arguments)
                result = await tool_handler(tc.name, tc.arguments) if tool_handler else ""
                results.append((tc, result))

            self._append_assistant_and_tool_results(messages, response, results)
            kwargs["messages"] = messages

        return self._extract_text(response) if response else ""
