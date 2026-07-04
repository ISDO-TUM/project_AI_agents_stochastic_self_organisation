"""Run journal — phase, heartbeat, and per-turn completion bookkeeping.

``run_swarm`` sequences a lot of async work across a potentially long wall-clock
run; a crash or redeploy mid-flight should not force the whole thing to restart
from scratch, and it should be visible from the DB alone that a run is (or was)
actually making progress. ``RunJournal`` centralizes the three kinds of writes
that give a run a recorded position:

* ``phase`` — which stage of the run loop it is in (and which round).
* ``heartbeat`` — a liveness timestamp so a crashed run can be told apart from
  a merely slow one (see ``server.db.reap_stale_runs``).
* ``turn`` — one agent's completion status for one (phase, round), so a resumed
  run can skip work that already happened instead of redoing it.

All writes self-commit, matching the engines' convention (``Blackboard``,
``AuctionEngine``, etc.) so the orchestrator never has to remember to commit
journal writes itself.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class RunJournal:
    """Records one run's phase/heartbeat/turn-completion state."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id

    async def phase(self, db: AsyncConnection, phase: str, round: int | None = None) -> None:
        """Record the run's current phase (and round, when applicable)."""
        await db.execute(
            text(
                "UPDATE swarm_runs SET phase = :phase, current_round = :round WHERE id = :id"
            ),
            {"phase": phase, "round": round, "id": self.run_id},
        )
        await db.commit()

    async def heartbeat(self, db: AsyncConnection) -> None:
        """Bump the liveness timestamp so a crashed run can be told apart from
        a merely slow one (see ``server.db.reap_stale_runs``)."""
        await db.execute(
            text("UPDATE swarm_runs SET heartbeat_at = :now WHERE id = :id"),
            {"now": datetime.now(UTC), "id": self.run_id},
        )
        await db.commit()

    async def turn(
        self, db: AsyncConnection, *, agent_id: str, phase: str, round: int, status: str
    ) -> None:
        """Record one agent's completion status for a (phase, round).

        Upserts on the UNIQUE(run_id, agent_id, phase, round) key rather than
        insert-or-ignore: a turn that fails once (recording ``failed``) and
        then succeeds on retry must end up ``done`` for that same tuple, not
        stuck at ``failed`` — the latest status for a tuple always wins within
        a run. Across a resume this is equally correct: ``completed_turns``
        is consulted *before* a turn is re-attempted, so a tuple already
        ``done``/``skipped`` is never re-run, and this method is simply never
        called for it again.
        """
        await db.execute(
            text(
                """
                INSERT INTO turn_log (id, run_id, agent_id, phase, round, status)
                VALUES (:id, :run_id, :agent_id, :phase, :round, :status)
                ON CONFLICT (run_id, agent_id, phase, round)
                DO UPDATE SET status = excluded.status
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "run_id": self.run_id,
                "agent_id": agent_id,
                "phase": phase,
                "round": round,
                "status": status,
            },
        )
        await db.commit()

    async def completed_turns(self, db: AsyncConnection, *, phase: str, round: int) -> set[str]:
        """Agent ids with a ``done`` or ``skipped`` row for this (phase, round).

        Used to make turn-building resume-safe: an agent already accounted for
        is not re-driven through another LLM call. ``failed`` rows are excluded
        deliberately — a failed turn has not completed and should be retried.
        """
        rows = (
            await db.execute(
                text(
                    """
                    SELECT agent_id FROM turn_log
                    WHERE run_id = :run_id AND phase = :phase AND round = :round
                      AND status IN ('done', 'skipped')
                    """
                ),
                {"run_id": self.run_id, "phase": phase, "round": round},
            )
        ).fetchall()
        return {row[0] for row in rows}
