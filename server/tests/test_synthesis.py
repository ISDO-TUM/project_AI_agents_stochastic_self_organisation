"""Unit tests for answer synthesis (PRD §6.6 — confirmed findings → final answer)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from unittest.mock import patch

from server.market_hive.schemas import ConfirmedEntrySchema
from server.market_hive.synthesis import (
    NO_ANSWER,
    AnswerSynthesizer,
    FallbackAnswerSynthesizer,
    fallback_answer,
)


def _finding(
    content: str,
    *,
    citation_count: int = 0,
    round_confirmed: int = 2,
    entry_type: Literal["anchor", "finding", "system"] = "finding",
) -> ConfirmedEntrySchema:
    return ConfirmedEntrySchema(
        id=f"id-{content}",
        run_id="run",
        thread_id="thread",
        content=content,
        entry_type=entry_type,
        citation_count=citation_count,
        round_confirmed=round_confirmed,
        created_at=datetime.now(UTC),
    )


def test_fallback_answer_empty_is_explicit_no_answer() -> None:
    assert fallback_answer([]) == NO_ANSWER
    # A board with only anchors/system rows still has no findings to answer with.
    assert fallback_answer([_finding("ctx", entry_type="anchor")]) == NO_ANSWER


def test_fallback_answer_orders_by_citation_count() -> None:
    answer = fallback_answer(
        [
            _finding("weakly cited", citation_count=1),
            _finding("strongly cited", citation_count=9),
        ]
    )
    assert answer.startswith("strongly cited")
    assert "weakly cited" in answer


async def test_fallback_synthesizer_is_deterministic_and_offline() -> None:
    findings = [_finding("the answer", citation_count=3)]
    synth = FallbackAnswerSynthesizer()

    assert await synth.synthesize(prompt="q", findings=findings) == "the answer"


async def test_llm_synthesizer_short_circuits_empty_findings_without_calling() -> None:
    synth = AnswerSynthesizer()
    with patch("server.market_hive.synthesis.call_agent") as call:
        result = await synth.synthesize(prompt="q", findings=[])
    assert result == NO_ANSWER
    call.assert_not_called()


async def test_llm_synthesizer_returns_model_text() -> None:
    synth = AnswerSynthesizer()

    async def fake_call_agent(prompt: str, **kwargs: object) -> tuple[str, list[Any]]:
        return "  A concise synthesised answer.  ", []

    with patch("server.market_hive.synthesis.call_agent", new=fake_call_agent):
        result = await synth.synthesize(prompt="q", findings=[_finding("f1"), _finding("f2")])

    assert result == "A concise synthesised answer."


async def test_llm_synthesizer_falls_back_on_error() -> None:
    synth = AnswerSynthesizer()

    async def boom(prompt: str, **kwargs: object) -> tuple[str, list[Any]]:
        raise RuntimeError("provider down")

    findings = [_finding("durable finding", citation_count=2)]
    with patch("server.market_hive.synthesis.call_agent", new=boom):
        result = await synth.synthesize(prompt="q", findings=findings)

    # Degrades to the deterministic joiner rather than blocking finalisation.
    assert result == "durable finding"
