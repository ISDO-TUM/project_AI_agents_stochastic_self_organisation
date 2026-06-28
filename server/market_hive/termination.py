"""Termination engine — budget, equilibrium, final-output selection (PRD §6.6).

v1 ships a minimal-but-real placeholder. ``MaxRoundsTerminator`` never forces an
early stop — the run loop simply ends when it reaches ``max_rounds`` — and selects
the final answer per thread as the most-cited confirmed finding (tie-break:
earliest ``round_confirmed``). ``TokenTracker`` accounts usage but never reports
exhaustion yet.

The full engine (equilibrium detection over ``k_consecutive`` rounds + enforced
token budget) will replace ``should_terminate`` / ``exhausted`` behind these same
signatures, so the orchestrator does not change when it lands.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection

from server.market_hive.blackboard import Blackboard
from server.market_hive.schemas import ConfirmedEntrySchema, SwarmFinalOutput, SwarmRunConfig


class TokenTracker:
    """Accumulates token usage across a run. Placeholder: never exhausts yet."""

    def __init__(self, budget: int) -> None:
        self.budget = budget
        self.used = 0

    def record(self, tokens: int) -> None:
        self.used += max(0, tokens)

    def exhausted(self) -> bool:
        # Budget enforcement is deferred to the full Termination engine.
        return False


class MaxRoundsTerminator:
    """v1 terminator: run to ``max_rounds``; final answer = most-cited finding."""

    async def should_terminate(
        self, *, run_id: str, round: int, config: SwarmRunConfig, db: AsyncConnection
    ) -> bool:
        # No equilibrium check yet — the round loop's ``max_rounds`` bound is the
        # only stop condition. The real engine implements §6.6 here.
        return False

    async def format_output(
        self, *, run_id: str, round: int, reason: str, db: AsyncConnection
    ) -> SwarmFinalOutput:
        confirmed = await Blackboard(db).get_confirmed(run_id=run_id)
        answers: dict[str, ConfirmedEntrySchema] = {}
        for entry in confirmed:
            if entry.entry_type != "finding":
                continue
            best = answers.get(entry.thread_id)
            if best is None or _ranks_higher(entry, best):
                answers[entry.thread_id] = entry
        return SwarmFinalOutput(
            run_id=run_id,
            answers=answers,
            confirmed_layer=confirmed,
            termination_round=round,
            termination_reason=reason,
            metadata={},
        )


def _ranks_higher(a: ConfirmedEntrySchema, b: ConfirmedEntrySchema) -> bool:
    """True if ``a`` beats ``b``: more citations, then earlier confirmation."""
    # Sort key: more citations wins; ties broken by earlier round_confirmed.
    return (a.citation_count, -a.round_confirmed) > (b.citation_count, -b.round_confirmed)
