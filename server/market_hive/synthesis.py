"""Answer synthesis — confirmed findings → one brief final answer (PRD §6.6).

The termination engine ranks and exposes the Confirmed layer, but a per-thread
list of ratified findings is not yet an *answer* to the user. This module turns
that layer into a single, short reply to the original prompt.

Two implementations of the ``Synthesizer`` seam (see ``termination.py``) live here,
mirroring the Market Maker's input-boundary pair:

* ``FallbackAnswerSynthesizer`` — a no-LLM stand-in that deterministically stitches
  the highest-cited findings together. It is the orchestrator default so the run
  loop and the whole test suite stay LLM-free.
* ``AnswerSynthesizer`` — one LLM call that *summarises* the findings into a couple
  of sentences. Routes inject it for real runs; it falls back to the deterministic
  joiner on any error so a missing key or slow provider never blocks finalisation.
"""

from __future__ import annotations

import asyncio
import logging

from server.llm import call_agent
from server.market_hive.schemas import ConfirmedEntrySchema

logger = logging.getLogger(__name__)

# Returned when the swarm ratified nothing — an honest "no answer" beats inventing one.
NO_ANSWER = "The swarm did not converge on a confirmed answer."

_MAX_FINDINGS = 12  # Cap how many findings reach the prompt so it stays bounded.

_SYSTEM_PROMPT = (
    "You are the synthesis step of a multi-agent collaboration system. A swarm of "
    "specialist agents has deliberated on a shared blackboard and ratified a set of "
    "confirmed findings. Combine those findings into a single, direct answer to the "
    "user's original request.\n\n"
    "Rules:\n"
    "- Answer the request directly, grounded ONLY in the confirmed findings.\n"
    "- Be brief: at most a few sentences. No preamble, no restating the question, "
    "no bullet lists unless the answer is inherently a short list.\n"
    "- Do not introduce facts, caveats, or recommendations the findings do not support.\n"
    "- Write plain prose addressed to the end user."
)


def _findings_only(findings: list[ConfirmedEntrySchema]) -> list[ConfirmedEntrySchema]:
    """Keep ratified findings; drop anchors/system rows that are not answers."""
    return [f for f in findings if f.entry_type == "finding"]


def _ranked(findings: list[ConfirmedEntrySchema]) -> list[ConfirmedEntrySchema]:
    """Most-endorsed first; ties broken by the earlier confirmation (more settled)."""
    return sorted(findings, key=lambda f: (f.citation_count, -f.round_confirmed), reverse=True)


def fallback_answer(findings: list[ConfirmedEntrySchema]) -> str:
    """Deterministic, no-LLM synthesis: stitch the top findings' content together.

    Degraded but always available — it cannot truly *summarise* (that needs the
    LLM), so it concatenates the most-cited findings. Used as the orchestrator
    default and as ``AnswerSynthesizer``'s safety net on any LLM failure.
    """
    ranked = _ranked(_findings_only(findings))
    if not ranked:
        return NO_ANSWER
    return " ".join(f.content.strip() for f in ranked[:3] if f.content.strip()) or NO_ANSWER


def _user_prompt(
    prompt: str,
    findings: list[ConfirmedEntrySchema],
    *,
    objections: list[str] | None = None,
) -> str:
    block = "\n".join(f"- {f.content.strip()}" for f in _ranked(findings)[:_MAX_FINDINGS])
    objection_block = (
        "\n\nThe takers reviewed this draft and objected: "
        + "; ".join(objections)
        + ". Revise to address these objections without inventing content beyond "
        "the confirmed findings."
        if objections
        else ""
    )
    return (
        f"User request:\n{prompt}\n\n"
        f"Confirmed findings (most-endorsed first):\n{block}"
        f"{objection_block}\n\n"
        "Write the brief final answer to the user's request."
    )


class FallbackAnswerSynthesizer:
    """No-LLM synthesizer: deterministic join of the confirmed findings."""

    async def synthesize(
        self,
        *,
        prompt: str,
        findings: list[ConfirmedEntrySchema],
        objections: list[str] | None = None,
    ) -> str:
        # Deterministic join has no revision mechanism — objections are accepted
        # for interface parity with AnswerSynthesizer but have nothing to act on.
        return fallback_answer(findings)


class AnswerSynthesizer:
    """LLM-backed synthesizer: confirmed findings → a couple of sentences."""

    def __init__(
        self,
        *,
        provider: str = "openai",
        model: str = "gpt-4o",
        # On timeout the deterministic joiner takes over — the run still ends,
        # but the final answer degrades to concatenated findings. Keep generous
        # so a slow provider doesn't silently swallow the synthesis step. 300s
        # matches the reasoning-model latency budget used elsewhere in the
        # codebase (gpt-5 family can spend minutes on a single completion); it
        # does not retry on timeout, it just falls back to the deterministic join.
        timeout: float = 300.0,
    ) -> None:
        self._provider = provider
        self._model = model
        self._timeout = timeout

    async def synthesize(
        self,
        *,
        prompt: str,
        findings: list[ConfirmedEntrySchema],
        objections: list[str] | None = None,
    ) -> str:
        """One LLM call → brief answer. Falls back to the joiner on empty/failure.

        ``objections`` (ratified synthesis): when the takers rejected a prior
        draft, their reasons are appended to the prompt so the revision
        specifically addresses them rather than starting from scratch.
        """
        findings = _findings_only(findings)
        if not findings:
            return NO_ANSWER
        try:
            response, _ = await asyncio.wait_for(
                call_agent(
                    _user_prompt(prompt, findings, objections=objections),
                    provider=self._provider,
                    model=self._model,
                    system_prompt=_SYSTEM_PROMPT,
                ),
                timeout=self._timeout,
            )
        except TimeoutError:
            logger.warning(
                "AnswerSynthesizer LLM call timed out after %.0fs; using fallback.", self._timeout
            )
            return fallback_answer(findings)
        except Exception:
            logger.exception("AnswerSynthesizer LLM call failed; using fallback.")
            return fallback_answer(findings)

        return response.strip() or fallback_answer(findings)
