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

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, NamedTuple, Protocol

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import deserialise_agent_row, hint_files_in_prompt, load_agent_files
from server.db.tables import agents as agents_table
from server.guardrails import build_guarded_system_prompt
from server.llm import call_agent
from server.market_hive.auction import AuctionEngine, Invitation
from server.market_hive.blackboard import Blackboard, format_entries_digest
from server.market_hive.contract_source import FallbackContractSource
from server.market_hive.convergence import ConvergenceEngine
from server.market_hive.journal import RunJournal
from server.market_hive.prompts import (
    AUCTION_SYSTEM_SUFFIX,
    RATIFY_SYSTEM_SUFFIX,
    VOTE_SYSTEM_SUFFIX,
    auction_user_prompt,
    ratify_user_prompt,
    round_one_system_suffix,
    round_one_user_prompt,
    round_one_wave2_user_prompt,
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
from server.market_hive.synthesis import FallbackAnswerSynthesizer
from server.market_hive.termination import MaxRoundsTerminator, Synthesizer
from server.market_hive.trust import TrustRegistry as DefaultTrustRegistry
from server.schemas import ToolCall

logger = logging.getLogger(__name__)

_MSG_EXCERPT_LEN = 120

# Resilient runs: per-turn timeout, retry budget before giving up, and the
# number of *consecutive* failed phases before an agent is dropped entirely.
TURN_TIMEOUT_S = 120
K_DROPOUT = 2

# ── Seams ────────────────────────────────────────────────────────────────────
# Structural (Protocol) interfaces so defaults can be swapped for the real
# components with no orchestrator change. Implementations need not inherit these.


class ContractSource(Protocol):
    """Turns a raw prompt into a persisted contract + threads (the MM's job)."""

    async def make_contract(
        self, prompt: str, run_id: str, db: AsyncConnection
    ) -> tuple[ContractSchema, list[ThreadSchema]]:
        raise NotImplementedError


class Terminator(Protocol):
    """Decides when the round loop stops and formats the final output."""

    async def should_terminate(
        self,
        *,
        run_id: str,
        round: int,
        config: SwarmRunConfig,
        db: AsyncConnection,
        status_flips: int = 0,
    ) -> bool:
        raise NotImplementedError

    async def format_output(
        self,
        *,
        run_id: str,
        round: int,
        reason: str,
        db: AsyncConnection,
        prompt: str | None = None,
        synthesizer: Synthesizer | None = None,
    ) -> Any:
        raise NotImplementedError


class TrustRegistry(Protocol):
    """Applies cross-run trust changes once, at run end."""

    async def update(
        self, *, run_id: str, takers: list[str], observers: list[str], db: AsyncConnection
    ) -> None:
        raise NotImplementedError


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
    ) -> AsyncIterator[SimulationStep]:
        pass


async def _default_agent_runner(
    agent: dict[str, Any],
    *,
    user_prompt: str,
    system_suffix: str,
    tool_names: list[str],
    tool_context: dict[str, Any],
) -> tuple[str, list[ToolCall]]:
    """Drive one real LLM turn, guardrail-wrapped.

    Resilient runs: errors now PROPAGATE instead of being swallowed here — the
    "errors → no action" contract (NFR-REL-01) moved up one level, to
    ``_board_turn``'s timeout/retry wrapper, which retries once and only then
    treats the turn as a no-op (and journals it ``failed``). The transaction
    reset still happens unconditionally via ``finally`` so a failed write never
    poisons the next agent's turn on a shared connection.
    """
    db = tool_context.get("db")
    try:
        # Load this agent's knowledge files so it can consult them in any phase
        # (auction self-selection through the discussion rounds, PRD §9.1). The
        # ``files`` tool reads them from context; offer it whenever the agent has
        # files, and steer the system prompt toward them. The per-turn lookup is a
        # cheap SELECT next to the LLM call, and keeps file-wiring in one place.
        files: dict[str, str] = await load_agent_files(db, agent["id"]) if db is not None else {}
        effective_tools = list(tool_names)
        if files and "files" not in effective_tools:
            effective_tools.append("files")

        combined = f"{agent['system_prompt']}\n\n{system_suffix}"
        system_prompt = build_guarded_system_prompt(
            hint_files_in_prompt(combined, list(files), effective_tools)
        )
        response, tools_used = await call_agent(
            user_prompt,
            provider=agent["provider"],
            model=agent["model"],
            system_prompt=system_prompt,
            tool_names=effective_tools,
            tool_context={**tool_context, "files": files},
        )
        return response, tools_used
    finally:
        # A tool whose DB write failed (e.g. the LLM passed a bad thread_id/entry_id)
        # leaves the shared run connection's transaction aborted, which would reject
        # every later statement. Roll back so the next agent's writes succeed;
        # committed work is unaffected (engines commit on success). Also clears the
        # dangling transaction left by read-only tool calls.
        await _reset_transaction(tool_context.get("db"))


async def _reset_transaction(db: AsyncConnection | None) -> None:
    """Roll back any open/aborted transaction on the shared connection."""
    if db is None or not db.in_transaction():
        return
    try:
        await db.rollback()
    except Exception:
        logger.exception("Failed to roll back the swarm connection after an agent turn")


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


# ── Concurrent agent turns ───────────────────────────────────────────────────
# Within a sub-round every agent's turn is independent — each reads the
# start-of-round board and posts its own entry — so the turns can overlap. The
# wall-clock cost is one LLM round-trip apiece; running them concurrently turns a
# round from N sequential calls into ~1, so the board fills far faster.

# Cap on simultaneous in-flight turns, so a large swarm can't open an unbounded
# number of LLM calls / DB connections at once (rate limits, pool exhaustion).
_MAX_CONCURRENT_TURNS = 8


class _Turn(NamedTuple):
    """One agent's pending turn: who it is, plus a coroutine that runs it.

    ``run`` takes the DB connection the turn should use (the shared one when
    serialized, a private one when parallelized) and returns the steps to emit.
    """

    agent_name: str
    node_id: str
    run: Callable[[AsyncConnection], Awaitable[list[SimulationStep]]]


async def _run_turns(
    db: AsyncConnection, turns: list[_Turn], *, journal: RunJournal | None = None
) -> AsyncIterator[SimulationStep]:
    """Run a sub-round's agent turns, yielding each one's steps as it finishes.

    First emits an ``agent-thinking`` frame per turn so the UI lights up every
    agent the moment the (slow) LLM calls start, instead of going silent.

    On Postgres the turns run concurrently, each on its own connection, so their
    LLM calls overlap and entries stream back in completion order. On SQLite —
    whose ``StaticPool`` shares one underlying DBAPI connection that can't carry
    concurrent transactions — they run sequentially on the shared connection,
    preserving the single-connection semantics the test suite relies on.

    ``journal`` (resilient runs), when given, gets a heartbeat bump after each
    turn finishes draining — a liveness signal spread across the sub-round
    rather than one write at its very end, so a long sub-round still looks
    alive from the DB's point of view while it is in flight.
    """
    if not turns:
        return
    for turn in turns:
        yield _step("agent-thinking", f"{turn.agent_name} is responding…", node_id=turn.node_id)

    serial = db.engine.dialect.name == "sqlite" or len(turns) == 1
    if serial:
        for turn in turns:
            for step in await turn.run(db):
                yield step
            if journal is not None:
                await journal.heartbeat(db)
        return

    # Postgres: fan out, each turn on a private connection, bounded by a semaphore.
    sem = asyncio.Semaphore(_MAX_CONCURRENT_TURNS)

    async def _isolated(turn: _Turn) -> list[SimulationStep]:
        async with sem, db.engine.connect() as conn:
            return await turn.run(conn)

    tasks = [asyncio.create_task(_isolated(turn)) for turn in turns]
    try:
        for finished in asyncio.as_completed(tasks):
            for step in await finished:
                yield step
            if journal is not None:
                await journal.heartbeat(db)
    finally:
        # Cover early consumer exit (client disconnect) and any task error: cancel
        # whatever is still running and drain so every connection closes cleanly.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _auction_turn(
    invitation: Invitation,
    agent: dict[str, Any],
    run_id: str,
    contract: ContractSchema,
    agent_runner: AgentRunner,
) -> _Turn:
    """Build one auction self-selection turn (bid vs. abstain)."""

    async def run(conn: AsyncConnection) -> list[SimulationStep]:
        _text, tools_used = await agent_runner(
            agent,
            user_prompt=auction_user_prompt(contract, invitation),
            system_suffix=AUCTION_SYSTEM_SUFFIX,
            # No read_blackboard here: the board is empty during the auction, and the
            # full contract is already in the prompt. Offering it only invites agents
            # to "read" an empty board and wrongly conclude there is no contract.
            tool_names=["submit_bid", "abstain"],
            tool_context={
                "db": conn,
                "run_id": run_id,
                "agent_id": invitation.agent_id,
                "contract_id": contract.id,
                "preliminary_score": invitation.preliminary_score,
            },
        )
        return _auction_events(invitation, agent, tools_used)

    return _Turn(agent_name=agent["name"], node_id=invitation.agent_id, run=run)


def _board_turn(
    agent: dict[str, Any],
    *,
    run_id: str,
    agent_runner: AgentRunner,
    system_suffix: str,
    tool_names: list[str],
    thread_id: str,
    round: int,
    journal: RunJournal,
    phase: str,
    user_prompt: str | None = None,
    prompt_builder: Callable[[AsyncConnection], Awaitable[str]] | None = None,
) -> _Turn:
    """Build one blackboard turn (round 1 / vote / discussion) for ``agent``.

    Exactly one of ``user_prompt`` (static) or ``prompt_builder`` (awaited on
    the turn's own connection — required for anything that reads the DB, e.g.
    RAG retrieval in discussion rounds) must be provided.

    Resilient runs: the actual ``agent_runner`` call is wrapped with a timeout
    and one retry on a clean transaction. A turn that still fails after the
    retry is journaled ``failed`` and yields no board events (silence, not a
    crash) — ``run_swarm`` drops an agent out once it accumulates
    ``K_DROPOUT`` such failures. A turn that succeeds (first try or retry) is
    journaled ``done``.
    """
    if (user_prompt is None) == (prompt_builder is None):
        raise ValueError("provide exactly one of user_prompt / prompt_builder")

    async def run(conn: AsyncConnection) -> list[SimulationStep]:
        prompt = user_prompt if user_prompt is not None else await prompt_builder(conn)

        async def attempt() -> tuple[str, list[ToolCall]]:
            return await asyncio.wait_for(
                agent_runner(
                    agent,
                    user_prompt=prompt,
                    system_suffix=system_suffix,
                    tool_names=tool_names,
                    tool_context={
                        "db": conn,
                        "run_id": run_id,
                        "agent_id": agent["id"],
                        "thread_id": thread_id,
                        "round": round,
                    },
                ),
                timeout=TURN_TIMEOUT_S,
            )

        try:
            _text, tools_used = await attempt()
        except Exception:
            logger.exception("turn failed once for %s — retrying", agent.get("id"))
            await _reset_transaction(conn)
            try:
                _text, tools_used = await attempt()
            except Exception:
                logger.exception("turn failed twice for %s", agent.get("id"))
                await _reset_transaction(conn)
                await journal.turn(
                    conn, agent_id=agent["id"], phase=phase, round=round, status="failed"
                )
                return []

        steps = await _board_events(conn, agent, tools_used, round)
        await journal.turn(conn, agent_id=agent["id"], phase=phase, round=round, status="done")
        return steps

    return _Turn(agent_name=agent["name"], node_id=agent["id"], run=run)


# ── Run lifecycle helpers ────────────────────────────────────────────────────


async def _create_run(db: AsyncConnection, run_id: str, config: SwarmRunConfig) -> None:
    """Persist a new run, including its config (resilient runs): a resumed run
    must use the SAME knobs as the original, not silently-different defaults."""
    await db.execute(
        text(
            "INSERT INTO swarm_runs (id, status, mode, config, heartbeat_at) "
            "VALUES (:id, 'running', 'swarm', :config, :now)"
        ),
        {"id": run_id, "config": config.model_dump_json(), "now": datetime.now(UTC)},
    )
    await db.commit()


async def _load_run_config(db: AsyncConnection, run_id: str) -> SwarmRunConfig | None:
    """Reconstruct a run's original config for resume. None if never persisted
    (older rows, or a run created before this column existed)."""
    raw = (
        await db.execute(text("SELECT config FROM swarm_runs WHERE id = :id"), {"id": run_id})
    ).scalar()
    if not raw:
        return None
    return SwarmRunConfig(**json.loads(raw))


async def _complete_run(
    db: AsyncConnection,
    run_id: str,
    *,
    status: str,
    reason: str | None,
    round: int,
    final_answer: str | None = None,
    ratification: dict[str, Any] | None = None,
) -> None:
    await db.execute(
        text(
            "UPDATE swarm_runs "
            "SET status = :status, termination_reason = :reason, "
            "    termination_round = :round, final_answer = :final_answer, "
            "    ratification = :ratification, phase = 'done', "
            "    completed_at = :now "
            "WHERE id = :id"
        ),
        {
            "id": run_id,
            "status": status,
            "reason": reason,
            "round": round,
            "final_answer": final_answer,
            "ratification": json.dumps(ratification) if ratification is not None else None,
            "now": datetime.now(UTC),
        },
    )
    await db.commit()


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


async def _draft_entry_payload(db: AsyncConnection, entry_id: str) -> dict[str, Any] | None:
    """Fetch a posted draft entry shaped for the frontend board (DraftEntry)."""
    row = (
        (
            await db.execute(
                text(
                    """
                    SELECT de.id, de.run_id, de.thread_id, de.round, de.author_id,
                           COALESCE(a.name, de.author_id) AS author_name,
                           de.entry_type, de.content, de.reply_to, de.mention_agents,
                           de.documents_used, de.is_visible, de.last_cited_round, de.created_at,
                           de.claim, de.stance, de.stance_target, de.evidence
                    FROM draft_entries de
                    LEFT JOIN agents a ON a.id = de.author_id
                    WHERE de.id = :id
                    """
                ),
                {"id": entry_id},
            )
        )
        .mappings()
        .fetchone()
    )
    if row is None:
        return None
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "thread_id": row["thread_id"],
        "round": row["round"],
        "author_id": row["author_id"],
        "author_name": row["author_name"],
        "entry_type": row["entry_type"],
        "content": row["content"],
        "reply_to": row["reply_to"],
        "mention_agents": json.loads(row["mention_agents"] or "[]"),
        "documents_used": json.loads(row["documents_used"] or "[]"),
        "is_visible": bool(row["is_visible"]),
        "deleted_at": None,
        "last_cited_round": row["last_cited_round"],
        "citation_count": 0,
        "created_at": str(row["created_at"]),
        "children": [],
        "claim": row["claim"],
        "stance": row["stance"],
        "stance_target": row["stance_target"],
        "evidence": json.loads(row["evidence"] or "[]"),
    }


async def _board_events(
    db: AsyncConnection, agent: dict[str, Any], tools_used: list[ToolCall], round: int
) -> list[SimulationStep]:
    """Map blackboard tool calls to steps carrying full board payloads in ``data``.

    The frontend builds the board directly from these events (no REST re-fetch):
    bb-post carries the whole entry, bb-cite/bb-vote the cited id + citer.
    """
    steps: list[SimulationStep] = []

    # Files the agent actually read this turn (order-preserving, deduped) — any
    # post_to_blackboard call in this same turn is attributed to having consulted
    # them, since a turn is one LLM call's worth of sequential tool use.
    documents_read: list[str] = []
    for call in tools_used:
        if call.name != "files" or call.input.get("action") != "read":
            continue
        file_name = call.input.get("file_name")
        if file_name and file_name not in documents_read:
            documents_read.append(file_name)

    for call in tools_used:
        if call.name == "post_to_blackboard":
            entry_id = _parse_entry_id(call.output)
            payload = await _draft_entry_payload(db, entry_id) if entry_id else None
            if payload is None:
                continue
            if documents_read:
                await db.execute(
                    text("UPDATE draft_entries SET documents_used = :d WHERE id = :id"),
                    {"d": json.dumps(documents_read), "id": entry_id},
                )
                await db.commit()
                payload["documents_used"] = documents_read
            steps.append(
                _step(
                    "bb-post",
                    f"{agent['name']} posted a {payload['entry_type']}",
                    node_id=agent["id"],
                    thread_id=payload["thread_id"],
                    entry_id=entry_id,
                    data=payload,
                )
            )
            for mentioned in payload["mention_agents"]:
                steps.append(
                    _step(
                        "bb-mention",
                        f"{agent['name']} mentioned an agent",
                        node_id=str(mentioned),
                        entry_id=entry_id,
                    )
                )
        elif call.name == "cite":
            for cited in call.input.get("entry_ids") or []:
                steps.append(
                    _step(
                        "bb-cite",
                        f"{agent['name']} cited an entry",
                        node_id=agent["id"],
                        entry_id=str(cited),
                        data={"entry_id": str(cited), "citer_name": agent["name"], "round": round},
                    )
                )
        elif call.name == "vote":
            cited = call.input.get("entry_id")
            if cited:
                steps.append(
                    _step(
                        "bb-vote",
                        f"{agent['name']} voted on a proposal",
                        node_id=agent["id"],
                        entry_id=str(cited),
                        data={"entry_id": str(cited), "citer_name": agent["name"], "round": round},
                    )
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
        elif call.name == "dispute":
            # The flip to 'contested' (crossing threshold M) is a separate
            # bb-contest step emitted by the end-of-round contest_check pass —
            # this only records the individual challenge.
            steps.append(
                _step(
                    "bb-dispute",
                    f"{agent['name']} disputed a confirmed finding",
                    node_id=agent["id"],
                    entry_id=str(call.input.get("entry_id", "")) or None,
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

    turns = [
        _auction_turn(invitation, agent, run_id, contract, agent_runner)
        for invitation in invitations
        if (agent := agents_by_id.get(invitation.agent_id)) is not None
    ]
    async for step in _run_turns(db, turns):
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
    journal: RunJournal,
) -> AsyncIterator[SimulationStep]:
    """Every taker posts one opening proposal per thread, in two waves (PRD §9.3)."""
    yield _step("system", "Round 1 begins. Opening proposals.")
    # Round 1 runs at a neutral temperature (no confidence signal exists yet).
    instruction = ConvergenceEngine.temperature_instruction(0.5)
    suffix = round_one_system_suffix(instruction)

    # Wave split: takers arrive bid-score-ordered from select_takers, so the
    # first ceil(N/2) are the best-matched agents — they anchor the board
    # blind. The second wave reads their proposals first and is told to add,
    # not restate (full agreement = stay silent, endorse in the vote
    # sub-round that follows).
    half = (len(takers) + 1) // 2
    wave1, wave2 = takers[:half], takers[half:]

    def _wave_turns(
        wave: list[str], prompts_by_thread: dict[str, str] | None
    ) -> list[_Turn]:
        turns: list[_Turn] = []
        for thread in threads:
            coworkers = [agents_by_id[t]["name"] for t in takers if t in agents_by_id]
            for taker in wave:
                agent = agents_by_id.get(taker)
                if agent is None:
                    continue
                user_prompt = (
                    prompts_by_thread[thread.id]
                    if prompts_by_thread is not None
                    else round_one_user_prompt(
                        contract, thread, max_rounds=config.max_rounds, coworkers=coworkers
                    )
                )
                turns.append(
                    _board_turn(
                        agent,
                        run_id=run_id,
                        agent_runner=agent_runner,
                        user_prompt=user_prompt,
                        system_suffix=suffix,
                        tool_names=_ROUND1_TOOLS,
                        thread_id=thread.id,
                        round=1,
                        journal=journal,
                        phase="round_1",
                    )
                )
        return turns

    async for step in _run_turns(db, _wave_turns(wave1, None), journal=journal):
        yield step

    if wave2:
        yield _step("system", "Round 1, second wave: reviewing existing proposals.")
        coworkers_all = [agents_by_id[t]["name"] for t in takers if t in agents_by_id]
        wave2_prompts: dict[str, str] = {}
        for thread in threads:
            proposals = await _round1_proposals(db, run_id, thread.id)
            wave2_prompts[thread.id] = round_one_wave2_user_prompt(
                contract,
                thread,
                proposals=proposals,
                max_rounds=config.max_rounds,
                coworkers=coworkers_all,
            )
        async for step in _run_turns(db, _wave_turns(wave2, wave2_prompts), journal=journal):
            yield step


async def _run_vote_subround(
    db: AsyncConnection,
    run_id: str,
    threads: list[ThreadSchema],
    takers: list[str],
    agents_by_id: dict[str, dict[str, Any]],
    agent_runner: AgentRunner,
    journal: RunJournal,
) -> AsyncIterator[SimulationStep]:
    """Each taker votes on the round-1 proposals it endorses (PRD §9.4)."""
    yield _step("system", "Vote sub-round. Agents review Round 1 proposals.")
    turns: list[_Turn] = []
    for thread in threads:
        proposals = await _round1_proposals(db, run_id, thread.id)
        for taker in takers:
            agent = agents_by_id.get(taker)
            if agent is None:
                continue
            turns.append(
                _board_turn(
                    agent,
                    run_id=run_id,
                    agent_runner=agent_runner,
                    user_prompt=vote_user_prompt(thread, proposals),
                    system_suffix=VOTE_SYSTEM_SUFFIX,
                    tool_names=_VOTE_TOOLS,
                    thread_id=thread.id,
                    round=1,
                    journal=journal,
                    phase="vote",
                )
            )
    async for step in _run_turns(db, turns, journal=journal):
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

_ROUNDS_TOOLS = ["read_blackboard", "get_confirmed", "post_to_blackboard", "cite", "dispute"]


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
    journal: RunJournal,
) -> AsyncIterator[SimulationStep]:
    """One discussion round: each taker reads, replies, and cites (PRD §9.5)."""
    yield _step("system", f"Round {round} begins.")
    phase = f"round_{round}"
    turns: list[_Turn] = []
    for thread in threads:
        for taker in takers:
            agent = agents_by_id.get(taker)
            if agent is None:
                continue

            if round > 2:
                # Adaptive skip: an agent with nothing new since its last turn in
                # this thread (no fresh visible post by someone else, no mention,
                # no new citation of its own work) is a silent no-op — round 2
                # (first after the vote sub-round) never skips.
                #
                # ``since`` is deliberately the taker's own last active round, not
                # round + 1: rounds run as one synchronized batch, so at the time
                # this round's turns are being built, round N-1's data already
                # exists but round N's does not. Anchoring "new" to round+1 would
                # always find zero at the very next round after any turn — done
                # or skipped — permanently silencing the whole swarm. Anchoring to
                # the taker's own last round instead means a skip only fires once
                # truly nothing (from that round on) has changed for it.
                last_turn_round = (
                    await db.execute(
                        text(
                            "SELECT COALESCE(MAX(round), 1) FROM turn_log "
                            "WHERE run_id = :r AND agent_id = :a AND status IN ('done', 'skipped')"
                        ),
                        {"r": run_id, "a": taker},
                    )
                ).scalar_one()
                since = last_turn_round
                fresh_posts = (
                    await db.execute(
                        text(
                            "SELECT COUNT(*) FROM draft_entries "
                            "WHERE run_id = :r AND thread_id = :t AND is_visible = true "
                            "AND author_id != :a AND round >= :since"
                        ),
                        {"r": run_id, "t": thread.id, "a": taker, "since": since},
                    )
                ).scalar_one()
                mentioned = (
                    await db.execute(
                        text(
                            "SELECT COUNT(*) FROM draft_entries "
                            "WHERE run_id = :r AND round >= :since AND mention_agents LIKE :pat"
                        ),
                        {"r": run_id, "since": since, "pat": f'%"{taker}"%'},
                    )
                ).scalar_one()
                cited = (
                    await db.execute(
                        text(
                            "SELECT COUNT(*) FROM citations c "
                            "JOIN draft_entries de ON de.id = c.cited_entry_id "
                            "WHERE de.run_id = :r AND de.author_id = :a AND c.round >= :since"
                        ),
                        {"r": run_id, "a": taker, "since": since},
                    )
                ).scalar_one()
                if fresh_posts == 0 and mentioned == 0 and cited == 0:
                    await journal.turn(
                        db, agent_id=taker, phase=phase, round=round, status="skipped"
                    )
                    continue

            instruction = ConvergenceEngine.temperature_instruction(temperatures.get(taker, 1.0))

            def make_builder(
                agent_id: str, thread: ThreadSchema
            ) -> Callable[[AsyncConnection], Awaitable[str]]:
                async def build(conn: AsyncConnection) -> str:
                    entries = await Blackboard(conn).read(
                        run_id=run_id,
                        query=f"{agents_by_id[agent_id]['description']} — "
                        f"{thread.title}: {thread.description}",
                        thread_id=thread.id,
                        k=8,
                        agent_id=agent_id,
                    )
                    digest = format_entries_digest(entries) if entries else None
                    return rounds_user_prompt(
                        contract,
                        thread,
                        round=round,
                        max_rounds=config.max_rounds,
                        relevant_posts=digest,
                    )

                return build

            turns.append(
                _board_turn(
                    agent,
                    run_id=run_id,
                    agent_runner=agent_runner,
                    prompt_builder=make_builder(taker, thread),
                    system_suffix=rounds_system_suffix(instruction),
                    tool_names=_ROUNDS_TOOLS,
                    thread_id=thread.id,
                    round=round,
                    journal=journal,
                    phase=phase,
                )
            )
    async for step in _run_turns(db, turns, journal=journal):
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
    status_flips: dict[str, int],
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
            data=entry.model_dump(mode="json"),
        )

    # Contestable consensus: a contest or re-affirmation forces at least one more
    # round of deliberation, so the caller counts flips toward equilibrium activity.
    contested = await bb.contest_check(
        run_id=run_id, current_round=round, participants_by_thread=participants_by_thread
    )
    for entry in contested:
        yield _step(
            "bb-contest",
            "Confirmed finding contested.",
            thread_id=entry.thread_id,
            entry_id=entry.id,
            data=entry.model_dump(mode="json"),
        )
    reaffirmed = await bb.reaffirm_check(
        run_id=run_id, participants_by_thread=participants_by_thread
    )
    for entry in reaffirmed:
        yield _step(
            "bb-contest",
            "Contested finding re-affirmed.",
            thread_id=entry.thread_id,
            entry_id=entry.id,
            data=entry.model_dump(mode="json"),
        )
    status_flips["n"] = len(contested) + len(reaffirmed)

    # soft_delete_stale returns only a count, so diff the visible set to recover IDs.
    before = await _visible_entry_ids(db, run_id)
    await bb.soft_delete_stale(run_id=run_id, current_round=round, decay_rounds=config.decay_rounds)
    deleted_ids = before - await _visible_entry_ids(db, run_id)
    for entry_id in deleted_ids:
        yield _step(
            "bb-delete",
            "Entry soft-deleted (stale).",
            entry_id=entry_id,
            data={"entry_id": entry_id},
        )

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


async def _apply_dropouts(
    db: AsyncConnection,
    run_id: str,
    agents_by_id: dict[str, dict[str, Any]],
    dropped: set[str],
    announced: set[str],
) -> list[SimulationStep]:
    """Drop agents whose last ``K_DROPOUT`` turn_log rows are all ``failed``.

    Dropped takers are excluded from the promotion denominator, temperatures,
    and turns from this point on — but never marked observers and never
    trust-penalized (silence is not the same as a provider failure).
    """
    rows = (
        (
            await db.execute(
                text(
                    "SELECT agent_id, status FROM turn_log WHERE run_id = :r "
                    "ORDER BY agent_id, created_at"
                ),
                {"r": run_id},
            )
        )
        .mappings()
        .fetchall()
    )
    by_agent: dict[str, list[str]] = {}
    for row in rows:
        by_agent.setdefault(row["agent_id"], []).append(row["status"])

    steps: list[SimulationStep] = []
    for agent_id, statuses in by_agent.items():
        if agent_id in dropped:
            continue
        tail = statuses[-K_DROPOUT:]
        if len(tail) == K_DROPOUT and all(s == "failed" for s in tail):
            dropped.add(agent_id)
            if agent_id not in announced:
                announced.add(agent_id)
                name = agents_by_id.get(agent_id, {}).get("name", agent_id[:8])
                steps.append(_step("system", f"{name} dropped out (provider failures)"))
    return steps


# ── Ratified synthesis (post-synthesis approval sub-round) ──────────────────


async def _taker_confirmed_findings(
    db: AsyncConnection, run_id: str, taker: str
) -> list[tuple[str, str]]:
    """Return ``(confirmed_entry_id, content)`` for entries this taker authored."""
    rows = (
        (
            await db.execute(
                text(
                    """
                    SELECT ce.id AS id, ce.content AS content
                    FROM confirmed_entries ce
                    JOIN draft_entries de ON de.id = ce.source_draft_id
                    WHERE ce.run_id = :run_id AND de.author_id = :taker
                      AND ce.status = 'confirmed'
                    """
                ),
                {"run_id": run_id, "taker": taker},
            )
        )
        .mappings()
        .all()
    )
    return [(row["id"], row["content"]) for row in rows]


async def _post_synthesis_candidate(
    db: AsyncConnection, run_id: str, thread_id: str, round_confirmed: int, candidate: str
) -> None:
    """Post the draft final answer to the confirmed layer as a system entry so
    it is visible on the board during ratification (no per-thread ratification —
    one candidate answers the whole run; the first thread anchors the row)."""
    await db.execute(
        text(
            """
            INSERT INTO confirmed_entries
                (id, run_id, thread_id, content, entry_type, citation_count, round_confirmed)
            VALUES (:id, :run_id, :thread_id, :content, 'system', 0, :round_confirmed)
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "run_id": run_id,
            "thread_id": thread_id,
            "content": f"[synthesis candidate] {candidate}",
            "round_confirmed": round_confirmed,
        },
    )
    await db.commit()


def _ratify_turn(
    agent: dict[str, Any],
    candidate: str,
    own_findings: list[tuple[str, str]],
    votes: dict[str, str | None],
    agent_runner: AgentRunner,
    run_id: str,
) -> _Turn:
    """Build one ratification turn: the taker approves or requests a revision."""

    async def run(conn: AsyncConnection) -> list[SimulationStep]:
        await agent_runner(
            agent,
            user_prompt=ratify_user_prompt(candidate, own_findings),
            system_suffix=RATIFY_SYSTEM_SUFFIX,
            tool_names=["approve_synthesis", "revise_synthesis"],
            tool_context={
                "db": conn,
                "run_id": run_id,
                "agent_id": agent["id"],
                "ratification_votes": votes,
            },
        )
        return []

    return _Turn(agent_name=agent["name"], node_id=agent["id"], run=run)


async def _run_ratification(
    db: AsyncConnection,
    run_id: str,
    candidate: str,
    takers: list[str],
    dropped: set[str],
    agents_by_id: dict[str, dict[str, Any]],
    agent_runner: AgentRunner,
) -> tuple[list[SimulationStep], int, int, list[str]]:
    """Run one ratification sub-round.

    Returns ``(steps, approvals, voters, objections)``. ``voters`` is the count
    of active (non-dropped) takers — the majority denominator — not the count
    of respondents: a taker whose turn makes no tool call is a silent
    non-approval, per spec.
    """
    votes: dict[str, str | None] = {}
    active = [t for t in takers if t not in dropped]
    turns: list[_Turn] = []
    for taker in active:
        agent = agents_by_id.get(taker)
        if agent is None:
            continue
        own = await _taker_confirmed_findings(db, run_id, taker)
        turns.append(_ratify_turn(agent, candidate, own, votes, agent_runner, run_id))
    steps = [step async for step in _run_turns(db, turns)]
    approvals = sum(1 for v in votes.values() if v is None)
    objections = [v for v in votes.values() if v]
    return steps, approvals, len(active), objections


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
    synthesizer: Synthesizer | None = None,
) -> AsyncIterator[SimulationStep]:
    """Drive one swarm run end-to-end, yielding ``SimulationStep`` events.

    Seam defaults are the v1 placeholders; pass real components to override.
    """
    contract_source = contract_source or FallbackContractSource()
    terminator = terminator or MaxRoundsTerminator()
    trust = trust or DefaultTrustRegistry.from_config(config)
    agent_runner = agent_runner or _default_agent_runner
    # No-LLM default so the run loop and tests stay offline; routes inject the real
    # AnswerSynthesizer (one LLM call) exactly as they inject the Market Maker.
    synthesizer = synthesizer or FallbackAnswerSynthesizer()

    run_id = str(uuid.uuid4())
    await _create_run(db, run_id, config)
    agents_by_id = await _load_agents(db)
    journal = RunJournal(run_id)
    dropped: set[str] = set()
    announced_dropouts: set[str] = set()

    # ── Contract (Market Maker seam) ──────────────────────────────────────────
    # The Confirmed layer starts empty by design — it fills only as draft entries
    # earn enough citations to be promoted. The contract/threads live in the
    # agents' prompts, not as confirmed anchors.
    #
    # Emit an immediate frame so the client sees the run start: the Market Maker's
    # LLM call below is the first slow step, and some clients/proxies don't render
    # the stream until the first real ``data:`` frame arrives (a comment is not
    # enough). This also confirms liveness while the contract is being drafted.
    yield _step("system", "Run started — drafting the contract…", data={"run_id": run_id})
    contract, threads = await contract_source.make_contract(config.prompt, run_id, db)
    yield _step(
        "system",
        f"Contract created: {contract.task_type}, {contract.task_nature}, "
        f"confidence={contract.confidence:.2f}",
        data={"run_id": run_id, "contract_id": contract.id},
    )
    yield _step(
        "system",
        f"Threads created: {', '.join(t.title for t in threads)}",
        data={
            "thread_ids": [t.id for t in threads],
            # Slim thread objects (no embeddings) so the board can show thread tabs.
            "threads": [t.model_dump(mode="json", exclude={"thread_embedding"}) for t in threads],
        },
    )

    # ── Auction (Market Hive §6.2) ───────────────────────────────────────────
    await journal.phase(db, "auction")
    auction = AuctionEngine.from_config(db, config)
    async for step in _run_auction(db, auction, run_id, contract, agents_by_id, agent_runner):
        yield step

    takers = await auction.get_takers(run_id=run_id)
    if not takers:
        await _complete_run(db, run_id, status="aborted", reason="no_takers", round=0)
        return

    # ── Round 1 — opening proposals (§9.3) ───────────────────────────────────
    convergence = ConvergenceEngine.from_config(db, config)
    await journal.phase(db, "round_1", 1)
    async for step in _run_round_one(
        db, run_id, contract, threads, takers, agents_by_id, agent_runner, config, journal
    ):
        yield step
    for step in await _apply_dropouts(db, run_id, agents_by_id, dropped, announced_dropouts):
        yield step
    takers = [t for t in takers if t not in dropped]

    # ── Vote sub-round → cold-start confidence/temperature (§9.4, §6.4) ───────
    await journal.phase(db, "vote", 1)
    async for step in _run_vote_subround(
        db, run_id, threads, takers, agents_by_id, agent_runner, journal
    ):
        yield step
    for step in await _apply_dropouts(db, run_id, agents_by_id, dropped, announced_dropouts):
        yield step
    takers = [t for t in takers if t not in dropped]
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
        await journal.phase(db, f"round_{round}", round)
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
            journal,
        ):
            yield step
        for step in await _apply_dropouts(db, run_id, agents_by_id, dropped, announced_dropouts):
            yield step
        takers = [t for t in takers if t not in dropped]

        status_flips = {"n": 0}
        async for step in _end_of_round(
            db, run_id, threads, takers, round, convergence, contract.task_type, config, status_flips
        ):
            yield step

        temperatures = await _next_temperatures(db, run_id, threads, takers, round, convergence)

        if amendment_processor is not None:
            async for step in amendment_processor.process(
                run_id=run_id, current_round=round, takers=takers, db=db
            ):
                yield step

        if await terminator.should_terminate(
            run_id=run_id, round=round, config=config, db=db, status_flips=status_flips["n"]
        ):
            termination_reason = "equilibrium"
            break

    # ── Finalize: select + synthesize the answer, update trust, emit (§6.6, §6.7) ─
    await journal.phase(db, "synthesis", last_round)
    output = await terminator.format_output(
        run_id=run_id,
        round=last_round,
        reason=termination_reason,
        db=db,
        prompt=None,
        synthesizer=None,
    )
    live_findings = [f for f in output.confirmed_layer if f.status == "confirmed"]
    ratification: dict[str, Any] | None = None
    final_answer = output.final_answer
    if live_findings and threads:
        candidate = await synthesizer.synthesize(prompt=config.prompt, findings=live_findings)
        await _post_synthesis_candidate(db, run_id, threads[0].id, last_round, candidate)
        steps, approvals, voters, objections = await _run_ratification(
            db, run_id, candidate, takers, dropped, agents_by_id, agent_runner
        )
        for step in steps:
            yield step
        if voters == 0 or approvals > voters / 2:
            final_answer = candidate
            ratification = {
                "approved": True,
                "round": 1,
                "approvals": approvals,
                "voters": voters,
                "objections": objections,
            }
        else:
            revised = await synthesizer.synthesize(
                prompt=config.prompt, findings=live_findings, objections=objections
            )
            await _post_synthesis_candidate(db, run_id, threads[0].id, last_round, revised)
            steps2, approvals2, voters2, objections2 = await _run_ratification(
                db, run_id, revised, takers, dropped, agents_by_id, agent_runner
            )
            for step in steps2:
                yield step
            final_answer = revised
            ratification = {
                "approved": approvals2 > voters2 / 2 if voters2 else True,
                "round": 2,
                "approvals": approvals2,
                "voters": voters2,
                "objections": objections2,
            }
    output = output.model_copy(update={"final_answer": final_answer, "ratification": ratification})

    observers = await auction.get_observers(run_id=run_id)
    await trust.update(run_id=run_id, takers=takers, observers=observers, db=db)
    await _complete_run(
        db,
        run_id,
        status="completed",
        reason=termination_reason,
        round=last_round,
        final_answer=output.final_answer,
        ratification=ratification,
    )
    yield _step(
        "convergence",
        f"Run complete ({termination_reason}, round {last_round}).",
        data={**output.model_dump(mode="json"), "ratification": ratification},
    )
