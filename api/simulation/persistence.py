"""Persist a `ConsensusResult` (and its topology) into the trial / rounds tables.

The consensus layer stays pure (no DB knowledge). This adapter is the single
place that converts in-memory telemetry into rows.
"""

from __future__ import annotations

import uuid
from typing import Any

import aiosqlite

from api.simulation.topology import Topology
from api.simulation.types import ConsensusResult, Task


async def record_trial(
    db: aiosqlite.Connection,
    *,
    description: str,
    protocol_name: str,
    task: Task,
    topology: Topology,
    result: ConsensusResult,
) -> str:
    """Insert one trial + all its rounds, proposals, and round_edges. Returns trial_id."""
    trial_id = str(uuid.uuid4())

    await db.execute(
        """
        INSERT INTO trials (
            id, description, task_prompt, protocol_name,
            final_answer, stopped_reason, completed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            trial_id,
            description,
            task.prompt,
            protocol_name,
            result.answer,
            result.stopped_reason,
        ),
    )

    for round_state in result.rounds:
        cur = await db.execute(
            """
            INSERT INTO rounds (trial_id, round_index, aggregate, agreement)
            VALUES (?, ?, ?, ?)
            """,
            (
                trial_id,
                round_state.round_index,
                round_state.aggregate,
                round_state.agreement,
            ),
        )
        round_id = cur.lastrowid
        if round_id is None:
            raise RuntimeError("rounds INSERT did not produce a rowid")

        proposal_rows = [
            (round_id, aid, p.content, round_state.scores.get(aid, 0.0))
            for aid, p in round_state.proposals.items()
        ]
        if proposal_rows:
            await db.executemany(
                "INSERT INTO proposals (round_id, agent_id, content, score) VALUES (?, ?, ?, ?)",
                proposal_rows,
            )

        # Round 0 has no inbound messages — agents proposed from a blank context.
        # From round 1 onward, every agent saw their topology neighbors' last-round
        # proposals; record those edges as a snapshot of the topology at that round.
        if round_state.round_index > 0:
            edge_rows: list[tuple[int, str, str, float]] = []
            for to_agent in topology.nodes():
                for from_agent in topology.neighbors(to_agent):
                    edge_rows.append(
                        (round_id, from_agent, to_agent, topology.edge_weight(from_agent, to_agent))
                    )
            if edge_rows:
                await db.executemany(
                    """
                    INSERT INTO round_edges (round_id, from_agent_id, to_agent_id, weight)
                    VALUES (?, ?, ?, ?)
                    """,
                    edge_rows,
                )

    await db.commit()
    return trial_id


async def load_trial(db: aiosqlite.Connection, trial_id: str) -> dict[str, Any] | None:
    """Read one trial back as a nested dict ready for JSON serialisation."""
    async with db.execute("SELECT * FROM trials WHERE id = ?", (trial_id,)) as cur:
        trial_row = await cur.fetchone()
    if trial_row is None:
        return None

    async with db.execute(
        "SELECT * FROM rounds WHERE trial_id = ? ORDER BY round_index ASC",
        (trial_id,),
    ) as cur:
        round_rows = await cur.fetchall()

    rounds: list[dict[str, Any]] = []
    for round_row in round_rows:
        round_id = round_row["id"]
        async with db.execute(
            "SELECT agent_id, content, score FROM proposals WHERE round_id = ?",
            (round_id,),
        ) as p_cur:
            proposals = [dict(r) for r in await p_cur.fetchall()]
        async with db.execute(
            "SELECT from_agent_id, to_agent_id, weight FROM round_edges WHERE round_id = ?",
            (round_id,),
        ) as e_cur:
            edges = [dict(r) for r in await e_cur.fetchall()]
        rounds.append(
            {
                "round_index": round_row["round_index"],
                "aggregate": round_row["aggregate"],
                "agreement": round_row["agreement"],
                "created_at": round_row["created_at"],
                "proposals": proposals,
                "edges": edges,
            }
        )

    return {**dict(trial_row), "rounds": rounds}
