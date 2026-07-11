"""Persistence for a taker's voluntary stand-down ('nothing more to add').

A stand-down is recorded once per (run, agent, thread). The orchestrator loads
the set at the start of each discussion round to skip agents that have opted
out of a thread, and the quiescence terminator uses the resulting silence to
end the run once everyone has stopped.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def record_stand_down(
    db: AsyncConnection,
    *,
    run_id: str,
    agent_id: str,
    thread_id: str,
    round: int,
    reason: str,
) -> None:
    """Record (idempotently) that ``agent_id`` has nothing more to add on ``thread_id``."""
    # ON CONFLICT keeps the first stand-down; a repeat call is a no-op. SQLite and
    # Postgres both support this ON CONFLICT form against the unique constraint.
    await db.execute(
        text(
            "INSERT INTO swarm_stand_downs (run_id, agent_id, thread_id, round, reason) "
            "VALUES (:run_id, :agent_id, :thread_id, :round, :reason) "
            "ON CONFLICT (run_id, agent_id, thread_id) DO NOTHING"
        ),
        {
            "run_id": run_id,
            "agent_id": agent_id,
            "thread_id": thread_id,
            "round": round,
            "reason": reason,
        },
    )


async def load_stood_down(db: AsyncConnection, run_id: str) -> dict[str, set[str]]:
    """Return ``{thread_id: {agent_id, ...}}`` of everyone stood down in this run."""
    rows = (
        await db.execute(
            text("SELECT thread_id, agent_id FROM swarm_stand_downs WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
    ).fetchall()
    out: dict[str, set[str]] = defaultdict(set)
    for thread_id, agent_id in rows:
        out[str(thread_id)].add(str(agent_id))
    return dict(out)
