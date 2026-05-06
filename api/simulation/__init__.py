"""Topology-aware simulation engine.

Execution model
───────────────
Broadcast phase
    Every agent receives the original prompt and responds independently
    and in parallel.

Discussion phase (repeated `rounds` times)
    For each agent that has at least one *incoming* edge (i.e. another agent
    has it in their ``connections`` list), we build a context message from
    those senders' most-recent responses and ask the receiving agent to reply.
    Agents without incoming edges are silent during discussion rounds.

An agent that fails during any phase has its error recorded as its response
for that round; subsequent rounds will include the error text as context so
other agents remain aware of the failure.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

import aiosqlite

from api.db import deserialise_agent_row
from api.llm import call_agent
from api.schemas import SimulationStep

# ── helpers ───────────────────────────────────────────────────────────────────


def _ts() -> str:
    d = datetime.now()
    return f"{d.hour:02d}:{d.minute:02d}:{d.second:02d}"


def _step(**kwargs: Any) -> SimulationStep:
    return SimulationStep(id=str(uuid.uuid4()), ts=_ts(), **kwargs)


async def _call_agent(agent: dict[str, Any], prompt: str, db: aiosqlite.Connection) -> str:
    """Invoke an agent and return its text response."""
    response, _ = await call_agent(
        prompt,
        provider=agent["provider"],
        model=agent["model"],
        system_prompt=agent["system_prompt"] or None,
        tool_names=agent["tools"] or None,
        tool_context={"db": db, "agent_id": agent["id"]},
    )
    return str(response)


# ── public interface ──────────────────────────────────────────────────────────


async def run_topology(
    prompt: str,
    db: aiosqlite.Connection,
    rounds: int = 1,
) -> list[SimulationStep]:
    """Run a full topology simulation and return the ordered step log.

    Args:
        prompt: The user prompt broadcast to all agents.
        db:     The active database connection (agents and their connections
                are loaded from here).
        rounds: Number of discussion rounds after the broadcast phase.

    Returns:
        A flat, ordered list of :class:`SimulationStep` objects ready to be
        returned directly to the frontend.
    """
    async with db.execute("SELECT * FROM agents") as cur:
        rows = await cur.fetchall()
    agents: list[dict[str, Any]] = [deserialise_agent_row(row) for row in rows]

    if not agents:
        return []

    agent_by_id: dict[str, dict[str, Any]] = {a["id"]: a for a in agents}

    # incoming[agent_id] = list of agent IDs that have an edge pointing TO it
    incoming: dict[str, list[str]] = {a["id"]: [] for a in agents}
    for agent in agents:
        for target_id in agent["connections"]:
            if target_id in incoming:
                incoming[target_id].append(agent["id"])

    steps: list[SimulationStep] = []

    # ── Broadcast phase ───────────────────────────────────────────────────────

    steps.append(
        _step(
            label="SYSTEM",
            msg=f"Broadcasting to {len(agents)} agent{'s' if len(agents) != 1 else ''}…",
            type="system",
        )
    )

    async def _broadcast(agent: dict[str, Any]) -> tuple[str, SimulationStep]:
        try:
            response = await _call_agent(agent, prompt, db)
        except Exception as exc:
            response = f"[error: {exc}]"
        return response, _step(
            label=agent["name"],
            msg=response,
            type="system",
            node_id=agent["id"],
        )

    broadcast_results = await asyncio.gather(*[_broadcast(a) for a in agents])

    # Preserve agent order (gather returns results in input order).
    responses: dict[str, str] = {}
    for agent, (response, step) in zip(agents, broadcast_results, strict=True):
        responses[agent["id"]] = response
        steps.append(step)

    # ── Discussion rounds ─────────────────────────────────────────────────────

    for round_num in range(1, rounds + 1):
        # Skip entirely if no edges exist in the topology.
        if not any(incoming.values()):
            break

        steps.append(
            _step(
                label="SYSTEM",
                msg=f"Discussion round {round_num} — agents exchange responses…",
                type="system",
            )
        )

        async def _discuss(
            agent: dict[str, Any],
        ) -> tuple[str | None, list[SimulationStep]]:
            senders = [sid for sid in incoming[agent["id"]] if sid in responses]
            if not senders:
                return None, []

            context_lines = [f"- {agent_by_id[sid]['name']}: {responses[sid]}" for sid in senders]
            discussion_prompt = (
                f"Original question: {prompt}\n\n"
                "Other agents responded:\n"
                + "\n".join(context_lines)
                + "\n\nConsidering these perspectives, what is your updated view?"
            )

            # One step per incoming edge — visualises the message flow on canvas.
            edge_steps = [
                _step(
                    label=agent_by_id[sid]["name"],
                    msg=responses[sid],
                    type="agent-to-agent",
                    target=agent["name"],
                    from_id=sid,
                    to_id=agent["id"],
                )
                for sid in senders
            ]

            try:
                response = await _call_agent(agent, discussion_prompt, db)
            except Exception as exc:
                response = f"[error: {exc}]"

            reply_step = _step(
                label=agent["name"],
                msg=response,
                type="system",
                node_id=agent["id"],
            )

            return response, [*edge_steps, reply_step]

        discuss_results = await asyncio.gather(*[_discuss(a) for a in agents])

        new_responses: dict[str, str] = {}
        for agent, (new_resp, new_steps) in zip(agents, discuss_results, strict=True):
            if new_resp is not None:
                new_responses[agent["id"]] = new_resp
                steps.extend(new_steps)
        responses.update(new_responses)

    steps.append(_step(label="SYSTEM", msg="Simulation complete.", type="system"))
    return steps
