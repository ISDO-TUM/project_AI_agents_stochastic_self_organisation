"""Base provider with template method for the tool-call loop."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from abc import ABC, abstractmethod
from time import monotonic
from typing import Any

from .normalizer import NormalizedToolCall

logger = logging.getLogger(__name__)

# Maximum wall-clock seconds for a single complete agent call (all tool
# iterations included). This is a hang backstop, NOT a performance budget:
# a hung connection must never stall a run forever, but a call that is
# genuinely still working must never be cut off. The old 90s cap covered the
# ENTIRE tool-call loop — up to max_iterations sequential round-trips, each
# resending a growing message history — and reasoning models (gpt-5 family)
# can spend minutes on a single completion, so legitimate turns were killed
# mid-flight. 600s matches the OpenAI SDK's own per-request default, giving
# the whole loop at least one full SDK-length request of headroom.
# Overridable via LLM_CALL_TIMEOUT_S. The orchestrator derives its outer
# TURN_TIMEOUT_S from this (market_hive/orchestrator.py) so this timeout's
# more specific error message always fires first instead of racing it.
_DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("LLM_CALL_TIMEOUT_S", "600"))

# A model that gets a tool call rejected (length cap, reply cap, semantic
# dedup, whatever) is supposed to read the error and change course — retry
# differently, or stop. Some models instead just retry the same rejected call
# near-verbatim, burning iterations without making progress: a live run hit
# iterations=20 / 156s on a single turn this way, invisible in the logs
# because tool calls only logged at DEBUG. If every tool call in the last N
# iterations came back an error, the model isn't recovering — end the turn
# now with whatever text it has instead of silently exhausting max_iterations
# (worst case ~30s/iteration * 20 = a turn that looks "just slow" but is
# actually stuck).
_MAX_CONSECUTIVE_ERROR_ITERATIONS = 3


def _is_tool_error(result: str) -> bool:
    """True for this codebase's error convention: a tool result that is (or
    starts with) a JSON object with an "error" key, e.g. '{"error": "..."}'.
    A heuristic, not a parse — tool results are free-form strings and most
    aren't JSON at all, so this only needs to catch the convention, not
    validate it."""
    return result.strip().startswith('{"error"')


# A slow turn and a hung turn look identical in the logs otherwise: nothing
# is written between "LLM call start" (DEBUG, easy to miss) and "LLM call
# complete" — which never comes if it's actually stuck. A real run went
# completely silent for 9+ minutes this way before the whole process died,
# with no signal in between to tell a merely-slow reasoning model apart from
# a genuine hang. This logs a heartbeat while a call is still in flight so
# that distinction is visible in real time, not reconstructed after the fact.
_PROGRESS_LOG_INTERVAL_S = 30


async def _log_in_flight_progress(model: str, started: float) -> None:
    try:
        while True:
            await asyncio.sleep(_PROGRESS_LOG_INTERVAL_S)
            logger.warning(
                "LLM call still in progress — model=%s elapsed=%.0fs and counting "
                "(no completion yet; watch for this repeating without end — that's a hang)",
                model,
                monotonic() - started,
            )
    except asyncio.CancelledError:
        pass


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
        max_iterations: int | None = None,
    ) -> str:
        logger.debug("LLM call start — model=%s tools=%s", model, list(tools or []))
        started = monotonic()
        watchdog = asyncio.create_task(_log_in_flight_progress(model, started))
        try:
            result, iterations = await asyncio.wait_for(
                self._call_inner(prompt, model, system_prompt, tools, tool_handler, max_iterations),
                timeout=self.timeout_seconds,
            )
            # Speed instrumentation (temporary, pending real numbers from a live run):
            # each agentic tool-call round-trip is a full LLM request, so a "turn"
            # that took N iterations spent roughly N sequential network calls, not
            # one — this is the number that explains a slow run, not just elapsed
            # time alone. INFO so it shows up without flipping on debug logging.
            logger.info(
                "LLM call complete — model=%s iterations=%d elapsed=%.2fs",
                model,
                iterations,
                monotonic() - started,
            )
            return result
        except TimeoutError as err:
            logger.error(
                "LLM call timed out after %ds (elapsed=%.2fs) — model=%s",
                self.timeout_seconds,
                monotonic() - started,
                model,
            )
            raise TimeoutError(
                f"The LLM call exceeded the maximum allowed time ({self.timeout_seconds}s). "
                "The provider is likely hung or unreachable; raise LLM_CALL_TIMEOUT_S "
                "if legitimate calls need more time."
            ) from err
        except Exception:
            logger.exception("LLM call failed after %.2fs — model=%s", monotonic() - started, model)
            raise
        finally:
            watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watchdog

    async def _call_inner(
        self,
        prompt: str,
        model: str,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_handler: Any | None = None,
        max_iterations: int | None = None,
    ) -> tuple[str, int]:
        effective_max_iterations = (
            max_iterations if max_iterations is not None else self.max_iterations
        )
        messages = self._build_messages(prompt, system_prompt)
        kwargs = self._build_kwargs(model, messages, tools)

        response: Any = None
        # Per-tool-name streak, not per-iteration: a turn that alternates a
        # failing post_to_blackboard with a harmless read_blackboard every
        # iteration never has an "all calls in this iteration failed"
        # iteration, so an iteration-level counter never trips even though
        # the model is stuck on the exact same rejected action the whole
        # time — confirmed live: a turn ran the full 20 iterations retrying
        # `post_to_blackboard` after "you cannot refines your own entry",
        # because each iteration also made a succeeding call alongside it.
        # Tracking each tool's own streak (reset only by THAT tool
        # succeeding) catches this regardless of what else is happening in
        # the same turn.
        consecutive_errors_by_tool: dict[str, int] = {}
        for iteration in range(effective_max_iterations):
            logger.debug("LLM send iteration %d — model=%s", iteration + 1, model)
            response = await self._send(kwargs)
            tool_calls = self._extract_tool_calls(response)

            if not tool_calls:
                return self._extract_text(response), iteration + 1

            results: list[tuple[NormalizedToolCall, str]] = []
            stuck_tool: str | None = None
            for tc in tool_calls:
                result = await tool_handler(tc.name, tc.arguments) if tool_handler else ""
                if _is_tool_error(result):
                    logger.info(
                        "Tool call rejected — model=%s name=%s args=%s -> %s",
                        model,
                        tc.name,
                        tc.arguments,
                        result[:300],
                    )
                    streak = consecutive_errors_by_tool.get(tc.name, 0) + 1
                    consecutive_errors_by_tool[tc.name] = streak
                    if streak >= _MAX_CONSECUTIVE_ERROR_ITERATIONS:
                        stuck_tool = tc.name
                else:
                    logger.debug("Tool call — model=%s name=%s args=%s", model, tc.name, tc.arguments)
                    consecutive_errors_by_tool[tc.name] = 0
                results.append((tc, result))

            self._append_assistant_and_tool_results(messages, response, results)
            kwargs["messages"] = messages

            if stuck_tool is not None:
                logger.warning(
                    "LLM call ending turn early — model=%s tool=%s got %d consecutive "
                    "rejections at iteration %d/%d (last: %s) — the model isn't recovering "
                    "from this rejected tool call, so stopping now instead of exhausting the "
                    "iteration budget on repeated failures.",
                    model,
                    stuck_tool,
                    consecutive_errors_by_tool[stuck_tool],
                    iteration + 1,
                    effective_max_iterations,
                    [r for _, r in results],
                )
                return self._extract_text(response), iteration + 1

        return (self._extract_text(response) if response else ""), effective_max_iterations
