"""Termination engine — budget, equilibrium, final-output selection (PRD §6.6).

This module owns deterministic run-ending logic. The orchestrator reaches it
through ``MaxRoundsTerminator``'s small seam while tests and routes can use the
full ``TerminationEngine`` directly.

``MaxRoundsTerminator`` keeps the name introduced on main for compatibility, but
it now delegates to the real PRD §6.6 implementation: equilibrium detection over
quiet confirmed-finding rounds and final answer selection by citation count.
Token-budget tracking is implemented here as an opt-in/opt-out utility; the
current orchestrator does not yet pass usage events into it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Literal, Protocol, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from server.market_hive.schemas import ConfirmedEntrySchema, SwarmFinalOutput, SwarmRunConfig

TerminationReason = Literal["equilibrium", "max_rounds", "budget"]


class Synthesizer(Protocol):
    """Turns the confirmed findings into one brief answer to the original prompt.

    A structural seam (see ``server.market_hive.synthesis``) so ``format_output``
    can stay LLM-free in tests: pass no synthesizer and ``final_answer`` is ``None``.
    """

    async def synthesize(
        self,
        *,
        prompt: str,
        findings: list[ConfirmedEntrySchema],
        objections: list[str] | None = None,
    ) -> str: ...


# 3, not 2: the round loop starts at round 2 (round 1 is proposals + votes), so a
# minimum of 2 would let equilibrium fire on the very first discussion round, before
# deliberation has happened. 3 requires at least two real discussion rounds first.
DEFAULT_MIN_ROUNDS = 3
DEFAULT_MAX_ROUNDS = 10
DEFAULT_K_CONSECUTIVE = 2
DEFAULT_EPSILON_ENTROPY = 0
DEFAULT_TOKEN_BUDGET = 50_000
DEFAULT_MIN_TURN_BUDGET = 1_000


@dataclass
class TokenUsageRecord:
    """One token accounting event from an LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int | None = None
    model: str | None = None
    agent_id: str | None = None
    phase: str | None = None

    def total(self) -> int:
        if self.total_tokens is not None:
            return self.total_tokens
        return self.input_tokens + self.output_tokens


@dataclass
class TokenTracker:
    """Run-scoped token budget accounting.

    Set ``enabled=False`` to make budget checks permissive and usage recording a
    no-op. The snapshot still records that tracking was disabled, which keeps
    persisted metadata explicit.
    """

    budget: int = DEFAULT_TOKEN_BUDGET
    min_turn_budget: int = DEFAULT_MIN_TURN_BUDGET
    enabled: bool = True
    records: list[TokenUsageRecord] = field(default_factory=list)
    started_at: float = field(default_factory=monotonic)

    def record(
        self,
        tokens: int | None = None,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int | None = None,
        model: str | None = None,
        agent_id: str | None = None,
        phase: str | None = None,
    ) -> None:
        """Record one LLM usage event when tracking is enabled.

        ``tokens`` is accepted for compatibility with main's placeholder tracker;
        richer call sites can pass input/output/model/agent/phase metadata.
        """
        if not self.enabled:
            return
        if tokens is not None and total_tokens is None:
            total_tokens = tokens
        self.records.append(
            TokenUsageRecord(
                input_tokens=max(0, input_tokens),
                output_tokens=max(0, output_tokens),
                total_tokens=max(0, total_tokens) if total_tokens is not None else None,
                model=model,
                agent_id=agent_id,
                phase=phase,
            )
        )

    def used(self) -> int:
        if not self.enabled:
            return 0
        return sum(record.total() for record in self.records)

    def remaining(self) -> int:
        if not self.enabled:
            return self.budget
        return max(0, self.budget - self.used())

    def exhausted(self) -> bool:
        return self.enabled and self.remaining() <= 0

    def can_start_turn(self, min_turn_budget: int | None = None) -> bool:
        if not self.enabled:
            return True
        return self.remaining() >= (min_turn_budget or self.min_turn_budget)

    def snapshot(self) -> dict[str, Any]:
        totals_by_model: dict[str, int] = {}
        totals_by_agent: dict[str, int] = {}
        totals_by_phase: dict[str, int] = {}
        for record in self.records:
            total = record.total()
            if record.model:
                totals_by_model[record.model] = totals_by_model.get(record.model, 0) + total
            if record.agent_id:
                totals_by_agent[record.agent_id] = totals_by_agent.get(record.agent_id, 0) + total
            if record.phase:
                totals_by_phase[record.phase] = totals_by_phase.get(record.phase, 0) + total

        return {
            "enabled": self.enabled,
            "budget": self.budget,
            "min_turn_budget": self.min_turn_budget,
            "used": self.used(),
            "remaining": self.remaining(),
            "exhausted": self.exhausted(),
            "calls": len(self.records) if self.enabled else 0,
            "by_model": totals_by_model,
            "by_agent": totals_by_agent,
            "by_phase": totals_by_phase,
            "latency_seconds": round(monotonic() - self.started_at, 3),
        }


class TerminationEngine:
    """Run termination logic for one DB connection."""

    def __init__(
        self,
        db: AsyncConnection,
        *,
        min_rounds: int = DEFAULT_MIN_ROUNDS,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        k_consecutive: int = DEFAULT_K_CONSECUTIVE,
        epsilon_entropy: int = DEFAULT_EPSILON_ENTROPY,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        min_turn_budget: int = DEFAULT_MIN_TURN_BUDGET,
        enable_token_budget: bool = True,
    ) -> None:
        self._db = db
        self.min_rounds = min_rounds
        self.max_rounds = max_rounds
        self.k_consecutive = k_consecutive
        self.epsilon_entropy = epsilon_entropy
        self.token_budget = token_budget
        self.min_turn_budget = min_turn_budget
        self.enable_token_budget = enable_token_budget

    @classmethod
    def from_config(cls, db: AsyncConnection, config: Any) -> TerminationEngine:
        """Build from ``SwarmRunConfig`` or a compatible object."""
        return cls(
            db,
            min_rounds=config.min_rounds,
            max_rounds=config.max_rounds,
            k_consecutive=config.k_consecutive,
            epsilon_entropy=config.epsilon_entropy,
            token_budget=config.token_budget,
            min_turn_budget=getattr(config, "min_turn_budget", DEFAULT_MIN_TURN_BUDGET),
            enable_token_budget=getattr(config, "enable_token_budget", True),
        )

    def new_tracker(self) -> TokenTracker:
        """Create a tracker using this engine's budget settings."""
        return TokenTracker(
            budget=self.token_budget,
            min_turn_budget=self.min_turn_budget,
            enabled=self.enable_token_budget,
        )

    async def count_confirmed_this_round(self, *, run_id: str, round: int) -> int:
        """Count newly confirmed findings for a round, excluding anchors/system rows."""
        return int(
            (
                await self._db.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM confirmed_entries
                        WHERE run_id = :run_id
                          AND round_confirmed = :round
                          AND entry_type = 'finding'
                        """
                    ),
                    {"run_id": run_id, "round": round},
                )
            ).scalar_one()
        )

    async def has_confirmed_findings(self, *, run_id: str) -> bool:
        """True once the run has promoted at least one finding.

        Equilibrium (PRD §6.6) is the state where confirmations have *ceased* — it
        presupposes the swarm produced something to converge on. A run that has
        confirmed nothing has not converged; it has not begun. Without this guard
        an all-quiet cold start (every round trivially at/below ``epsilon_entropy``
        because nothing is ever confirmed) satisfies the K-round window on the very
        first check and ends the run with an empty Confirmed board.
        """
        count = (
            await self._db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM confirmed_entries
                    WHERE run_id = :run_id AND entry_type = 'finding'
                    """
                ),
                {"run_id": run_id},
            )
        ).scalar_one()
        return int(count) > 0

    async def check_equilibrium(
        self, *, run_id: str, current_round: int, status_flips: int = 0
    ) -> bool:
        """Return true when the swarm has converged.

        Convergence requires *both* that the run has confirmed at least one finding
        and that the last ``k_consecutive`` promotion rounds added no more than
        ``epsilon_entropy`` new findings. The two guards below keep a cold start —
        an empty board where every round is trivially quiet — from being mistaken
        for convergence and ending the run before any proposal can be promoted.

        ``status_flips`` (contestable consensus): a contest or re-affirmation this
        round counts as activity too — it forces at least one more round of
        deliberation rather than letting the run end on a freshly-contested finding.
        """
        if current_round < self.min_rounds:
            return False

        if status_flips > 0:
            return False

        # Nothing confirmed yet ⇒ the swarm has not started converging, let alone
        # converged. Skipping this check is the cold-start bug: the trailing window
        # is quiet only because no citations have accumulated into a promotion yet.
        if not await self.has_confirmed_findings(run_id=run_id):
            return False

        # Promotions only run from round 2 onward (round 1 is opening proposals plus
        # the vote sub-round, and votes are not promotion signals), so round 1 is
        # structurally always quiet. Start the window at round 2 so it spans only
        # rounds that *could* have promoted; counting round 1 would pad the window
        # with a guaranteed-quiet round and make the swarm look converged a round early.
        start_round = max(2, current_round - self.k_consecutive + 1)
        for round_number in range(start_round, current_round + 1):
            new_confirmed = await self.count_confirmed_this_round(run_id=run_id, round=round_number)
            if new_confirmed > self.epsilon_entropy:
                return False
        return True

    async def select_final_answer(
        self,
        *,
        run_id: str,
        thread_id: str,
    ) -> ConfirmedEntrySchema | None:
        """Pick the highest-cited confirmed finding for one thread.

        Excludes contested/retracted rows (contestable consensus) — a finding
        that lost its democratic standing should not be featured as *the*
        thread answer even while the audit-visible ``confirmed_layer`` still
        carries it for transparency.
        """
        row = (
            (
                await self._db.execute(
                    text(
                        """
                        SELECT id, run_id, thread_id, source_draft_id, content,
                               entry_type, citation_count, round_confirmed, created_at,
                               status
                        FROM confirmed_entries
                        WHERE run_id = :run_id
                          AND thread_id = :thread_id
                          AND entry_type = 'finding'
                          AND status = 'confirmed'
                        ORDER BY citation_count DESC, round_confirmed ASC, created_at ASC
                        LIMIT 1
                        """
                    ),
                    {"run_id": run_id, "thread_id": thread_id},
                )
            )
            .mappings()
            .fetchone()
        )
        return ConfirmedEntrySchema(**dict(row)) if row is not None else None

    async def format_output(
        self,
        *,
        run_id: str,
        termination_round: int,
        termination_reason: TerminationReason,
        tracker: TokenTracker | None = None,
        metadata: dict[str, Any] | None = None,
        prompt: str | None = None,
        synthesizer: Synthesizer | None = None,
    ) -> SwarmFinalOutput:
        """Build the final output object from confirmed state.

        When a ``synthesizer`` and the original ``prompt`` are supplied, the
        confirmed findings are also condensed into a single ``final_answer``. Both
        are optional so callers that only need the structured layers (e.g. the
        audit endpoint, which reads the persisted answer instead) skip the LLM call.

        Contestable consensus: any entry still ``contested`` at this point never
        gathered enough fresh citations to re-affirm, so it is retracted here —
        the row is never deleted (P-03), only its status changes, and it stays
        visible in ``confirmed_layer`` for audit even though it excludes itself
        from ``final_answer`` and from ``answers`` (via ``select_final_answer``).
        """
        await self._db.execute(
            text(
                "UPDATE confirmed_entries SET status = 'retracted' "
                "WHERE run_id = :run_id AND status = 'contested'"
            ),
            {"run_id": run_id},
        )
        await self._db.commit()

        threads = (
            (
                await self._db.execute(
                    text("SELECT id FROM threads WHERE run_id = :run_id ORDER BY created_at ASC"),
                    {"run_id": run_id},
                )
            )
            .scalars()
            .all()
        )

        answers: dict[str, ConfirmedEntrySchema] = {}
        for thread_id in threads:
            answer = await self.select_final_answer(run_id=run_id, thread_id=str(thread_id))
            if answer is not None:
                answers[answer.thread_id] = answer

        confirmed_layer = await self._confirmed_layer(run_id=run_id)
        final_metadata = await self._metadata(run_id=run_id)
        if tracker is not None:
            final_metadata["token_usage"] = tracker.snapshot()
        if metadata:
            final_metadata.update(metadata)

        final_answer: str | None = None
        if synthesizer is not None and prompt is not None:
            # Only live (status='confirmed') findings feed synthesis — a
            # contested/just-retracted entry must not shape the answer text,
            # even though it remains visible in confirmed_layer for audit.
            live_findings = [f for f in confirmed_layer if f.status == "confirmed"]
            final_answer = await synthesizer.synthesize(prompt=prompt, findings=live_findings)

        return SwarmFinalOutput(
            run_id=run_id,
            answers=answers,
            confirmed_layer=confirmed_layer,
            final_answer=final_answer,
            termination_round=termination_round,
            termination_reason=termination_reason,
            metadata=final_metadata,
        )

    async def complete_run(
        self,
        *,
        run_id: str,
        termination_round: int,
        termination_reason: TerminationReason,
        tracker: TokenTracker | None = None,
        token_usage: dict[str, Any] | None = None,
    ) -> None:
        """Persist completed run bookkeeping."""
        usage = token_usage if token_usage is not None else tracker.snapshot() if tracker else {}
        await self._db.execute(
            text(
                """
                UPDATE swarm_runs
                SET status = 'completed',
                    termination_reason = :reason,
                    termination_round = :round,
                    token_usage = :token_usage,
                    completed_at = CURRENT_TIMESTAMP
                WHERE id = :run_id
                """
            ),
            {
                "run_id": run_id,
                "reason": termination_reason,
                "round": termination_round,
                "token_usage": json.dumps(usage),
            },
        )
        await self._db.commit()

    async def _confirmed_layer(self, *, run_id: str) -> list[ConfirmedEntrySchema]:
        """Every confirmed row regardless of status (audit trail — P-03: nothing
        is ever deleted, so contested/retracted findings stay visible here even
        though they are excluded from synthesis and per-thread ``answers``)."""
        rows = (
            (
                await self._db.execute(
                    text(
                        """
                        SELECT id, run_id, thread_id, source_draft_id, content,
                               entry_type, citation_count, round_confirmed, created_at,
                               status, origin_run_id
                        FROM confirmed_entries
                        WHERE run_id = :run_id
                        ORDER BY round_confirmed ASC, created_at ASC
                        """
                    ),
                    {"run_id": run_id},
                )
            )
            .mappings()
            .fetchall()
        )
        return [ConfirmedEntrySchema(**dict(row)) for row in rows]

    async def _metadata(self, *, run_id: str) -> dict[str, Any]:
        taker_rows = (
            await self._db.execute(
                text(
                    """
                    SELECT DISTINCT agent_id
                    FROM bids
                    WHERE run_id = :run_id AND is_taker = true
                    """
                ),
                {"run_id": run_id},
            )
        ).fetchall()
        observer_rows_raw = (
            await self._db.execute(
                text(
                    """
                    SELECT DISTINCT agent_id
                    FROM bids
                    WHERE run_id = :run_id AND is_observer = true
                    """
                ),
                {"run_id": run_id},
            )
        ).fetchall()
        draft_author_rows = (
            await self._db.execute(
                text(
                    """
                    SELECT DISTINCT author_id
                    FROM draft_entries
                    WHERE run_id = :run_id
                    """
                ),
                {"run_id": run_id},
            )
        ).fetchall()

        takers = sorted(str(row[0]) for row in taker_rows)
        observer_rows = sorted(str(row[0]) for row in observer_rows_raw)
        observers = sorted(set(observer_rows) - set(takers))
        draft_authors = sorted(str(row[0]) for row in draft_author_rows)

        return {
            "agent_participation": {
                "takers": takers,
                "observers": observers,
                "draft_authors": draft_authors,
            }
        }


class MaxRoundsTerminator:
    """Orchestrator-facing termination adapter.

    The name is retained from main's placeholder seam, but the behavior now
    delegates to the full termination engine: equilibrium may stop the loop
    before ``max_rounds``, and output selection uses the PRD §6.6 ranking.
    """

    async def should_terminate(
        self,
        *,
        run_id: str,
        round: int,
        config: SwarmRunConfig,
        db: AsyncConnection,
        status_flips: int = 0,
    ) -> bool:
        return await TerminationEngine.from_config(db, config).check_equilibrium(
            run_id=run_id,
            current_round=round,
            status_flips=status_flips,
        )

    async def format_output(
        self,
        *,
        run_id: str,
        round: int,
        reason: str,
        db: AsyncConnection,
        prompt: str | None = None,
        synthesizer: Synthesizer | None = None,
    ) -> SwarmFinalOutput:
        return await TerminationEngine(db).format_output(
            run_id=run_id,
            termination_round=round,
            termination_reason=cast(TerminationReason, reason),
            prompt=prompt,
            synthesizer=synthesizer,
        )
