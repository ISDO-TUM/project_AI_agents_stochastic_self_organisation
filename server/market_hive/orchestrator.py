"""Swarm orchestrator — the ECSAS run loop (PRD §11.2).

``run_swarm`` is the single agent driver: it creates a run, asks a
``ContractSource`` for the contract + threads, runs the auction, drives the
discussion rounds, and finalizes. Every component it depends on that is not yet
built (Market Maker, Trust registry) or is intentionally minimal (Termination) is
reached through a narrow seam with a default implementation, so the real
component drops in without touching this file.

The engines (blackboard, auction, convergence, amendment) are passive: they own
DB writes and self-commit. The orchestrator only sequences them and turns each
action into a ``SimulationStep`` for the SSE stream.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import deserialise_agent_row
from server.db.tables import agents as agents_table
from server.guardrails import build_guarded_system_prompt
from server.llm import call_agent
from server.market_hive.auction import AuctionEngine, Invitation
from server.market_hive.blackboard import Blackboard
from server.market_hive.contract_source import FallbackContractSource
from server.market_hive.convergence import ConvergenceEngine
from server.market_hive.prompts import (
    AUCTION_SYSTEM_SUFFIX,
    VOTE_SYSTEM_SUFFIX,
    auction_user_prompt,
    round_one_system_suffix,
    round_one_user_prompt,
    rounds_system_suffix,
    rounds_user_prompt,
    vote_user_prompt,
)
from server.market_hive.schemas import (
    ContractSchema,
    SimulationStep,
    SwarmRunConfig,
    ThreadSchema,
)
from server.market_hive.termination import MaxRoundsTerminator
from server.market_hive.trust import NoopTrustRegistry
from server.schemas import ToolCall

logger = logging.getLogger(__name__)

_MSG_EXCERPT_LEN = 120

# ── Seams ────────────────────────────────────────────────────────────────────
# Structural (Protocol) interfaces so defaults can be swapped for the real
# components with no orchestrator change. Implementations need not inherit these.


class ContractSource(Protocol):
    """Turns a raw prompt into a persisted contract + threads (the MM's job)."""

    async def make_contract(
        self, prompt: str, run_id: str, db: AsyncConnection
    ) -> tuple[ContractSchema, list[ThreadSchema]]: ...


class Terminator(Protocol):
    """Decides when the round loop stops and formats the final output."""

    async def should_terminate(
        self, *, run_id: str, round: int, config: SwarmRunConfig, db: AsyncConnection
    ) -> bool: ...

    async def format_output(
        self, *, run_id: str, round: int, reason: str, db: AsyncConnection
    ) -> Any: ...


class TrustRegistry(Protocol):
    """Applies cross-run trust changes once, at run end."""

    async def update(
        self, *, run_id: str, takers: list[str], observers: list[str], db: AsyncConnection
    ) -> None: ...


class AgentRunner(Protocol):
    """Runs one LLM turn for an agent and returns its text + tool calls.

    Injectable so the round logic can be driven by deterministic fakes in tests
    without any LLM call. The default is ``_default_agent_runner``.
    """

    async def __call__(
        self,
        agent: dict[str, Any],
        *,
        user_prompt: str,
        system_suffix: str,
        tool_names: list[str],
        tool_context: dict[str, Any],
    ) -> tuple[str, list[ToolCall]]: ...


class AmendmentProcessor(Protocol):
    """Resolves pending contract amendments at end-of-round, yielding steps.

    Optional: defaults to ``None`` (no amendment processing) because the real
    resolver votes with the Market Maker, which is not built yet. When it lands,
    pass a processor here and add ``request_expertise`` to the round tools — no
    change to the round loop itself.
    """

    def process(
        self, *, run_id: str, current_round: int, takers: list[str], db: AsyncConnection
    ) -> AsyncIterator[SimulationStep]: ...


async def _default_agent_runner(
    agent: dict[str, Any],
    *,
    user_prompt: str,
    system_suffix: str,
    tool_names: list[str],
    tool_context: dict[str, Any],
) -> tuple[str, list[ToolCall]]:
    """Drive one real LLM turn, guardrail-wrapped. Errors → no action (NFR-REL-01)."""
    system_prompt = build_guarded_system_prompt(f"{agent['system_prompt']}\n\n{system_suffix}")
    try:
        response, tools_used = await call_agent(
            user_prompt,
            provider=agent["provider"],
            model=agent["model"],
            system_prompt=system_prompt,
            tool_names=tool_names,
            tool_context=tool_context,
        )
        return response, tools_used
    except Exception:
        logger.exception(
            "Agent turn failed for agent_id=%s; treating as no action", agent.get("id")
        )
        return "", []


# ── Step helper ──────────────────────────────────────────────────────────────


def _step(
    step_type: str,
    msg: str,
    *,
    node_id: str | None = None,
    thread_id: str | None = None,
    entry_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> SimulationStep:
    return SimulationStep(
        type=step_type,
        msg=msg,
        node_id=node_id,
        thread_id=thread_id,
        entry_id=entry_id,
        data=data,
    )


# ── Run lifecycle helpers ────────────────────────────────────────────────────


async def _create_run(db: AsyncConnection, run_id: str) -> None:
    await db.execute(
        text("INSERT INTO swarm_runs (id, status, mode) VALUES (:id, 'running', 'swarm')"),
        {"id": run_id},
    )
    await db.commit()


async def _complete_run(
    db: AsyncConnection, run_id: str, *, status: str, reason: str | None, round: int
) -> None:
    await db.execute(
        text(
            "UPDATE swarm_runs "
            "SET status = :status, termination_reason = :reason, "
            "    termination_round = :round, completed_at = :now "
            "WHERE id = :id"
        ),
        {
            "id": run_id,
            "status": status,
            "reason": reason,
            "round": round,
            "now": datetime.now(UTC),
        },
    )
    await db.commit()


async def _post_anchors(
    bb: Blackboard, run_id: str, contract: ContractSchema, threads: list[ThreadSchema]
) -> None:
    """Seed the Confirmed layer with the permanent contract + thread anchors."""
    await bb.post_anchor(
        run_id=run_id,
        thread_id=threads[0].id,
        content=f"[ANCHOR] Contract: {contract.original_prompt}",
    )
    for thread in threads:
        await bb.post_anchor(
            run_id=run_id,
            thread_id=thread.id,
            content=f"[ANCHOR] Thread: {thread.title} — {thread.description}",
        )


async def _load_agents(db: AsyncConnection) -> dict[str, dict[str, Any]]:
    """Return ``{agent_id: agent_dict}`` for every agent in the DB."""
    rows = (await db.execute(select(agents_table))).mappings().all()
    return {row["id"]: deserialise_agent_row(row) for row in rows}


def _excerpt(value: str) -> str:
    value = value.strip().replace("\n", " ")
    return value if len(value) <= _MSG_EXCERPT_LEN else value[:_MSG_EXCERPT_LEN] + "…"


def _parse_entry_id(tool_output: str) -> str | None:
    """Extract ``entry_id`` from a post_to_blackboard tool result, if present."""
    try:
        entry_id = json.loads(tool_output).get("entry_id")
    except (json.JSONDecodeError, AttributeError, TypeError):
        return None
    return entry_id if isinstance(entry_id, str) else None


def _tool_events(agent: dict[str, Any], tools_used: list[ToolCall]) -> list[SimulationStep]:
    """Map blackboard tool calls (post/cite/vote/request_expertise) to steps.

    Shared by the proposal, vote, and discussion rounds.
    """
    steps: list[SimulationStep] = []
    for call in tools_used:
        if call.name == "post_to_blackboard":
            entry_type = str(call.input.get("entry_type", "post"))
            thread_id = call.input.get("thread_id")
            entry_id = _parse_entry_id(call.output)
            steps.append(
                _step(
                    "bb-post",
                    f"{agent['name']} posted a {entry_type}",
                    node_id=agent["id"],
                    thread_id=thread_id,
                    entry_id=entry_id,
                )
            )
            for mentioned in call.input.get("mention_agents") or []:
                steps.append(
                    _step(
                        "bb-mention",
                        f"{agent['name']} mentioned an agent",
                        node_id=str(mentioned),
                        entry_id=entry_id,
                    )
                )
        elif call.name == "cite":
            steps.append(_step("bb-cite", f"{agent['name']} cited entries", node_id=agent["id"]))
        elif call.name == "vote":
            steps.append(
                _step("bb-vote", f"{agent['name']} voted on a proposal", node_id=agent["id"])
            )
        elif call.name == "request_expertise":
            domain = str(call.input.get("domain", ""))
            steps.append(
                _step(
                    "amendment",
                    f"{agent['name']} requested '{domain}' expertise",
                    node_id=agent["id"],
                )
            )
    return steps


def _fmt_scores(scores: dict[str, float], agents_by_id: dict[str, dict[str, Any]]) -> str:
    """Render ``{agent_id: score}`` as ``Alpha=0.50, Beta=0.00`` for a system step."""
    return ", ".join(
        f"{agents_by_id.get(aid, {}).get('name', aid[:8])}={score:.2f}"
        for aid, score in scores.items()
    )


# ── Auction (M1) ─────────────────────────────────────────────────────────────


def _auction_events(
    invitation: Invitation, agent: dict[str, Any], tools_used: list[ToolCall]
) -> list[SimulationStep]:
    """Map an agent's auction tool calls to bid/abstain steps."""
    steps: list[SimulationStep] = []
    for call in tools_used:
        if call.name == "submit_bid":
            justification = str(call.input.get("justification", ""))
            steps.append(
                _step(
                    "bid",
                    f"{agent['name']} submitted bid: '{_excerpt(justification)}'",
                    node_id=invitation.agent_id,
                )
            )
        elif call.name == "abstain":
            reason = str(call.input.get("reason", ""))
            steps.append(
                _step(
                    "abstain",
                    f"{agent['name']} abstained: '{_excerpt(reason)}'",
                    node_id=invitation.agent_id,
                )
            )
    return steps


async def _run_auction(
    db: AsyncConnection,
    auction: AuctionEngine,
    run_id: str,
    contract: ContractSchema,
    agents_by_id: dict[str, dict[str, Any]],
    agent_runner: AgentRunner,
) -> AsyncIterator[SimulationStep]:
    """Invite agents, drive self-selection, and select takers (PRD §6.2)."""
    invitations = await auction.invite(run_id=run_id, contract_id=contract.id)
    yield _step("system", f"Auction open. {len(invitations)} agent(s) invited.")

    for invitation in invitations:
        agent = agents_by_id.get(invitation.agent_id)
        if agent is None:
            continue
        _text, tools_used = await agent_runner(
            agent,
            user_prompt=auction_user_prompt(contract, invitation),
            system_suffix=AUCTION_SYSTEM_SUFFIX,
            tool_names=["read_blackboard", "submit_bid", "abstain"],
            tool_context={
                "db": db,
                "run_id": run_id,
                "agent_id": invitation.agent_id,
                "contract_id": contract.id,
                "preliminary_score": invitation.preliminary_score,
            },
        )
        for step in _auction_events(invitation, agent, tools_used):
            yield step

    selection = await auction.select_takers(run_id=run_id, contract_id=contract.id)
    if selection.aborted:
        yield _step("system", selection.reason or "No agents qualified. Run aborted.")
        return
    taker_names = [agents_by_id[a]["name"] for a in selection.takers if a in agents_by_id]
    yield _step("system", f"Takers selected: {', '.join(taker_names)}")


# ── Round 1 + vote sub-round (M2) ────────────────────────────────────────────

# In v1 every taker works the single fallback thread. When the Market Maker
# produces multiple threads, per-thread taker assignment replaces this mapping.
_ROUND1_TOOLS = ["read_blackboard", "get_confirmed", "post_to_blackboard"]
_VOTE_TOOLS = ["read_blackboard", "vote"]


async def _round1_proposals(
    db: AsyncConnection, run_id: str, thread_id: str
) -> list[tuple[str, str, str]]:
    """Return ``(entry_id, author_name, content)`` for round-1 proposals in a thread."""
    rows = (
        (
            await db.execute(
                text(
                    """
                    SELECT de.id AS id,
                           COALESCE(a.name, de.author_id) AS name,
                           de.content AS content
                    FROM draft_entries de
                    LEFT JOIN agents a ON a.id = de.author_id
                    WHERE de.run_id = :run_id AND de.thread_id = :thread_id
                      AND de.round = 1 AND de.entry_type = 'proposal'
                    ORDER BY de.created_at
                    """
                ),
                {"run_id": run_id, "thread_id": thread_id},
            )
        )
        .mappings()
        .all()
    )
    return [(r["id"], r["name"], r["content"]) for r in rows]


async def _run_round_one(
    db: AsyncConnection,
    run_id: str,
    contract: ContractSchema,
    threads: list[ThreadSchema],
    takers: list[str],
    agents_by_id: dict[str, dict[str, Any]],
    agent_runner: AgentRunner,
    config: SwarmRunConfig,
) -> AsyncIterator[SimulationStep]:
    """Every taker posts one opening proposal per thread (PRD §9.3)."""
    yield _step("system", "Round 1 begins. Opening proposals.")
    # Round 1 runs at a neutral temperature (no confidence signal exists yet).
    instruction = ConvergenceEngine.temperature_instruction(0.5)
    suffix = round_one_system_suffix(instruction)

    for thread in threads:
        coworkers = [agents_by_id[t]["name"] for t in takers if t in agents_by_id]
        for taker in takers:
            agent = agents_by_id.get(taker)
            if agent is None:
                continue
            _text, tools_used = await agent_runner(
                agent,
                user_prompt=round_one_user_prompt(
                    contract, thread, max_rounds=config.max_rounds, coworkers=coworkers
                ),
                system_suffix=suffix,
                tool_names=_ROUND1_TOOLS,
                tool_context={
                    "db": db,
                    "run_id": run_id,
                    "agent_id": taker,
                    "thread_id": thread.id,
                    "round": 1,
                },
            )
            for step in _tool_events(agent, tools_used):
                yield step


async def _run_vote_subround(
    db: AsyncConnection,
    run_id: str,
    threads: list[ThreadSchema],
    takers: list[str],
    agents_by_id: dict[str, dict[str, Any]],
    agent_runner: AgentRunner,
) -> AsyncIterator[SimulationStep]:
    """Each taker votes on the round-1 proposals it endorses (PRD §9.4)."""
    yield _step("system", "Vote sub-round. Agents review Round 1 proposals.")
    for thread in threads:
        proposals = await _round1_proposals(db, run_id, thread.id)
        for taker in takers:
            agent = agents_by_id.get(taker)
            if agent is None:
                continue
            _text, tools_used = await agent_runner(
                agent,
                user_prompt=vote_user_prompt(thread, proposals),
                system_suffix=VOTE_SYSTEM_SUFFIX,
                tool_names=_VOTE_TOOLS,
                tool_context={
                    "db": db,
                    "run_id": run_id,
                    "agent_id": taker,
                    "thread_id": thread.id,
                    "round": 1,
                },
            )
            for step in _tool_events(agent, tools_used):
                yield step


async def _cold_start_temperatures(
    db: AsyncConnection,
    run_id: str,
    threads: list[ThreadSchema],
    takers: list[str],
    convergence: ConvergenceEngine,
) -> tuple[dict[str, float], dict[str, float]]:
    """Compute cold-start confidence and the round-2 conceding temperatures."""
    confidences: dict[str, float] = {}
    for thread in threads:
        confidences.update(
            await convergence.compute_cold_start_confidence(run_id=run_id, thread_id=thread.id)
        )
    confidences = {taker: confidences.get(taker, 0.0) for taker in takers}
    temperatures = convergence.temperatures_for_round(confidences=confidences, round=1)
    return confidences, temperatures


# ── Discussion rounds + end-of-round (M3) ────────────────────────────────────

_ROUNDS_TOOLS = ["read_blackboard", "get_confirmed", "post_to_blackboard", "cite"]


async def _run_discussion_round(
    db: AsyncConnection,
    run_id: str,
    contract: ContractSchema,
    threads: list[ThreadSchema],
    takers: list[str],
    temperatures: dict[str, float],
    round: int,
    agents_by_id: dict[str, dict[str, Any]],
    agent_runner: AgentRunner,
    config: SwarmRunConfig,
) -> AsyncIterator[SimulationStep]:
    """One discussion round: each taker reads, replies, and cites (PRD §9.5)."""
    yield _step("system", f"Round {round} begins.")
    for thread in threads:
        for taker in takers:
            agent = agents_by_id.get(taker)
            if agent is None:
                continue
            instruction = ConvergenceEngine.temperature_instruction(temperatures.get(taker, 1.0))
            _text, tools_used = await agent_runner(
                agent,
                user_prompt=rounds_user_prompt(
                    contract, thread, round=round, max_rounds=config.max_rounds
                ),
                system_suffix=rounds_system_suffix(instruction),
                tool_names=_ROUNDS_TOOLS,
                tool_context={
                    "db": db,
                    "run_id": run_id,
                    "agent_id": taker,
                    "thread_id": thread.id,
                    "round": round,
                },
            )
            for step in _tool_events(agent, tools_used):
                yield step


async def _visible_entry_ids(db: AsyncConnection, run_id: str) -> set[str]:
    rows = (
        await db.execute(
            text("SELECT id FROM draft_entries WHERE run_id = :run_id AND is_visible = true"),
            {"run_id": run_id},
        )
    ).fetchall()
    return {row[0] for row in rows}


async def _end_of_round(
    db: AsyncConnection,
    run_id: str,
    threads: list[ThreadSchema],
    takers: list[str],
    round: int,
    convergence: ConvergenceEngine,
    domain: str,
    config: SwarmRunConfig,
) -> AsyncIterator[SimulationStep]:
    """Promote, soft-delete, and update reputation at the end of a round (§11.2)."""
    bb = Blackboard(db)
    participants_by_thread = {thread.id: len(takers) for thread in threads}

    promoted = await bb.check_promotions(
        run_id=run_id, current_round=round, participants_by_thread=participants_by_thread
    )
    for entry in promoted:
        yield _step(
            "bb-promote",
            f"Entry promoted to Confirmed ({entry.citation_count} citations).",
            thread_id=entry.thread_id,
            entry_id=entry.source_draft_id,
        )

    # soft_delete_stale returns only a count, so diff the visible set to recover IDs.
    before = await _visible_entry_ids(db, run_id)
    await bb.soft_delete_stale(run_id=run_id, current_round=round, decay_rounds=config.decay_rounds)
    deleted_ids = before - await _visible_entry_ids(db, run_id)
    for entry_id in deleted_ids:
        yield _step("bb-delete", "Entry soft-deleted (stale).", entry_id=entry_id)

    await convergence.update_reputation(
        run_id=run_id,
        current_round=round,
        domain=domain,
        promoted_draft_ids={e.source_draft_id for e in promoted if e.source_draft_id},
        deleted_draft_ids=deleted_ids,
    )


async def _next_temperatures(
    db: AsyncConnection,
    run_id: str,
    threads: list[ThreadSchema],
    takers: list[str],
    round: int,
    convergence: ConvergenceEngine,
) -> dict[str, float]:
    """Recompute conceding temperatures from this round's citation share."""
    confidences: dict[str, float] = {}
    for thread in threads:
        confidences.update(
            await convergence.compute_confidence(run_id=run_id, thread_id=thread.id, round=round)
        )
    confidences = {taker: confidences.get(taker, 0.0) for taker in takers}
    temperatures: dict[str, float] = convergence.temperatures_for_round(
        confidences=confidences, round=round
    )
    return temperatures


# ── Orchestrator ─────────────────────────────────────────────────────────────


async def run_swarm(
    config: SwarmRunConfig,
    db: AsyncConnection,
    *,
    contract_source: ContractSource | None = None,
    terminator: Terminator | None = None,
    trust: TrustRegistry | None = None,
    agent_runner: AgentRunner | None = None,
    amendment_processor: AmendmentProcessor | None = None,
) -> AsyncIterator[SimulationStep]:
    """Drive one swarm run end-to-end, yielding ``SimulationStep`` events.

    Seam defaults are the v1 placeholders; pass real components to override.
    """
    contract_source = contract_source or FallbackContractSource()
    terminator = terminator or MaxRoundsTerminator()
    trust = trust or NoopTrustRegistry()
    agent_runner = agent_runner or _default_agent_runner

    run_id = str(uuid.uuid4())
    await _create_run(db, run_id)
    bb = Blackboard(db)
    agents_by_id = await _load_agents(db)

    # ── Contract + anchors (Market Maker seam) ───────────────────────────────
    contract, threads = await contract_source.make_contract(config.prompt, run_id, db)
    await _post_anchors(bb, run_id, contract, threads)
    yield _step(
        "system",
        f"Contract created: {contract.task_type}, {contract.task_nature}, "
        f"confidence={contract.confidence:.2f}",
        data={"run_id": run_id, "contract_id": contract.id},
    )
    yield _step(
        "system",
        f"Threads created: {', '.join(t.title for t in threads)}",
        data={"thread_ids": [t.id for t in threads]},
    )

    # ── Auction (Market Hive §6.2) ───────────────────────────────────────────
    auction = AuctionEngine.from_config(db, config)
    async for step in _run_auction(db, auction, run_id, contract, agents_by_id, agent_runner):
        yield step

    takers = await auction.get_takers(run_id=run_id)
    if not takers:
        await _complete_run(db, run_id, status="aborted", reason="no_takers", round=0)
        return

    # ── Round 1 — opening proposals (§9.3) ───────────────────────────────────
    convergence = ConvergenceEngine.from_config(db, config)
    async for step in _run_round_one(
        db, run_id, contract, threads, takers, agents_by_id, agent_runner, config
    ):
        yield step

    # ── Vote sub-round → cold-start confidence/temperature (§9.4, §6.4) ───────
    async for step in _run_vote_subround(db, run_id, threads, takers, agents_by_id, agent_runner):
        yield step
    confidences, temperatures = await _cold_start_temperatures(
        db, run_id, threads, takers, convergence
    )
    yield _step("system", f"Cold-start confidence: {_fmt_scores(confidences, agents_by_id)}")
    yield _step("system", f"Round 2 temperatures: {_fmt_scores(temperatures, agents_by_id)}")

    # ── Discussion rounds 2..max_rounds (§9.5, §11.2) ────────────────────────
    termination_reason = "max_rounds"
    last_round = 1
    for round in range(2, config.max_rounds + 1):
        last_round = round
        async for step in _run_discussion_round(
            db,
            run_id,
            contract,
            threads,
            takers,
            temperatures,
            round,
            agents_by_id,
            agent_runner,
            config,
        ):
            yield step

        async for step in _end_of_round(
            db, run_id, threads, takers, round, convergence, contract.task_type, config
        ):
            yield step

        temperatures = await _next_temperatures(db, run_id, threads, takers, round, convergence)

        if amendment_processor is not None:
            async for step in amendment_processor.process(
                run_id=run_id, current_round=round, takers=takers, db=db
            ):
                yield step

        if await terminator.should_terminate(run_id=run_id, round=round, config=config, db=db):
            termination_reason = "equilibrium"
            break

    # ── Finalize: select the answer, update trust, emit the result (§6.6, §6.7) ─
    output = await terminator.format_output(
        run_id=run_id, round=last_round, reason=termination_reason, db=db
    )
    observers = await auction.get_observers(run_id=run_id)
    await trust.update(run_id=run_id, takers=takers, observers=observers, db=db)
    await _complete_run(db, run_id, status="completed", reason=termination_reason, round=last_round)
    yield _step(
        "convergence",
        f"Run complete ({termination_reason}, round {last_round}).",
        data=output.model_dump(mode="json"),
    )
