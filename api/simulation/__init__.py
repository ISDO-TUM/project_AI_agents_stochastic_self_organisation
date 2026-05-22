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

- ``broadcast_no_consensus``: discussion-only, no consensus operator. Returns no
  final answer; useful for free-form exploration.
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
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import aiosqlite

from api.db import (
    create_round,
    create_trial,
    deserialise_agent_row,
    hint_files_in_prompt,
    load_agent_file_names,
    record_message,
)
from api.llm import call_agent
from api.schemas import SimulationStep, ToolCall

ConsensusMode = Literal[
    "broadcast_no_consensus",
    "weighted_opinion_pooling",
    "plurality_voting",
]

# ── helpers ───────────────────────────────────────────────────────────────────


def _ts() -> str:
    d = datetime.now()
    return f"{d.hour:02d}:{d.minute:02d}:{d.second:02d}"


def _step(**kwargs: Any) -> SimulationStep:
    return SimulationStep(id=str(uuid.uuid4()), ts=_ts(), **kwargs)


async def _call_agent(
    agent: dict[str, Any], prompt: str, db: aiosqlite.Connection
) -> tuple[str, list[ToolCall]]:
    """Invoke an agent and return (response_text, tools_used)."""
    file_names = await load_agent_file_names(db, agent["id"])
    system_prompt = hint_files_in_prompt(agent["system_prompt"] or None, file_names)
    response, tools_used = await call_agent(
        prompt,
        provider=agent["provider"],
        model=agent["model"],
        system_prompt=system_prompt,
        tool_names=agent["tools"] or None,
        tool_context={"db": db, "agent_id": agent["id"]},
    )
    return str(response), tools_used


def _tool_steps(tools_used: list[ToolCall], node_id: str) -> list[SimulationStep]:
    """Convert tool calls into SimulationStep log entries, one entry per tool name."""
    # Keep only the last call per tool (e.g. files: list → read → show the read)
    last_by_name: dict[str, ToolCall] = {}
    for tool in tools_used:
        last_by_name[tool.name] = tool
    out = []
    for tool in last_by_name.values():
        input_summary = " · ".join(f"**{k}:** `{v}`" for k, v in tool.input.items())
        output = tool.output.strip()
        output_block = f"```\n{output}\n```" if "\n" in output else output
        out.append(
            _step(
                label=tool.name,
                msg=f"action: {input_summary}\n\n**Result:**\n{output_block}",
                type="tool",
                node_id=node_id,
            )
        )
    return out


def _with_context(prompt: str, agent_id: str, agent_context: dict[str, str] | None) -> str:
    """Prepend an agent's private context to its prompt, if any."""
    if agent_context and agent_id in agent_context and agent_context[agent_id]:
        return f"Your private context:\n{agent_context[agent_id]}\n\n{prompt}"
    return prompt


def _jaccard(a: str, b: str) -> float:
    """Token-set Jaccard similarity. Cheap, no LLM/embedding dependency."""
    sa = set(a.lower().split())
    sb = set(b.lower().split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _centroid_response(responses: dict[str, str]) -> tuple[str | None, str | None]:
    """The reply most similar to all others (highest summed Jaccard).

    Returns (centroid_text, centroid_agent_id) — both None if no replies.
    """
    if not responses:
        return None, None
    items = list(responses.items())
    if len(items) == 1:
        aid, r = items[0]
        return r, aid
    best_id, best_text, best_score = None, None, -1.0
    for aid, r in items:
        score = sum(_jaccard(r, other) for oaid, other in items if oaid != aid)
        if score > best_score:
            best_score, best_id, best_text = score, aid, r
    return best_text, best_id


_REASON_RE = re.compile(r"^\s*REASON:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_VOTE_RE = re.compile(r"^\s*VOTE:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
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
    db: aiosqlite.Connection,
    trial_id: str,
    agents: list[dict[str, Any]],
    prompt: str,
    phase: str,
) -> int:
    """Record the initial one-way SYSTEM prompt sent to every agent."""
    round_id = int(await create_round(db, trial_id, 0, phase))
    for agent in agents:
        await record_message(db, round_id, None, str(agent["id"]), "system_broadcast", prompt)
    return round_id


async def _persist_agent_deliveries(
    db: aiosqlite.Connection,
    round_id: int,
    deliveries: list[tuple[str | None, str, str]],
    message_type: str,
) -> None:
    """Record directed agent-to-agent payloads delivered during a round."""
    for from_agent_id, to_agent_id, message in deliveries:
        await record_message(
            db,
            round_id,
            from_agent_id,
            to_agent_id,
            message_type,
            message,
        )


# ── outcome ───────────────────────────────────────────────────────────────────


@dataclass
class SimulationOutcome:
    steps: list[SimulationStep] = field(default_factory=list)
    consensus: str | None = None
    consensus_agent_id: str | None = None
    converged: bool = False
    rounds_used: int = 0


# ── public interface ──────────────────────────────────────────────────────────


async def run_topology(
    prompt: str,
    db: aiosqlite.Connection,
    rounds: int = 3,
    mode: ConsensusMode = "broadcast_no_consensus",
    agent_context: dict[str, str] | None = None,
) -> SimulationOutcome:
    """Run a topology simulation under the chosen consensus mode."""
    async with db.execute("SELECT * FROM agents") as cur:
        rows = await cur.fetchall()
    agents: list[dict[str, Any]] = [deserialise_agent_row(row) for row in rows]

    if not agents:
        return SimulationOutcome()

    incoming = _build_incoming(agents)
    trial_id = await create_trial(db, prompt, _trial_description(mode), mode)

    if mode == "weighted_opinion_pooling":
        return await _run_weighted_opinion_pool(
            prompt, agents, incoming, db, rounds, agent_context, trial_id
        )
    if mode == "plurality_voting":
        return await _run_voting(prompt, agents, incoming, db, rounds, agent_context, trial_id)
    return await _run_broadcast_no_consensus(
        prompt, agents, incoming, db, rounds, agent_context, trial_id
    )


# ── mode 1: broadcast (no consensus) ──────────────────────────────────────────


async def _run_broadcast_no_consensus(
    prompt: str,
    agents: list[dict[str, Any]],
    incoming: dict[str, list[str]],
    db: aiosqlite.Connection,
    rounds: int,
    agent_context: dict[str, str] | None,
    trial_id: str,
) -> SimulationOutcome:
    agent_by_id = {a["id"]: a for a in agents}
    steps: list[SimulationStep] = [
        _step(
            label="SYSTEM",
            msg=f"Broadcasting to {len(agents)} agent{'s' if len(agents) != 1 else ''}…",
            type="system",
        )
    ]
    await _persist_system_broadcast(db, trial_id, agents, prompt, "broadcast_no_consensus")

    async def _broadcast(agent: dict[str, Any]) -> tuple[str, list[SimulationStep]]:
        try:
            response, tools_used = await _call_agent(
                agent, _with_context(prompt, agent["id"], agent_context), db
            )
        except Exception as exc:
            err = f"[error: {exc}]"
            return err, [_step(label=agent["name"], msg=err, type="system", node_id=agent["id"])]
        agent_steps = _tool_steps(tools_used, agent["id"])
        agent_steps.append(
            _step(label=agent["name"], msg=response, type="system", node_id=agent["id"])
        )
        return response, agent_steps

    bcast = await asyncio.gather(*[_broadcast(a) for a in agents])
    responses: dict[str, str] = {}
    for agent, (response, agent_steps) in zip(agents, bcast, strict=True):
        responses[agent["id"]] = response
        steps.extend(agent_steps)

    rounds_used = 0
    for round_num in range(1, rounds + 1):
        if not any(incoming.values()):
            break
        rounds_used = round_num
        round_id = await create_round(db, trial_id, round_num, "discussion")

        steps.append(
            _step(
                label="SYSTEM",
                msg=f"Discussion round {round_num} — agents exchange responses…",
                type="system",
            )
        )

        async def _discuss(
            agent: dict[str, Any],
        ) -> tuple[str | None, list[SimulationStep], list[tuple[str | None, str, str]]]:
            senders = [sid for sid in incoming[agent["id"]] if sid in responses]
            if not senders:
                return None, [], []

            context_lines = [f"- {agent_by_id[sid]['name']}: {responses[sid]}" for sid in senders]
            discussion_prompt = (
                f"Original question: {prompt}\n\n"
                "Other agents responded:\n"
                + "\n".join(context_lines)
                + "\n\nConsidering these perspectives, what is your updated view?"
            )

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
            agent_id = str(agent["id"])
            deliveries: list[tuple[str | None, str, str]] = [
                (sid, agent_id, responses[sid]) for sid in senders
            ]

            try:
                response, tools_used = await _call_agent(agent, discussion_prompt, db)
            except Exception as exc:
                err = f"[error: {exc}]"
                return (
                    err,
                    [
                        *edge_steps,
                        _step(label=agent["name"], msg=err, type="system", node_id=agent["id"]),
                    ],
                    deliveries,
                )

            reply_steps = _tool_steps(tools_used, agent["id"])
            reply_steps.append(
                _step(label=agent["name"], msg=response, type="system", node_id=agent["id"])
            )
            return response, [*edge_steps, *reply_steps], deliveries

        results = await asyncio.gather(*[_discuss(a) for a in agents])

        new_responses: dict[str, str] = {}
        persisted_deliveries: list[tuple[str | None, str, str]] = []
        for agent, (new_resp, new_steps, deliveries) in zip(agents, results, strict=True):
            persisted_deliveries.extend(deliveries)
            if new_resp is not None:
                new_responses[agent["id"]] = new_resp
                steps.extend(new_steps)
        await _persist_agent_deliveries(db, round_id, persisted_deliveries, "agent_to_agent")
        responses.update(new_responses)

    steps.append(_step(label="SYSTEM", msg="Simulation complete.", type="system"))
    return SimulationOutcome(steps=steps, rounds_used=rounds_used)


# ── mode 2: weighted opinion pooling (Option A) ───────────────────────────────


_WEIGHT_BLEND = 0.5  # how much old trust to retain each round (EMA factor)
_WEIGHT_EPSILON = 0.05  # max trust change to declare convergence


async def _run_weighted_opinion_pool(
    prompt: str,
    agents: list[dict[str, Any]],
    incoming: dict[str, list[str]],
    db: aiosqlite.Connection,
    rounds: int,
    agent_context: dict[str, str] | None,
    trial_id: str,
) -> SimulationOutcome:
    agent_by_id = {a["id"]: a for a in agents}
    steps: list[SimulationStep] = [
        _step(
            label="SYSTEM",
            msg=f"Weighted opinion pooling — broadcasting to {len(agents)} agents.",
            type="system",
        )
    ]
    await _persist_system_broadcast(
        db,
        trial_id,
        agents,
        prompt,
        "weighted_opinion_pooling_broadcast",
    )

    # Each agent's trust over its own neighbours, uniform at start.
    trust: dict[str, dict[str, float]] = {}
    for a in agents:
        nbrs = incoming[a["id"]]
        trust[a["id"]] = {n: 1.0 / len(nbrs) for n in nbrs} if nbrs else {}

    async def _broadcast(agent: dict[str, Any]) -> tuple[str, list[SimulationStep]]:
        try:
            response, tools = await _call_agent(
                agent, _with_context(prompt, agent["id"], agent_context), db
            )
        except Exception as exc:
            err = f"[error: {exc}]"
            return err, [_step(label=agent["name"], msg=err, type="system", node_id=agent["id"])]
        agent_steps = _tool_steps(tools, agent["id"])
        agent_steps.append(
            _step(label=agent["name"], msg=response, type="system", node_id=agent["id"])
        )
        return response, agent_steps

    bcast = await asyncio.gather(*[_broadcast(a) for a in agents])
    responses: dict[str, str] = {}
    for agent, (resp, agent_steps) in zip(agents, bcast, strict=True):
        responses[agent["id"]] = resp
        steps.extend(agent_steps)

    # Snapshot broadcast replies for provenance-based routing attribution.
    broadcast_responses: dict[str, str] = dict(responses)

    rounds_used = 0
    converged = False

    for round_num in range(1, rounds + 1):
        if not any(incoming.values()):
            break
        rounds_used = round_num
        round_id = await create_round(db, trial_id, round_num, "weighted_opinion_pooling")

        steps.append(
            _step(
                label="SYSTEM",
                msg=f"Round {round_num} — weighted opinion pooling.",
                type="system",
            )
        )

        async def _discuss(
            agent: dict[str, Any],
        ) -> tuple[str | None, list[SimulationStep], list[tuple[str | None, str, str]]]:
            nbrs = [n for n in incoming[agent["id"]] if n in responses]
            if not nbrs:
                return None, [], []

            weights = trust[agent["id"]]
            context_lines = [
                f"- {agent_by_id[n]['name']} (trust {weights.get(n, 0.0):.2f}): {responses[n]}"
                for n in nbrs
            ]
            discussion_prompt = (
                f"Original question: {prompt}\n\n"
                "Other agents responded (weighted by your trust in them):\n"
                + "\n".join(context_lines)
                + "\n\nGiving more weight to higher-trust voices, what is your updated answer?"
            )

            edge_steps = [
                _step(
                    label=agent_by_id[n]["name"],
                    msg=responses[n],
                    type="agent-to-agent",
                    target=agent["name"],
                    from_id=n,
                    to_id=agent["id"],
                )
                for n in nbrs
            ]
            agent_id = str(agent["id"])
            deliveries: list[tuple[str | None, str, str]] = [
                (n, agent_id, responses[n]) for n in nbrs
            ]

            try:
                resp, tools = await _call_agent(agent, discussion_prompt, db)
            except Exception as exc:
                err = f"[error: {exc}]"
                return (
                    err,
                    [
                        *edge_steps,
                        _step(label=agent["name"], msg=err, type="system", node_id=agent["id"]),
                    ],
                    deliveries,
                )

            tool_s = _tool_steps(tools, agent["id"])
            tool_s.append(_step(label=agent["name"], msg=resp, type="system", node_id=agent["id"]))
            return resp, [*edge_steps, *tool_s], deliveries

        results = await asyncio.gather(*[_discuss(a) for a in agents])

        prev_responses = dict(responses)
        new_responses: dict[str, str] = {}
        persisted_deliveries: list[tuple[str | None, str, str]] = []
        for agent, (new_resp, new_steps, deliveries) in zip(agents, results, strict=True):
            persisted_deliveries.extend(deliveries)
            if new_resp is not None:
                new_responses[agent["id"]] = new_resp
                steps.extend(new_steps)
        await _persist_agent_deliveries(
            db, round_id, persisted_deliveries, "weighted_agent_to_agent"
        )

        # Trust update: increase weight on neighbours whose latest reply
        # agrees most (Jaccard) with the agent's own latest reply.
        max_trust_change = 0.0
        for a in agents:
            aid = a["id"]
            nbrs = incoming[aid]
            if not nbrs or aid not in new_responses:
                continue
            my_new = new_responses[aid]
            sims: dict[str, float] = {}
            for n in nbrs:
                nbr_text = new_responses.get(n, prev_responses.get(n, ""))
                sims[n] = _jaccard(my_new, nbr_text)
            total = sum(sims.values())
            target = (
                {n: s / total for n, s in sims.items()}
                if total > 0
                else {n: 1.0 / len(nbrs) for n in nbrs}
            )
            old = trust[aid]
            updated = {
                n: _WEIGHT_BLEND * old.get(n, 1.0 / len(nbrs)) + (1 - _WEIGHT_BLEND) * target[n]
                for n in nbrs
            }
            for n in nbrs:
                max_trust_change = max(
                    max_trust_change, abs(updated[n] - old.get(n, 1.0 / len(nbrs)))
                )
            trust[aid] = updated

        responses.update(new_responses)

        if max_trust_change < _WEIGHT_EPSILON:
            steps.append(
                _step(
                    label="SYSTEM",
                    msg=f"Converged after {round_num} round(s) — Δtrust={max_trust_change:.3f}.",
                    type="system",
                )
            )
            converged = True
            break

    consensus, _centroid_aid = _centroid_response(responses)

    # Provenance attribution: trace the consensus back to whichever agent's
    # *broadcast* (round-0) reply most resembled the final consensus string.
    # That points to the original information source rather than whichever
    # agent's final reply happened to be the most central in the cluster.
    consensus_aid: str | None = None
    if consensus is not None and broadcast_responses:
        consensus_aid = max(
            broadcast_responses.items(),
            key=lambda kv: _jaccard(kv[1], consensus),
        )[0]

    if consensus is not None:
        steps.append(
            _step(
                label="SYSTEM",
                msg=f"Selected consensus answer (centroid of replies):\n{consensus}",
                type="system",
                node_id=consensus_aid,
            )
        )
    steps.append(_step(label="SYSTEM", msg="Simulation complete.", type="system"))
    return SimulationOutcome(
        steps=steps,
        consensus=consensus,
        consensus_agent_id=consensus_aid,
        converged=converged,
        rounds_used=rounds_used,
    )


# ── mode 3: plurality voting (Option B) ───────────────────────────────────────


_VOTE_STABILITY_K = 2  # consecutive rounds the plurality must hold to converge


async def _run_voting(
    prompt: str,
    agents: list[dict[str, Any]],
    incoming: dict[str, list[str]],
    db: aiosqlite.Connection,
    rounds: int,
    agent_context: dict[str, str] | None,
    trial_id: str,
) -> SimulationOutcome:
    agent_by_id = {a["id"]: a for a in agents}
    steps: list[SimulationStep] = [
        _step(
            label="SYSTEM",
            msg=f"Plurality voting — broadcasting to {len(agents)} agents.",
            type="system",
        )
    ]
    await _persist_system_broadcast(
        db,
        trial_id,
        agents,
        prompt,
        "plurality_voting_broadcast",
    )

    async def _broadcast(
        agent: dict[str, Any],
    ) -> tuple[str, str | None, str | None, list[SimulationStep]]:
        full_prompt = _with_context(prompt, agent["id"], agent_context) + _VOTE_INSTRUCTION
        try:
            response, tools = await _call_agent(agent, full_prompt, db)
        except Exception as exc:
            err = f"[error: {exc}]"
            return (
                err,
                None,
                None,
                [_step(label=agent["name"], msg=err, type="system", node_id=agent["id"])],
            )
        vote = _extract_vote(response)
        reason = _extract_reason(response)
        agent_steps = _tool_steps(tools, agent["id"])
        agent_steps.append(
            _step(label=agent["name"], msg=response, type="system", node_id=agent["id"])
        )
        return response, vote, reason, agent_steps

    bcast = await asyncio.gather(*[_broadcast(a) for a in agents])
    responses: dict[str, str] = {}
    votes: dict[str, str | None] = {}
    reasons: dict[str, str | None] = {}
    for agent, (resp, vote, reason, agent_steps) in zip(agents, bcast, strict=True):
        responses[agent["id"]] = resp
        votes[agent["id"]] = vote
        reasons[agent["id"]] = reason
        steps.extend(agent_steps)

    # Snapshot the round-0 votes for provenance-based routing attribution.
    broadcast_votes: dict[str, str | None] = dict(votes)

    plurality, counts = _tally(votes)
    steps.append(_step(label="TALLY", msg=_format_tally(plurality, counts), type="system"))

    rounds_used = 0
    converged = False
    # The broadcast already produced one round of votes — count it toward the
    # stability streak so a single matching follow-up converges (broadcast +
    # 1 follow-up = 2 vote rounds total).
    stable_streak = 1
    last_plurality = plurality

    for round_num in range(1, rounds + 1):
        rounds_used = round_num
        round_id = await create_round(db, trial_id, round_num, "plurality_voting")
        steps.append(_step(label="SYSTEM", msg=f"Voting round {round_num}.", type="system"))
        tally_msg = _format_tally(plurality, counts)
        reasons_msg = _format_vote_reasons(agents, votes, reasons)

        async def _discuss(
            agent: dict[str, Any],
            tally_msg: str = tally_msg,
            reasons_msg: str = reasons_msg,
        ) -> tuple[
            str,
            str | None,
            str | None,
            list[SimulationStep],
            list[tuple[str | None, str, str]],
            str,
        ]:
            nbrs = [n for n in incoming[agent["id"]] if n in responses]
            own_prev = responses.get(agent["id"], "")

            was_unknown = (votes.get(agent["id"]) or "unknown") in _ZERO_SCORE_VOTES
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

            if nbrs:
                # Topology-aware: agent sees its own previous answer + only
                # connected neighbours' votes and reasons.
                neighbour_lines = [
                    f"- {agent_by_id[n]['name']} voted "
                    f"'{votes.get(n) or 'unknown'}': "
                    f"{reasons.get(n) or 'No reason provided.'}"
                    for n in nbrs
                ]
                edge_steps = [
                    _step(
                        label=agent_by_id[n]["name"],
                        msg=responses[n],
                        type="agent-to-agent",
                        target=agent["name"],
                        from_id=n,
                        to_id=agent["id"],
                    )
                    for n in nbrs
                ]
                agent_id = str(agent["id"])
                deliveries: list[tuple[str | None, str, str]] = [
                    (n, agent_id, responses[n]) for n in nbrs
                ]
                delivery_type = "voting_agent_to_agent"
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
            else:
                # Isolated agent: fall back to global tally so it isn't blind.
                edge_steps = []
                agent_id = str(agent["id"])
                deliveries = [(None, agent_id, f"{tally_msg}\n\n{reasons_msg}")]
                delivery_type = "voting_tally"
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

            try:
                resp, tools = await _call_agent(agent, full_prompt, db)
            except Exception as exc:
                err = f"[error: {exc}]"
                return (
                    err,
                    None,
                    None,
                    [
                        *edge_steps,
                        _step(label=agent["name"], msg=err, type="system", node_id=agent["id"]),
                    ],
                    deliveries,
                    delivery_type,
                )
            v = _extract_vote(resp)
            r = _extract_reason(resp)
            tool_s = _tool_steps(tools, agent["id"])
            tool_s.append(_step(label=agent["name"], msg=resp, type="system", node_id=agent["id"]))
            return resp, v, r, [*edge_steps, *tool_s], deliveries, delivery_type

        results = await asyncio.gather(*[_discuss(a) for a in agents])

        deliveries_by_type: dict[str, list[tuple[str | None, str, str]]] = {}
        for agent, (resp, vote, reason, agent_steps, deliveries, delivery_type) in zip(
            agents, results, strict=True
        ):
            deliveries_by_type.setdefault(delivery_type, []).extend(deliveries)
            responses[agent["id"]] = resp
            votes[agent["id"]] = vote
            reasons[agent["id"]] = reason
            steps.extend(agent_steps)
        for delivery_type, deliveries in deliveries_by_type.items():
            await _persist_agent_deliveries(db, round_id, deliveries, delivery_type)

        plurality, counts = _tally(votes)
        steps.append(_step(label="TALLY", msg=_format_tally(plurality, counts), type="system"))

        if plurality is not None and plurality == last_plurality:
            stable_streak += 1
        else:
            stable_streak = 1
        last_plurality = plurality

        if stable_streak >= _VOTE_STABILITY_K:
            steps.append(
                _step(
                    label="SYSTEM",
                    msg=f"Vote stable for {stable_streak} round(s) — converged.",
                    type="system",
                )
            )
            converged = True
            break

    # Provenance attribution: pick the first agent who voted for the final
    # plurality in the *broadcast* round, not the latest round. Late folders
    # are not the source of the answer; the round-0 voter is.
    consensus_aid = (
        next((aid for aid, v in broadcast_votes.items() if v == plurality), None)
        if plurality
        else None
    )
    steps.append(_step(label="SYSTEM", msg="Simulation complete.", type="system"))
    return SimulationOutcome(
        steps=steps,
        consensus=plurality,
        consensus_agent_id=consensus_aid,
        converged=converged,
        rounds_used=rounds_used,
    )
