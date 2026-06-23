"""Convergence engine — confidence, conceding temperature, reputation (PRD §6.4).

This module turns the blackboard's raw citation/vote signals into the per-agent
scalars that steer deliberation:

* **Confidence** — how widely an agent's posts are cited. High confidence means
  the agent holds the consensus view; low confidence means it is an outlier.
  Bootstrapped from the cold-start vote sub-round, then recomputed each round
  from citation share. Confidence is *transient* (recomputed every round, fed
  into the prompt), so it is not persisted — the engine returns it.
* **Conceding temperature** — derived from confidence and a round-rising floor.
  High T = the agent should seek consensus; low T = defend firmly. The engine
  maps T to the natural-language instruction injected into the system prompt.
* **Per-run reputation** — domain credibility within a run, persisted in the
  ``reputation`` table. Rewarded when an agent's entry is promoted to Confirmed,
  penalised when an entry is soft-deleted. Clamped to ``[0, 1]``.

The engine owns only the maths and the reputation persistence. The orchestrator
calls it at the end of each round and injects the results into the next round's
prompts.

Two consistency choices (faithful to the (N-1) denominator and the cite rules):

* Cold-start votes are counted **excluding self-votes** — the ``votes`` table
  does not filter self-votes the way ``cite()`` does, and the
  ``votes / (N_participants - 1)`` formula counts endorsements from *others*.
* Per-round citation counts also defensively exclude self-citations (``cite()``
  already drops them server-side, but the filter keeps the maths correct even
  if a self-citation ever lands in the table).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# ── Defaults (mirror SWARM_DEFAULTS in PRD §15) ────────────────────────────────
DEFAULT_T_INITIAL = 0.0
DEFAULT_DELTA_T = 0.1
DEFAULT_T_MAX = 1.0
DEFAULT_DELTA_CONFIRM = 0.05  # reputation gain for a confirmed entry
DEFAULT_DELTA_REJECT = 0.03  # reputation loss for a soft-deleted entry
DEFAULT_REPUTATION = 0.5  # starting per-run reputation


# Conceding-temperature instruction bands (PRD §6.4). Ordered low → high T.
_TEMPERATURE_BANDS: list[tuple[float, str]] = [
    (0.25, "Defend your analysis firmly. Only revise if shown clear, contradicting evidence."),
    (
        0.50,
        "Acknowledge valid points from others. "
        "Defend your core reasoning but remain open to refinement.",
    ),
    (
        0.75,
        "Actively seek common ground. "
        "Revise your position where others present stronger arguments.",
    ),
    (
        1.01,  # inclusive upper bound for T == 1.0
        "Prioritize consensus. If the majority position is well-supported, "
        "align with it and explain why.",
    ),
]


class ConvergenceEngine:
    """Confidence / temperature / reputation logic for one DB connection."""

    def __init__(
        self,
        db: AsyncConnection,
        *,
        t_initial: float = DEFAULT_T_INITIAL,
        delta_t: float = DEFAULT_DELTA_T,
        t_max: float = DEFAULT_T_MAX,
        delta_confirm: float = DEFAULT_DELTA_CONFIRM,
        delta_reject: float = DEFAULT_DELTA_REJECT,
    ) -> None:
        self._db = db
        self.t_initial = t_initial
        self.delta_t = delta_t
        self.t_max = t_max
        self.delta_confirm = delta_confirm
        self.delta_reject = delta_reject

    @classmethod
    def from_config(cls, db: AsyncConnection, config: Any) -> ConvergenceEngine:
        """Build from a ``SwarmRunConfig`` (carries ``t_initial`` / ``delta_t``)."""
        return cls(db, t_initial=config.t_initial, delta_t=config.delta_t)

    # ── confidence ────────────────────────────────────────────────────────────

    async def compute_cold_start_confidence(
        self,
        *,
        run_id: str,
        thread_id: str,
    ) -> dict[str, float]:
        """``confidence_0`` from the vote sub-round (PRD §6.4).

        ``confidence_0[agent] = votes_received / (N_thread_participants - 1)``,
        where votes are the cold-start votes on the agent's round-1 proposal and
        participants are the distinct authors of round-1 proposals in the thread.
        Self-votes are excluded to match the ``(N - 1)`` denominator.
        """
        participants = await self._round1_authors(run_id=run_id, thread_id=thread_id)
        if not participants:
            return {}

        rows = (
            (
                await self._db.execute(
                    text(
                        """
                        SELECT de.author_id AS author_id, COUNT(*) AS cnt
                        FROM votes v
                        JOIN draft_entries de ON de.id = v.voted_entry_id
                        WHERE v.run_id = :run_id
                          AND de.thread_id = :thread_id
                          AND de.round = 1
                          AND v.voter_agent_id <> de.author_id
                        GROUP BY de.author_id
                        """
                    ),
                    {"run_id": run_id, "thread_id": thread_id},
                )
            )
            .mappings()
            .fetchall()
        )
        votes_by_author = {r["author_id"]: int(r["cnt"]) for r in rows}

        denom = max(1, len(participants) - 1)
        return {author: min(1.0, votes_by_author.get(author, 0) / denom) for author in participants}

    async def compute_confidence(
        self,
        *,
        run_id: str,
        thread_id: str,
        round: int,
    ) -> dict[str, float]:
        """Per-round confidence from citation share (PRD §6.4, R >= 2).

        ``confidence[agent] = citations_for_agent / max(1, total_citations)``,
        over the citations cast *this round* on entries in *this thread*.
        Every thread participant is included; those uncited this round score 0.0.
        """
        participants = await self._thread_authors(run_id=run_id, thread_id=thread_id)
        if not participants:
            return {}

        rows = (
            (
                await self._db.execute(
                    text(
                        """
                        SELECT de.author_id AS author_id, COUNT(*) AS cnt
                        FROM citations c
                        JOIN draft_entries de ON de.id = c.cited_entry_id
                        WHERE c.run_id = :run_id
                          AND c.round = :round
                          AND de.thread_id = :thread_id
                          AND c.citing_agent_id <> de.author_id
                        GROUP BY de.author_id
                        """
                    ),
                    {"run_id": run_id, "thread_id": thread_id, "round": round},
                )
            )
            .mappings()
            .fetchall()
        )
        cites_by_author = {r["author_id"]: int(r["cnt"]) for r in rows}
        total = sum(cites_by_author.values())
        denom = max(1, total)
        return {author: cites_by_author.get(author, 0) / denom for author in participants}

    # ── conceding temperature ───────────────────────────────────────────────────

    def temperature_floor(self, round: int) -> float:
        """``T_floor(R) = T_initial + (R - 1) * delta_T`` (PRD §6.4)."""
        return self.t_initial + (round - 1) * self.delta_t

    def conceding_temperature(self, *, confidence: float, round: int) -> float:
        """``T = max(1 - confidence, T_floor(R))``, clamped to ``[0, t_max]``."""
        t = max(1.0 - confidence, self.temperature_floor(round))
        return max(0.0, min(t, self.t_max))

    def temperatures_for_round(
        self,
        *,
        confidences: dict[str, float],
        round: int,
    ) -> dict[str, float]:
        """Conceding temperature for each agent given their confidence."""
        return {
            agent: self.conceding_temperature(confidence=conf, round=round)
            for agent, conf in confidences.items()
        }

    @staticmethod
    def temperature_instruction(temperature: float) -> str:
        """Natural-language instruction for a temperature band (PRD §6.4)."""
        for upper, instruction in _TEMPERATURE_BANDS:
            if temperature < upper:
                return instruction
        return _TEMPERATURE_BANDS[-1][1]

    # ── per-run reputation ──────────────────────────────────────────────────────

    async def update_reputation(
        self,
        *,
        run_id: str,
        current_round: int,
        domain: str,
        promoted_draft_ids: set[str] | None = None,
        deleted_draft_ids: set[str] | None = None,
    ) -> dict[str, float]:
        """Update per-run reputation at end of a round (PRD §6.4).

        +``delta_confirm`` for the author of each entry promoted to Confirmed this
        round; -``delta_reject`` for the author of each soft-deleted entry. Scores
        are clamped to ``[0, 1]`` and persisted to the ``reputation`` table.

        ``promoted_draft_ids`` defaults to the entries confirmed this round
        (``round_confirmed == current_round``). ``deleted_draft_ids`` must be
        supplied by the caller — the blackboard's soft-delete records a timestamp,
        not a round, so the orchestrator passes the IDs it just deleted. Returns
        the new score for every agent whose reputation changed.
        """
        if promoted_draft_ids is None:
            promoted_draft_ids = await self._confirmed_draft_ids_for_round(
                run_id=run_id, round=current_round
            )
        deleted_draft_ids = deleted_draft_ids or set()

        # Net reputation delta per author this round.
        deltas: dict[str, float] = {}
        for draft_id in promoted_draft_ids:
            author = await self._author_of(draft_id)
            if author is not None:
                deltas[author] = deltas.get(author, 0.0) + self.delta_confirm
        for draft_id in deleted_draft_ids:
            author = await self._author_of(draft_id)
            if author is not None:
                deltas[author] = deltas.get(author, 0.0) - self.delta_reject

        updated: dict[str, float] = {}
        for agent_id, delta in deltas.items():
            if delta == 0.0:
                continue
            new_score = await self._apply_reputation_delta(
                run_id=run_id, agent_id=agent_id, domain=domain, delta=delta
            )
            updated[agent_id] = new_score

        if updated:
            await self._db.commit()
        return updated

    # ── helpers ──────────────────────────────────────────────────────────────────

    async def _round1_authors(self, *, run_id: str, thread_id: str) -> list[str]:
        rows = (
            await self._db.execute(
                text(
                    "SELECT DISTINCT author_id FROM draft_entries "
                    "WHERE run_id = :run_id AND thread_id = :thread_id AND round = 1"
                ),
                {"run_id": run_id, "thread_id": thread_id},
            )
        ).fetchall()
        return [r[0] for r in rows]

    async def _thread_authors(self, *, run_id: str, thread_id: str) -> list[str]:
        rows = (
            await self._db.execute(
                text(
                    "SELECT DISTINCT author_id FROM draft_entries "
                    "WHERE run_id = :run_id AND thread_id = :thread_id"
                ),
                {"run_id": run_id, "thread_id": thread_id},
            )
        ).fetchall()
        return [r[0] for r in rows]

    async def _confirmed_draft_ids_for_round(self, *, run_id: str, round: int) -> set[str]:
        rows = (
            await self._db.execute(
                text(
                    "SELECT source_draft_id FROM confirmed_entries "
                    "WHERE run_id = :run_id AND round_confirmed = :round "
                    "AND source_draft_id IS NOT NULL"
                ),
                {"run_id": run_id, "round": round},
            )
        ).fetchall()
        return {r[0] for r in rows}

    async def _author_of(self, draft_id: str) -> str | None:
        row = (
            await self._db.execute(
                text("SELECT author_id FROM draft_entries WHERE id = :id"),
                {"id": draft_id},
            )
        ).fetchone()
        return row[0] if row is not None else None

    async def _apply_reputation_delta(
        self,
        *,
        run_id: str,
        agent_id: str,
        domain: str,
        delta: float,
    ) -> float:
        """Read-modify-write a clamped reputation score (portable; no upsert)."""
        row = (
            await self._db.execute(
                text(
                    "SELECT score FROM reputation "
                    "WHERE run_id = :run_id AND agent_id = :agent_id AND domain = :domain"
                ),
                {"run_id": run_id, "agent_id": agent_id, "domain": domain},
            )
        ).fetchone()
        current = float(row[0]) if row is not None else DEFAULT_REPUTATION
        new_score = max(0.0, min(1.0, current + delta))

        if row is not None:
            await self._db.execute(
                text(
                    "UPDATE reputation SET score = :score, updated_at = CURRENT_TIMESTAMP "
                    "WHERE run_id = :run_id AND agent_id = :agent_id AND domain = :domain"
                ),
                {"score": new_score, "run_id": run_id, "agent_id": agent_id, "domain": domain},
            )
        else:
            await self._db.execute(
                text(
                    "INSERT INTO reputation (run_id, agent_id, domain, score) "
                    "VALUES (:run_id, :agent_id, :domain, :score)"
                ),
                {"run_id": run_id, "agent_id": agent_id, "domain": domain, "score": new_score},
            )
        return new_score
