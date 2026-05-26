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

Three consensus modes are supported via `mode`:

- ``broadcast_no_consensus``: discussion-only, no consensus operator; useful for
  free-form exploration.
- ``weighted_opinion_pooling``: each agent maintains a trust weight vector over its
  neighbours. Replies are presented to the agent labelled with weights;
  weights are updated each round based on textual agreement (Jaccard).
  Converges when weights stop changing across a round.
- ``plurality_voting``: every agent emits structured ``REASON: ...`` and ``VOTE: ...``
  lines. A pure tally function (no separate agent) counts the votes and
  broadcasts the plurality plus submitted reasons back to every agent.
  Converges when the plurality is stable across two consecutive vote rounds —
  the broadcast counts as the first round, so a single matching follow-up is
  enough to stop.

An agent that fails during any phase has its error recorded as its response
for that round; subsequent rounds will include the error text as context so
other agents remain aware of the failure.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import (
    create_connection,
    create_round,
    create_trial,
    deserialise_agent_row,
    hint_files_in_prompt,
    load_files_by_agent,
    record_message,
)
from server.db.tables import agents as agents_table
from server.db.tables import connections as connections_table
from server.db.tables import messages as messages_table
from server.db.tables import rounds as rounds_table
from server.guardrails import build_guarded_system_prompt, sanitize_prompt
from server.guardrails.input_sanitizer import PromptInjectionError
from server.llm import call_agent
from server.schemas import ToolCall

ConsensusMode = Literal[
    "broadcast_no_consensus",
    "weighted_opinion_pooling",
    "plurality_voting",
]

# Callable type for the bound agent-call closure passed into runner functions.
_AgentCall = Callable[[dict[str, Any], str], Awaitable[tuple[str, list[ToolCall]]]]

MessageDelivery = tuple[str | None, str, str]
SelfMessage = tuple[str, str]


@dataclass(frozen=True)
class AgentMessage:
    """Latest DB-backed output from one agent."""

    message_id: int
    round_id: int
    round_index: int
    from_agent_id: str
    message: str


# Helpers


async def _call_agent(
    agent: dict[str, Any], prompt: str, files: dict[str, str], ruleset: str | None = None
) -> tuple[str, list[ToolCall]]:
    """Invoke an agent and return (response_text, tools_used).

    `ruleset`, when provided, is prepended to the agent's system prompt so every
    LLM call in a simulation run automatically abides by the shared rules.

    The prompt is sanitised for injection attempts before being forwarded to the
    LLM.  The system prompt is wrapped with anti-hallucination guardrails.
    """
    # Sanitise the incoming prompt (raises PromptInjectionError on attack)
    try:
        sanitize_prompt(prompt, field_name="simulation prompt")
    except PromptInjectionError as exc:
        return f"[GUARDRAIL BLOCKED] {exc}", []

    file_names = list(files.keys())
    raw_system_prompt = hint_files_in_prompt(agent["system_prompt"] or None, file_names)

    # Wrap with anti-hallucination guardrails
    guarded_system_prompt = build_guarded_system_prompt(raw_system_prompt)

    if ruleset and ruleset.strip():
        # Sanitise ruleset before injecting it into the system prompt
        try:
            sanitize_prompt(ruleset, field_name="ruleset")
        except PromptInjectionError as exc:
            return f"[GUARDRAIL BLOCKED ruleset] {exc}", []
        guarded_system_prompt = f"## RULESET\n{ruleset.strip()}\n\n{guarded_system_prompt}"
    guarded_system_prompt = (
        f"## CURRENT DATE\n{date.today().isoformat()}\n\n{guarded_system_prompt}"
    )

    response, tools_used = await call_agent(
        prompt,
        provider=agent["provider"],
        model=agent["model"],
        system_prompt=guarded_system_prompt,
        tool_names=agent["tools"] or None,
        tool_context={"files": files},
    )
    return str(response), tools_used


def _last_tool_calls(tools_used: list[ToolCall]) -> list[ToolCall]:
    """Return the last call for each tool, preserving first-seen tool order."""
    # Keep only the last call per tool (e.g. files: list → read → show the read)
    last_by_name: dict[str, ToolCall] = {}
    for tool in tools_used:
        last_by_name[tool.name] = tool
    return list(last_by_name.values())


def _format_tool_message(tool: ToolCall) -> str:
    """Format a tool call the same way it appears in the simulation sidebar."""
    input_summary = " · ".join(f"**{k}:** `{v}`" for k, v in tool.input.items())
    output = tool.output.strip()
    output_block = f"```\n{output}\n```" if "\n" in output else output
    return f"action: {input_summary}\n\n**Result:**\n{output_block}"


def _self_messages(response: str, tools_used: list[ToolCall]) -> list[SelfMessage]:
    """Build self-addressed history messages for an agent's actions and output."""
    messages: list[SelfMessage] = [
        ("tool", _format_tool_message(tool)) for tool in _last_tool_calls(tools_used)
    ]
    messages.append(("agent_output", response))
    return messages


def _with_context(prompt: str, agent_id: str, agent_context: dict[str, str] | None) -> str:
    """Prepend an agent's private context to its prompt, if any.

    Context values are sanitised for injection attempts; a blocked context is
    silently omitted (the simulation continues without the private context).
    """
    if agent_context and agent_id in agent_context and agent_context[agent_id]:
        ctx = agent_context[agent_id]
        try:
            sanitize_prompt(ctx, field_name=f"agent_context[{agent_id}]")
        except PromptInjectionError:
            # Log and skip - don't abort the whole simulation
            return prompt
        return f"Your private context:\n{ctx}\n\n{prompt}"
    return prompt


def _jaccard(a: str, b: str) -> float:
    """Token-set Jaccard similarity. Cheap, no LLM/embedding dependency."""
    sa = set(a.lower().split())
    sb = set(b.lower().split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


_REASON_RE = re.compile(
    r"^\s*(?:>\s*)?(?:[-*+]\s*|\d+[.)]\s*)?(?:\*\*)?REASON(?:\*\*)?\s*[:\-]\s*(?:\*\*)?(.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_VOTE_RE = re.compile(
    r"^\s*(?:>\s*)?(?:[-*+]\s*|\d+[.)]\s*)?(?:\*\*)?VOTE(?:\*\*)?\s*[:\-]\s*(?:\*\*)?(.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_ZERO_SCORE_VOTES = frozenset({"unknown"})
_VOTE_INSTRUCTION = (
    "\n\nIMPORTANT: End your response with these two lines in this EXACT format:\n"
    "REASON: <why you chose the answer, including a quote and/or file/source "
    "if available>\n"
    "VOTE: <bare answer only — no preamble, no full sentence >\n"
    "Examples:\n"
    "  GOOD: REASON: Dylan was chosen due to the quote "
    "'Dylan is the manager of organisation delta' from 2026_information.txt\n"
    "        VOTE: Dylan\n"
    "  BAD:  VOTE: The manager is Dylan\n"
    "if you dont have an answer, vote with: 'unknown'\n"
    "if you dont think there is a correct answer, vote with: none"
    "Examples:\n"
    "  GOOD: REASON: No information regarding the question was found "
    "        VOTE: unknown\n"
    "  BAD:  unknown\n"
    "  GOOD: REASON: No other agent has provided any valid alternative answer"
    "        VOTE: none\n"
    "  BAD: none\n"
)

# Strip stop-words and common framing prefixes so semantically equivalent
# replies (\"Trump\" vs \"the president of america is trump\") tally together.
_VOTE_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "was",
        "are",
        "be",
        "of",
        "to",
        "in",
        "on",
        "for",
        "and",
        "or",
        "with",
        "by",
        "this",
        "that",
        "it",
        "as",
        "at",
        "from",
        "answer",
        "vote",
    }
)


def _normalise_vote(raw: str) -> str:
    """Lowercase, strip punctuation, drop common stop-words.

    Keeps the remaining tokens in original order so multi-word answers
    (\"new york\") stay intact while preambles (\"the answer is …\") fall away.
    """
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in raw.lower())
    tokens = [t for t in cleaned.split() if t and t not in _VOTE_STOPWORDS]
    return " ".join(tokens) if tokens else " ".join(cleaned.split())


def _extract_vote(text: str) -> str | None:
    """Pull the last VOTE: ... line from a response and normalise it."""
    matches = _VOTE_RE.findall(text)
    if not matches:
        return None
    return _normalise_vote(matches[-1]) or None


def _extract_reason(text: str) -> str | None:
    """Pull the last REASON: ... line from a response."""
    matches = _REASON_RE.findall(text)
    if not matches:
        return None
    reason = matches[-1].strip()
    return reason or None


def _tally(votes: dict[str, str | None]) -> tuple[str | None, dict[str, int]]:
    """Count valid votes and return (plurality, counts).

    ``unknown`` is an abstention: it records that an agent found no answer, but
    contributes zero score to plurality voting.
    """
    counts: dict[str, int] = {}
    for v in votes.values():
        if v and v not in _ZERO_SCORE_VOTES:
            counts[v] = counts.get(v, 0) + 1
    if not counts:
        return None, counts
    plurality = max(counts.items(), key=lambda kv: kv[1])[0]
    return plurality, counts


def _format_tally(plurality: str | None, counts: dict[str, int]) -> str:
    if not counts:
        return "No valid votes were cast."
    sorted_counts = sorted(counts.items(), key=lambda kv: -kv[1])
    lines = [f"- '{ans}': {n} vote{'s' if n != 1 else ''}" for ans, n in sorted_counts]
    return f"**Plurality:** '{plurality}'\n\n" + "\n".join(lines)


def _format_vote_reasons(
    agents: list[dict[str, Any]],
    votes: dict[str, str | None],
    reasons: dict[str, str | None],
) -> str:
    """Format per-agent vote reasons for the next voting round."""
    lines = []
    for agent in agents:
        agent_id = agent["id"]
        vote = votes.get(agent_id) or "no valid vote"
        reason = reasons.get(agent_id) or "No reason provided."
        lines.append(f"- {agent['name']} voted '{vote}': {reason}")
    return "\n".join(lines)


def _build_incoming(agents: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Build the undirected adjacency dict from each agent's connections list."""
    agent_by_id = {a["id"]: a for a in agents}
    incoming: dict[str, list[str]] = {a["id"]: [] for a in agents}
    seen: set[frozenset[str]] = set()
    for agent in agents:
        for target_id in agent["connections"]:
            if target_id not in agent_by_id or target_id == agent["id"]:
                continue
            pair = frozenset({agent["id"], target_id})
            if pair in seen:
                continue
            seen.add(pair)
            incoming[target_id].append(agent["id"])
            incoming[agent["id"]].append(target_id)
    return incoming


def _trial_description(mode: ConsensusMode) -> str:
    """Generate a description for an individual trial."""
    return f"{mode} run - {datetime.now().isoformat(timespec='seconds')}"


async def _persist_system_broadcast(
    db: AsyncConnection,
    trial_id: str,
    agents: list[dict[str, Any]],
    prompt: str,
    phase: str,
    round_index: int = 1,
) -> int:
    """Record the initial one-way SYSTEM prompt sent to every agent."""
    round_id = int(await create_round(db, trial_id, round_index, phase))
    for agent in agents:
        await record_message(db, round_id, None, str(agent["id"]), "system_broadcast", prompt)
    return round_id


async def _persist_agent_deliveries(
    db: AsyncConnection,
    round_id: int,
    deliveries: Sequence[MessageDelivery],
    message_type: str,
    source_messages: dict[str, AgentMessage] | None = None,
) -> None:
    """Record directed agent-to-agent payloads delivered during a round."""
    for from_agent_id, to_agent_id, message in deliveries:
        source_message = (
            source_messages.get(from_agent_id)
            if source_messages and from_agent_id is not None
            else None
        )
        await record_message(
            db,
            round_id,
            from_agent_id,
            to_agent_id,
            message_type,
            message,
            {"source_message_id": source_message.message_id} if source_message else None,
        )


async def _persist_self_messages(
    db: AsyncConnection,
    round_id: int,
    agent_id: str,
    messages: list[SelfMessage],
) -> None:
    """Record actions and outputs as messages sent from an agent to itself."""
    for message_type, message in messages:
        await record_message(db, round_id, agent_id, agent_id, message_type, message)


async def _persist_system_self_message(
    db: AsyncConnection,
    round_id: int,
    message_type: str,
    message: str,
) -> None:
    """Record synthetic SYSTEM notes as messages sent from SYSTEM to itself."""
    await record_message(db, round_id, None, None, message_type, message)


async def _create_self_message_round(
    db: AsyncConnection,
    trial_id: str,
    round_index: int,
    phase: str,
) -> int:
    """Create a persisted round for agent self-addressed action/output messages."""
    return int(await create_round(db, trial_id, round_index, phase))


async def _copy_topology_to_round(
    db: AsyncConnection,
    source_round_id: int,
    target_round_id: int,
) -> int:
    """Copy persisted agent-agent edges from one round snapshot to another."""
    result = await db.execute(
        select(connections_table.c.from_agent_id, connections_table.c.to_agent_id).where(
            connections_table.c.round_id == source_round_id,
            connections_table.c.from_agent_id.is_not(None),
            connections_table.c.to_agent_id.is_not(None),
            connections_table.c.from_agent_id != connections_table.c.to_agent_id,
        )
    )
    copied = 0
    for row in result:
        await create_connection(db, target_round_id, row.from_agent_id, row.to_agent_id)
        copied += 1
    return copied


async def _seed_topology_from_agent_connections(
    db: AsyncConnection,
    round_id: int,
    agents: list[dict[str, Any]],
) -> int:
    """Compatibility seed from agents.connections when no DB topology exists yet."""
    agent_by_id = {str(a["id"]): a for a in agents}
    seen: set[frozenset[str]] = set()
    created = 0
    for agent in agents:
        source_id = str(agent["id"])
        for target_id in agent["connections"]:
            target_id = str(target_id)
            if target_id not in agent_by_id or target_id == source_id:
                continue
            pair = frozenset({source_id, target_id})
            if pair in seen:
                continue
            seen.add(pair)
            await create_connection(db, round_id, source_id, target_id)
            await create_connection(db, round_id, target_id, source_id)
            created += 2
    return created


async def _latest_prior_topology_round_id(
    db: AsyncConnection,
    trial_id: str,
    before_round_index: int,
) -> int | None:
    """Find the latest prior round that contains real agent-agent topology edges."""
    result = await db.execute(
        select(rounds_table.c.id)
        .select_from(
            rounds_table.join(
                connections_table,
                connections_table.c.round_id == rounds_table.c.id,
            )
        )
        .where(
            rounds_table.c.trial_id == trial_id,
            rounds_table.c.round_index < before_round_index,
            connections_table.c.from_agent_id.is_not(None),
            connections_table.c.to_agent_id.is_not(None),
            connections_table.c.from_agent_id != connections_table.c.to_agent_id,
        )
        .order_by(rounds_table.c.round_index.desc(), rounds_table.c.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _ensure_round_topology(
    db: AsyncConnection,
    *,
    trial_id: str,
    round_id: int,
    round_index: int,
    agents: list[dict[str, Any]],
    previous_topology_round_id: int | None,
) -> bool:
    """Create this round's topology snapshot from DB state.

    Existing algorithms keep the topology unchanged by copying the previous
    snapshot. If a client created an initial setup round, that round is copied.
    The legacy agents.connections seed only keeps the current one-step run API
    working until the client creates the first snapshot itself.
    """
    if previous_topology_round_id is not None:
        return await _copy_topology_to_round(db, previous_topology_round_id, round_id) > 0

    source_round_id = await _latest_prior_topology_round_id(db, trial_id, round_index)
    if source_round_id is not None:
        return await _copy_topology_to_round(db, source_round_id, round_id) > 0

    return await _seed_topology_from_agent_connections(db, round_id, agents) > 0


async def _load_incoming_agent_ids(
    db: AsyncConnection,
    round_id: int,
    agent_id: str,
) -> list[str]:
    """Return sender ids connected to this receiver in the round snapshot."""
    result = await db.execute(
        select(connections_table.c.from_agent_id)
        .where(
            connections_table.c.round_id == round_id,
            connections_table.c.to_agent_id == agent_id,
            connections_table.c.from_agent_id.is_not(None),
            connections_table.c.from_agent_id != agent_id,
        )
        .order_by(connections_table.c.id.asc())
    )
    return [str(row.from_agent_id) for row in result]


async def _load_latest_agent_output(
    db: AsyncConnection,
    *,
    trial_id: str,
    agent_id: str,
    before_round_index: int,
) -> AgentMessage | None:
    """Load one agent's latest prior output/error from persisted messages."""
    result = await db.execute(
        select(
            messages_table.c.id.label("message_id"),
            messages_table.c.round_id,
            rounds_table.c.round_index,
            messages_table.c.from_agent_id,
            messages_table.c.message,
        )
        .select_from(
            messages_table.join(rounds_table, rounds_table.c.id == messages_table.c.round_id)
        )
        .where(
            rounds_table.c.trial_id == trial_id,
            rounds_table.c.round_index < before_round_index,
            messages_table.c.from_agent_id == agent_id,
            messages_table.c.to_agent_id == agent_id,
            messages_table.c.message_type.in_(["agent_output", "agent_error"]),
        )
        .order_by(rounds_table.c.round_index.desc(), messages_table.c.id.desc())
        .limit(1)
    )
    row = result.mappings().first()
    if row is None or row["message"] is None or row["from_agent_id"] is None:
        return None
    return AgentMessage(
        message_id=int(row["message_id"]),
        round_id=int(row["round_id"]),
        round_index=int(row["round_index"]),
        from_agent_id=str(row["from_agent_id"]),
        message=str(row["message"]),
    )


async def _load_latest_outputs_for_senders(
    db: AsyncConnection,
    *,
    trial_id: str,
    sender_ids: list[str],
    before_round_index: int,
) -> list[AgentMessage]:
    """Load latest prior outputs for the supplied senders from the DB."""
    outputs: list[AgentMessage] = []
    for sender_id in sender_ids:
        message = await _load_latest_agent_output(
            db,
            trial_id=trial_id,
            agent_id=sender_id,
            before_round_index=before_round_index,
        )
        if message is not None:
            outputs.append(message)
    return outputs


async def _load_latest_votes(
    db: AsyncConnection,
    *,
    trial_id: str,
    agents: list[dict[str, Any]],
    before_round_index: int,
) -> tuple[dict[str, str | None], dict[str, str | None], dict[str, str]]:
    """Derive latest votes, reasons and raw responses from persisted outputs."""
    votes: dict[str, str | None] = {}
    reasons: dict[str, str | None] = {}
    responses: dict[str, str] = {}
    for agent in agents:
        agent_id = str(agent["id"])
        latest = await _load_latest_agent_output(
            db,
            trial_id=trial_id,
            agent_id=agent_id,
            before_round_index=before_round_index,
        )
        text = latest.message if latest is not None else ""
        responses[agent_id] = text
        votes[agent_id] = _extract_vote(text)
        reasons[agent_id] = _extract_reason(text)
    return votes, reasons, responses


async def _load_latest_trust_weights(
    db: AsyncConnection,
    *,
    trial_id: str,
    agent_id: str,
    neighbour_ids: list[str],
    before_round_index: int,
) -> dict[str, float]:
    """Load an agent's latest persisted trust vector or return uniform weights."""
    if not neighbour_ids:
        return {}
    result = await db.execute(
        select(messages_table.c.meta)
        .select_from(
            messages_table.join(rounds_table, rounds_table.c.id == messages_table.c.round_id)
        )
        .where(
            rounds_table.c.trial_id == trial_id,
            rounds_table.c.round_index < before_round_index,
            messages_table.c.from_agent_id == agent_id,
            messages_table.c.to_agent_id == agent_id,
            messages_table.c.message_type == "trust_update",
        )
        .order_by(rounds_table.c.round_index.desc(), messages_table.c.id.desc())
        .limit(1)
    )
    raw_meta = result.scalar_one_or_none()
    if raw_meta:
        try:
            weights = json.loads(raw_meta).get("weights", {})
        except json.JSONDecodeError:
            weights = {}
        loaded = {
            n: float(weights[n])
            for n in neighbour_ids
            if n in weights and isinstance(weights[n], int | float)
        }
        if loaded:
            missing = [n for n in neighbour_ids if n not in loaded]
            remainder = max(0.0, 1.0 - sum(loaded.values()))
            default = remainder / len(missing) if missing else 0.0
            return {n: loaded.get(n, default) for n in neighbour_ids}
    return {n: 1.0 / len(neighbour_ids) for n in neighbour_ids}


async def _persist_trust_update(
    db: AsyncConnection,
    round_id: int,
    agent_id: str,
    weights: dict[str, float],
    max_change: float,
) -> None:
    """Persist weighted-pooling state in messages.meta."""
    await record_message(
        db,
        round_id,
        agent_id,
        agent_id,
        "trust_update",
        None,
        {
            "consensus_mode": "weighted_opinion_pooling",
            "weights": weights,
            "max_change": max_change,
        },
    )


# Public interface


async def run_topology(
    prompt: str,
    db: AsyncConnection,
    rounds: int = 3,
    mode: ConsensusMode = "broadcast_no_consensus",
    agent_context: dict[str, str] | None = None,
    trial_id: str | None = None,
    ruleset: str | None = None,
) -> None:
    """Run a topology simulation under the chosen consensus mode.

    All database reads happen here, up front and sequentially. Each agent's
    knowledge files are pre-loaded so the concurrent LLM phase never touches the
    connection (a single async connection cannot serve concurrent queries).
    """
    result = await db.execute(select(agents_table))
    agents: list[dict[str, Any]] = [deserialise_agent_row(row) for row in result.mappings().all()]

    if not agents:
        return

    files_by_agent = await load_files_by_agent(db)
    if trial_id is None:
        trial_id = await create_trial(db, prompt, _trial_description(mode), mode)

    async def call(agent: dict[str, Any], prompt: str) -> tuple[str, list[ToolCall]]:
        return await _call_agent(agent, prompt, files_by_agent.get(agent["id"], {}), ruleset)

    if mode == "weighted_opinion_pooling":
        await _run_weighted_opinion_pool(prompt, agents, call, db, rounds, agent_context, trial_id)
        return
    if mode == "plurality_voting":
        await _run_voting(prompt, agents, call, db, rounds, agent_context, trial_id)
        return
    await _run_broadcast_no_consensus(prompt, agents, call, db, rounds, agent_context, trial_id)


# Mode 1: broadcast (no consensus)


async def _run_broadcast_no_consensus(
    prompt: str,
    agents: list[dict[str, Any]],
    call: _AgentCall,
    db: AsyncConnection,
    rounds: int,
    agent_context: dict[str, str] | None,
    trial_id: str,
) -> None:
    agent_by_id = {a["id"]: a for a in agents}
    await _persist_system_broadcast(db, trial_id, agents, prompt, "broadcast_no_consensus")
    broadcast_output_round_id = await _create_self_message_round(
        db, trial_id, 2, "broadcast_no_consensus_outputs"
    )

    async def _broadcast(
        agent: dict[str, Any],
    ) -> tuple[str, list[SelfMessage]]:
        agent_id = str(agent["id"])
        try:
            response, tools_used = await call(agent, _with_context(prompt, agent_id, agent_context))
        except Exception as exc:
            err = f"[error: {exc}]"
            return err, [("agent_error", err)]
        return response, _self_messages(response, tools_used)

    bcast = await asyncio.gather(*[_broadcast(a) for a in agents])
    for agent, (_response, self_messages) in zip(agents, bcast, strict=True):
        agent_id = str(agent["id"])
        await _persist_self_messages(db, broadcast_output_round_id, agent_id, self_messages)

    previous_topology_round_id: int | None = None
    for round_num in range(1, rounds + 1):
        round_index = round_num + 2
        round_id = await create_round(db, trial_id, round_index, "discussion")
        has_topology = await _ensure_round_topology(
            db,
            trial_id=trial_id,
            round_id=round_id,
            round_index=round_index,
            agents=agents,
            previous_topology_round_id=previous_topology_round_id,
        )
        if not has_topology:
            break

        jobs: list[tuple[dict[str, Any], list[AgentMessage], str]] = []
        for agent in agents:
            agent_id = str(agent["id"])
            senders = await _load_incoming_agent_ids(db, round_id, agent_id)
            latest_messages = await _load_latest_outputs_for_senders(
                db,
                trial_id=trial_id,
                sender_ids=senders,
                before_round_index=round_index,
            )
            if not latest_messages:
                continue
            context_lines = [
                f"- {agent_by_id[msg.from_agent_id]['name']}: {msg.message}"
                for msg in latest_messages
            ]
            discussion_prompt = (
                f"Original question: {prompt}\n\n"
                "Other agents responded:\n"
                + "\n".join(context_lines)
                + "\n\nConsidering these perspectives, what is your updated view?"
            )
            jobs.append((agent, latest_messages, discussion_prompt))

        async def _discuss(
            agent: dict[str, Any], discussion_prompt: str
        ) -> tuple[str, list[MessageDelivery], list[SelfMessage], str] | None:
            agent_id = str(agent["id"])

            try:
                response, tools_used = await call(agent, discussion_prompt)
            except Exception as exc:
                err = f"[error: {exc}]"
                return agent_id, [], [("agent_error", err)], err

            return agent_id, [], _self_messages(response, tools_used), response

        results = await asyncio.gather(*[_discuss(agent, p) for agent, _, p in jobs])

        for (_agent, latest_messages, _), result in zip(jobs, results, strict=True):
            if result is None:
                continue
            agent_id, _, self_messages, _new_resp = result
            source_messages = {msg.from_agent_id: msg for msg in latest_messages}
            deliveries: list[MessageDelivery] = [
                (msg.from_agent_id, agent_id, msg.message) for msg in latest_messages
            ]
            await _persist_agent_deliveries(
                db, round_id, deliveries, "agent_to_agent", source_messages
            )
            await _persist_self_messages(db, round_id, agent_id, self_messages)
        previous_topology_round_id = round_id


# Mode 2: weighted opinion pooling


_WEIGHT_BLEND = 0.5  # how much old trust to retain each round (EMA factor)
_WEIGHT_EPSILON = 0.05  # max trust change to declare convergence


async def _run_weighted_opinion_pool(
    prompt: str,
    agents: list[dict[str, Any]],
    call: _AgentCall,
    db: AsyncConnection,
    rounds: int,
    agent_context: dict[str, str] | None,
    trial_id: str,
) -> None:
    agent_by_id = {a["id"]: a for a in agents}
    await _persist_system_broadcast(
        db,
        trial_id,
        agents,
        prompt,
        "weighted_opinion_pooling_broadcast",
    )
    broadcast_output_round_id = await _create_self_message_round(
        db, trial_id, 2, "weighted_opinion_pooling_broadcast_outputs"
    )

    async def _broadcast(
        agent: dict[str, Any],
    ) -> tuple[str, list[SelfMessage]]:
        agent_id = str(agent["id"])
        try:
            response, tools = await call(agent, _with_context(prompt, agent_id, agent_context))
        except Exception as exc:
            err = f"[error: {exc}]"
            return err, [("agent_error", err)]
        return response, _self_messages(response, tools)

    bcast = await asyncio.gather(*[_broadcast(a) for a in agents])
    for agent, (_resp, self_messages) in zip(agents, bcast, strict=True):
        agent_id = str(agent["id"])
        await _persist_self_messages(db, broadcast_output_round_id, agent_id, self_messages)

    previous_topology_round_id: int | None = None
    for round_num in range(1, rounds + 1):
        round_index = round_num + 2
        round_id = await create_round(db, trial_id, round_index, "weighted_opinion_pooling")
        has_topology = await _ensure_round_topology(
            db,
            trial_id=trial_id,
            round_id=round_id,
            round_index=round_index,
            agents=agents,
            previous_topology_round_id=previous_topology_round_id,
        )
        if not has_topology:
            break

        jobs: list[tuple[dict[str, Any], list[AgentMessage], dict[str, float], str]] = []
        for agent in agents:
            agent_id = str(agent["id"])
            nbrs = await _load_incoming_agent_ids(db, round_id, agent_id)
            latest_messages = await _load_latest_outputs_for_senders(
                db,
                trial_id=trial_id,
                sender_ids=nbrs,
                before_round_index=round_index,
            )
            if not latest_messages:
                continue
            weights = await _load_latest_trust_weights(
                db,
                trial_id=trial_id,
                agent_id=agent_id,
                neighbour_ids=[msg.from_agent_id for msg in latest_messages],
                before_round_index=round_index,
            )
            context_lines = [
                f"- {agent_by_id[msg.from_agent_id]['name']} "
                f"(trust {weights.get(msg.from_agent_id, 0.0):.2f}): {msg.message}"
                for msg in latest_messages
            ]
            discussion_prompt = (
                f"Original question: {prompt}\n\n"
                "Other agents responded (weighted by your trust in them):\n"
                + "\n".join(context_lines)
                + "\n\nGiving more weight to higher-trust voices, what is your updated answer?"
            )
            jobs.append((agent, latest_messages, weights, discussion_prompt))

        async def _discuss(
            agent: dict[str, Any], discussion_prompt: str
        ) -> tuple[str, list[MessageDelivery], list[SelfMessage], str] | None:
            agent_id = str(agent["id"])

            try:
                resp, tools = await call(agent, discussion_prompt)
            except Exception as exc:
                err = f"[error: {exc}]"
                return agent_id, [], [("agent_error", err)], err

            return agent_id, [], _self_messages(resp, tools), resp

        results = await asyncio.gather(*[_discuss(agent, p) for agent, _, _, p in jobs])

        new_responses: dict[str, str] = {}
        latest_by_agent: dict[str, list[AgentMessage]] = {}
        old_weights_by_agent: dict[str, dict[str, float]] = {}
        for (_agent, latest_messages, weights, _), result in zip(jobs, results, strict=True):
            if result is None:
                continue
            agent_id, _, self_messages, new_resp = result
            source_messages = {msg.from_agent_id: msg for msg in latest_messages}
            deliveries: list[MessageDelivery] = [
                (msg.from_agent_id, agent_id, msg.message) for msg in latest_messages
            ]
            await _persist_agent_deliveries(
                db, round_id, deliveries, "weighted_agent_to_agent", source_messages
            )
            await _persist_self_messages(db, round_id, agent_id, self_messages)
            new_responses[agent_id] = new_resp
            latest_by_agent[agent_id] = latest_messages
            old_weights_by_agent[agent_id] = weights

        # Trust update: increase weight on neighbours whose latest reply
        # agrees most (Jaccard) with the agent's own latest reply.
        max_trust_change = 0.0
        for aid, my_new in new_responses.items():
            latest_messages = latest_by_agent.get(aid, [])
            nbrs = [msg.from_agent_id for msg in latest_messages]
            if not nbrs:
                continue
            sims: dict[str, float] = {}
            latest_text_by_sender = {msg.from_agent_id: msg.message for msg in latest_messages}
            for n in nbrs:
                sims[n] = _jaccard(my_new, new_responses.get(n, latest_text_by_sender.get(n, "")))
            total = sum(sims.values())
            target = (
                {n: s / total for n, s in sims.items()}
                if total > 0
                else {n: 1.0 / len(nbrs) for n in nbrs}
            )
            old = old_weights_by_agent.get(aid, {})
            updated = {
                n: _WEIGHT_BLEND * old.get(n, 1.0 / len(nbrs)) + (1 - _WEIGHT_BLEND) * target[n]
                for n in nbrs
            }
            agent_max_change = 0.0
            for n in nbrs:
                change = abs(updated[n] - old.get(n, 1.0 / len(nbrs)))
                agent_max_change = max(agent_max_change, change)
                max_trust_change = max(max_trust_change, change)
            await _persist_trust_update(db, round_id, aid, updated, agent_max_change)

        previous_topology_round_id = round_id

        if max_trust_change < _WEIGHT_EPSILON:
            break


# Mode 3: plurality voting


_VOTE_STABILITY_K = 2  # consecutive rounds the plurality must hold to converge


async def _run_voting(
    prompt: str,
    agents: list[dict[str, Any]],
    call: _AgentCall,
    db: AsyncConnection,
    rounds: int,
    agent_context: dict[str, str] | None,
    trial_id: str,
) -> None:
    agent_by_id = {a["id"]: a for a in agents}
    next_round_index = 1
    await _persist_system_broadcast(
        db,
        trial_id,
        agents,
        prompt,
        "plurality_voting_broadcast",
        next_round_index,
    )
    next_round_index += 1
    broadcast_output_round_id = await _create_self_message_round(
        db, trial_id, next_round_index, "plurality_voting_broadcast_outputs"
    )
    next_round_index += 1

    async def _collect_initial_vote(
        agent: dict[str, Any],
    ) -> tuple[str, str | None, str | None, list[SelfMessage]]:
        """Ask one agent for its independent first-round vote.

        The initial voting pass gives each agent only the original prompt plus
        any private context. The required ``REASON:`` / ``VOTE:`` instructions
        are appended here so the result can be parsed and tallied before later
        topology-aware discussion rounds.
        """
        agent_id = str(agent["id"])
        full_prompt = _with_context(prompt, agent_id, agent_context) + _VOTE_INSTRUCTION
        try:
            response, tools = await call(agent, full_prompt)
        except Exception as exc:
            err = f"[error: {exc}]"
            return err, None, None, [("agent_error", err)]
        vote = _extract_vote(response)
        reason = _extract_reason(response)
        return response, vote, reason, _self_messages(response, tools)

    bcast = await asyncio.gather(*[_collect_initial_vote(a) for a in agents])
    for agent, (_resp, _vote, _reason, self_messages) in zip(agents, bcast, strict=True):
        agent_id = str(agent["id"])
        await _persist_self_messages(db, broadcast_output_round_id, agent_id, self_messages)

    votes, reasons, _responses = await _load_latest_votes(
        db, trial_id=trial_id, agents=agents, before_round_index=next_round_index
    )
    plurality, counts = _tally(votes)
    tally_message = _format_tally(plurality, counts)
    await record_message(
        db,
        broadcast_output_round_id,
        None,
        None,
        "vote_tally",
        tally_message,
        {"plurality": plurality, "counts": counts, "reasons": reasons},
    )

    # The broadcast already produced one round of votes — count it toward the
    # stability streak so a single matching follow-up converges (broadcast +
    # 1 follow-up = 2 vote rounds total).
    stable_streak = 1
    last_plurality = plurality

    previous_topology_round_id: int | None = None

    # main round loop
    for _ in range(rounds):
        round_index = next_round_index
        # cretae a new entry in "rounds" table
        round_id = await create_round(db, trial_id, round_index, "plurality_voting")
        next_round_index += 1

        # retrieve current rounds topology from "connections" table
        has_topology = await _ensure_round_topology(
            db,
            trial_id=trial_id,
            round_id=round_id,
            round_index=round_index,
            agents=agents,
            previous_topology_round_id=previous_topology_round_id,
        )

        # gather previous rounds tally and reasons, for discussion prompt
        tally_msg = _format_tally(plurality, counts)
        reasons_msg = _format_vote_reasons(agents, votes, reasons)
        votes, reasons, responses = await _load_latest_votes(
            db, trial_id=trial_id, agents=agents, before_round_index=round_index
        )

        async def _discuss(
            agent: dict[str, Any],
            full_prompt: str,
            deliveries: list[MessageDelivery],
        ) -> tuple[
            str,
            list[MessageDelivery],
            str,
            list[SelfMessage],
            str,
            str | None,
            str | None,
        ]:
            """Agents generate a new output, weighing in the incoming outouts of connected agents"""

            agent_id = str(agent["id"])
            delivery_type = (
                "voting_agent_to_agent" if deliveries[0][0] is not None else "voting_tally"
            )

            try:
                resp, tools = await call(agent, full_prompt)
            except Exception as exc:
                err = f"[error: {exc}]"
                return agent_id, deliveries, delivery_type, [("agent_error", err)], err, None, None
            v = _extract_vote(resp)
            r = _extract_reason(resp)
            return agent_id, deliveries, delivery_type, _self_messages(resp, tools), resp, v, r

        jobs: list[tuple[dict[str, Any], list[AgentMessage], str, list[MessageDelivery]]] = []
        source_messages_by_agent: dict[str, dict[str, AgentMessage]] = {}

        # 1) build the per-agent-prompts from neighbouring agents outputs
        # 2) call _dicuss() using the full_prompt
        for agent in agents:
            agent_id = str(agent["id"])
            own_prev = responses.get(agent_id, "")
            was_unknown = (votes.get(agent_id) or "unknown") in _ZERO_SCORE_VOTES
            unknown_nudge = (
                "\nYou voted 'unknown' last round because you lacked information. "
                "One of your connected agents may now have provided that information — "
                "if their reason is grounded in a file or specific source, adopt their "
                "answer rather than staying 'unknown'."
                if was_unknown
                else ""
            )
            source_nudge = (
                "\nWhen two agents disagree, prefer the answer backed by a specific "
                "file, quote, or source over an unsupported opinion."
            )
            senders = await _load_incoming_agent_ids(db, round_id, agent_id) if has_topology else []
            latest_messages = await _load_latest_outputs_for_senders(
                db,
                trial_id=trial_id,
                sender_ids=senders,
                before_round_index=round_index,
            )
            if latest_messages:
                neighbour_lines = [
                    f"- {agent_by_id[msg.from_agent_id]['name']} voted "
                    f"'{votes.get(msg.from_agent_id) or 'unknown'}': "
                    f"{reasons.get(msg.from_agent_id) or 'No reason provided.'}"
                    for msg in latest_messages
                ]
                full_prompt = (
                    f"Original question: {prompt}\n\n"
                    f"Your previous answer:\n{own_prev}\n\n"
                    "Your connected agents responded:\n"
                    + "\n".join(neighbour_lines)
                    + "\n\nReconsider your answer in light of your connected agents' "
                    "reasoning. Keep your REASON grounded in quotes and "
                    "files/sources when available."
                    + unknown_nudge
                    + source_nudge
                    + _VOTE_INSTRUCTION
                )
                deliveries: list[MessageDelivery] = [
                    (msg.from_agent_id, agent_id, msg.message) for msg in latest_messages
                ]
            else:
                full_prompt = (
                    f"Original question: {prompt}\n\n"
                    f"Your previous answer:\n{own_prev}\n\n"
                    f"Current vote tally:\n{tally_msg}\n\n"
                    f"Reasons submitted by agents:\n{reasons_msg}\n\n"
                    "Reconsider your answer in light of the reasoning of other agents. "
                    "Keep your REASON grounded in quotes and files/sources when available."
                    + unknown_nudge
                    + source_nudge
                    + _VOTE_INSTRUCTION
                )
                deliveries = [(None, agent_id, f"{tally_msg}\n\n{reasons_msg}")]
            source_messages_by_agent[agent_id] = {msg.from_agent_id: msg for msg in latest_messages}
            jobs.append((agent, latest_messages, full_prompt, deliveries))

        # agent-wise discussion
        results = await asyncio.gather(
            *[
                _discuss(agent, full_prompt, deliveries)
                for agent, _, full_prompt, deliveries in jobs
            ]
        )
        # store inter-agent messages in DB
        for agent_id, deliveries, delivery_type, self_messages, _resp, _vote, _reason in results:
            await _persist_agent_deliveries(
                db,
                round_id,
                deliveries,
                delivery_type,
                source_messages_by_agent.get(agent_id),
            )
            # store self-addressed messages for tracking individual agent output
            await _persist_self_messages(db, round_id, agent_id, self_messages)

        # retrieve votes from agent outputs
        votes, reasons, _responses = await _load_latest_votes(
            db, trial_id=trial_id, agents=agents, before_round_index=next_round_index
        )
        plurality, counts = _tally(votes)
        tally_message = _format_tally(plurality, counts)

        # generate a system message including the final round tally
        await record_message(
            db,
            round_id,
            None,
            None,
            "vote_tally",
            tally_message,
            {"plurality": plurality, "counts": counts, "reasons": reasons},
        )

        if plurality is not None and plurality == last_plurality:
            stable_streak += 1
        else:
            stable_streak = 1
        last_plurality = plurality
        previous_topology_round_id = round_id

        if stable_streak >= _VOTE_STABILITY_K:
            break
