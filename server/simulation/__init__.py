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
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import (
    create_round,
    create_trial,
    deserialise_agent_row,
    hint_files_in_prompt,
    load_files_by_agent,
    record_message,
)
from server.db.tables import agents as agents_table
from server.guardrails import build_guarded_system_prompt, sanitize_prompt
from server.guardrails.input_sanitizer import PromptInjectionError
from server.llm import call_agent
from server.schemas import ToolCall

ConsensusMode = Literal[
    "broadcast_no_consensus",
    "weighted_opinion_pooling",
    "plurality_voting",
    "bidding",
]

# Callable type for the bound agent-call closure passed into runner functions.
_AgentCall = Callable[[dict[str, Any], str], Awaitable[tuple[str, list[ToolCall]]]]

MessageDelivery = tuple[str | None, str, str]
SelfMessage = tuple[str, str]

# ── helpers ───────────────────────────────────────────────────────────────────


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
    deliveries: list[MessageDelivery],
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


# ── public interface ──────────────────────────────────────────────────────────


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
    incoming = _build_incoming(agents)
    if trial_id is None:
        trial_id = await create_trial(db, prompt, _trial_description(mode), mode)

    async def call(agent: dict[str, Any], prompt: str) -> tuple[str, list[ToolCall]]:
        return await _call_agent(agent, prompt, files_by_agent.get(agent["id"], {}), ruleset)

    if mode == "weighted_opinion_pooling":
        await _run_weighted_opinion_pool(
            prompt, agents, incoming, call, db, rounds, agent_context, trial_id
        )
        return
    if mode == "plurality_voting":
        await _run_voting(prompt, agents, incoming, call, db, rounds, agent_context, trial_id)
        return
    if mode == "bidding":
        await _run_bidding(
            prompt,
            agents,
            incoming,
            call,
            db,
            rounds,
            agent_context,
            trial_id,
            files_by_agent,
        )
        return
    await _run_broadcast_no_consensus(
        prompt, agents, incoming, call, db, rounds, agent_context, trial_id
    )


# ── mode 1: broadcast (no consensus) ──────────────────────────────────────────


async def _run_broadcast_no_consensus(
    prompt: str,
    agents: list[dict[str, Any]],
    incoming: dict[str, list[str]],
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
    responses: dict[str, str] = {}
    for agent, (response, self_messages) in zip(agents, bcast, strict=True):
        agent_id = str(agent["id"])
        await _persist_self_messages(db, broadcast_output_round_id, agent_id, self_messages)
        responses[agent_id] = response

    for round_num in range(1, rounds + 1):
        if not any(incoming.values()):
            break
        round_id = await create_round(db, trial_id, round_num + 2, "discussion")

        async def _discuss(
            agent: dict[str, Any],
        ) -> tuple[str, list[MessageDelivery], list[SelfMessage], str] | None:
            senders = [sid for sid in incoming[agent["id"]] if sid in responses]
            if not senders:
                return None

            context_lines = [f"- {agent_by_id[sid]['name']}: {responses[sid]}" for sid in senders]
            discussion_prompt = (
                f"Original question: {prompt}\n\n"
                "Other agents responded:\n"
                + "\n".join(context_lines)
                + "\n\nConsidering these perspectives, what is your updated view?"
            )

            agent_id = str(agent["id"])
            deliveries: list[MessageDelivery] = [(sid, agent_id, responses[sid]) for sid in senders]

            try:
                response, tools_used = await call(agent, discussion_prompt)
            except Exception as exc:
                err = f"[error: {exc}]"
                return agent_id, deliveries, [("agent_error", err)], err

            return agent_id, deliveries, _self_messages(response, tools_used), response

        results = await asyncio.gather(*[_discuss(a) for a in agents])

        new_responses: dict[str, str] = {}
        for result in results:
            if result is None:
                continue
            agent_id, deliveries, self_messages, new_resp = result
            await _persist_agent_deliveries(db, round_id, deliveries, "agent_to_agent")
            await _persist_self_messages(db, round_id, agent_id, self_messages)
            new_responses[agent_id] = new_resp
        responses.update(new_responses)


# ── mode 2: weighted opinion pooling (Option A) ───────────────────────────────


_WEIGHT_BLEND = 0.5  # how much old trust to retain each round (EMA factor)
_WEIGHT_EPSILON = 0.05  # max trust change to declare convergence


async def _run_weighted_opinion_pool(
    prompt: str,
    agents: list[dict[str, Any]],
    incoming: dict[str, list[str]],
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

    # Each agent's trust over its own neighbours, uniform at start.
    trust: dict[str, dict[str, float]] = {}
    for a in agents:
        nbrs = incoming[a["id"]]
        trust[a["id"]] = {n: 1.0 / len(nbrs) for n in nbrs} if nbrs else {}

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
    responses: dict[str, str] = {}
    for agent, (resp, self_messages) in zip(agents, bcast, strict=True):
        agent_id = str(agent["id"])
        await _persist_self_messages(db, broadcast_output_round_id, agent_id, self_messages)
        responses[agent_id] = resp

    for round_num in range(1, rounds + 1):
        if not any(incoming.values()):
            break
        round_id = await create_round(db, trial_id, round_num + 2, "weighted_opinion_pooling")

        async def _discuss(
            agent: dict[str, Any],
        ) -> tuple[str, list[MessageDelivery], list[SelfMessage], str] | None:
            nbrs = [n for n in incoming[agent["id"]] if n in responses]
            if not nbrs:
                return None

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

            agent_id = str(agent["id"])
            deliveries: list[MessageDelivery] = [(n, agent_id, responses[n]) for n in nbrs]

            try:
                resp, tools = await call(agent, discussion_prompt)
            except Exception as exc:
                err = f"[error: {exc}]"
                return agent_id, deliveries, [("agent_error", err)], err

            return agent_id, deliveries, _self_messages(resp, tools), resp

        results = await asyncio.gather(*[_discuss(a) for a in agents])

        prev_responses = dict(responses)
        new_responses: dict[str, str] = {}
        for result in results:
            if result is None:
                continue
            agent_id, deliveries, self_messages, new_resp = result
            await _persist_agent_deliveries(db, round_id, deliveries, "weighted_agent_to_agent")
            await _persist_self_messages(db, round_id, agent_id, self_messages)
            new_responses[agent_id] = new_resp

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
            break


# ── mode 3: plurality voting (Option B) ───────────────────────────────────────


_VOTE_STABILITY_K = 2  # consecutive rounds the plurality must hold to converge


async def _run_voting(
    prompt: str,
    agents: list[dict[str, Any]],
    incoming: dict[str, list[str]],
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

    async def _broadcast(
        agent: dict[str, Any],
    ) -> tuple[str, str | None, str | None, list[SelfMessage]]:
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

    bcast = await asyncio.gather(*[_broadcast(a) for a in agents])
    responses: dict[str, str] = {}
    votes: dict[str, str | None] = {}
    reasons: dict[str, str | None] = {}
    for agent, (resp, vote, reason, self_messages) in zip(agents, bcast, strict=True):
        agent_id = str(agent["id"])
        await _persist_self_messages(db, broadcast_output_round_id, agent_id, self_messages)
        responses[agent_id] = resp
        votes[agent_id] = vote
        reasons[agent_id] = reason

    plurality, counts = _tally(votes)
    tally_message = _format_tally(plurality, counts)
    await _persist_system_self_message(db, broadcast_output_round_id, "vote_tally", tally_message)

    # The broadcast already produced one round of votes — count it toward the
    # stability streak so a single matching follow-up converges (broadcast +
    # 1 follow-up = 2 vote rounds total).
    stable_streak = 1
    last_plurality = plurality

    for _ in range(1, rounds + 1):
        round_id = await create_round(db, trial_id, next_round_index, "plurality_voting")
        next_round_index += 1
        tally_msg = _format_tally(plurality, counts)
        reasons_msg = _format_vote_reasons(agents, votes, reasons)

        async def _discuss(
            agent: dict[str, Any],
            tally_msg: str = tally_msg,
            reasons_msg: str = reasons_msg,
        ) -> tuple[
            str,
            list[MessageDelivery],
            str,
            list[SelfMessage],
            str,
            str | None,
            str | None,
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
                agent_id = str(agent["id"])
                deliveries: list[MessageDelivery] = [(n, agent_id, responses[n]) for n in nbrs]
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
                resp, tools = await call(agent, full_prompt)
            except Exception as exc:
                err = f"[error: {exc}]"
                return agent_id, deliveries, delivery_type, [("agent_error", err)], err, None, None
            v = _extract_vote(resp)
            r = _extract_reason(resp)
            return agent_id, deliveries, delivery_type, _self_messages(resp, tools), resp, v, r

        results = await asyncio.gather(*[_discuss(a) for a in agents])

        for agent_id, deliveries, delivery_type, self_messages, resp, vote, reason in results:
            await _persist_agent_deliveries(db, round_id, deliveries, delivery_type)
            await _persist_self_messages(db, round_id, agent_id, self_messages)
            responses[agent_id] = resp
            votes[agent_id] = vote
            reasons[agent_id] = reason

        plurality, counts = _tally(votes)
        tally_message = _format_tally(plurality, counts)
        await _persist_system_self_message(db, round_id, "vote_tally", tally_message)

        if plurality is not None and plurality == last_plurality:
            stable_streak += 1
        else:
            stable_streak = 1
        last_plurality = plurality

        if stable_streak >= _VOTE_STABILITY_K:
            break


# ── mode 4: bidding ───────────────────────────────────────────────────────────

_BIDDING_INSTRUCTION = (
    "\n\n## BIDDING TASK\n"
    "You are participating in a bidding consensus. Before any work begins, "
    "you must produce *verifiable* evidence that you can contribute to the "
    "task above.\n\n"
    "REQUIRED steps:\n"
    "1. If you have a `files` tool, call it with action='list' to see your "
    "attached knowledge files.\n"
    "2. For EVERY file you intend to cite under `relevant_files`, you MUST "
    "first call `files` with action='read' to inspect its contents. "
    "Citations to files you have not actually read this turn will be "
    "REJECTED and stripped by the system.\n"
    "3. Respond with ONLY a single JSON object (no prose, no markdown "
    "fences) matching this schema exactly:\n\n"
    "{\n"
    '  "estimated_completeness": "full" | "partial" | "none",\n'
    '  "evidence": {\n'
    '    "relevant_tools": [<names of YOUR available tools that help>],\n'
    '    "relevant_files": [\n'
    "      {\n"
    '        "file_name": "<exact name of a file you actually read>",\n'
    '        "file_type": "<e.g. csv, md, txt>",\n'
    '        "relevance": "<one sentence: what in the file supports the task>"\n'
    "      }\n"
    "    ]\n"
    "  },\n"
    '  "gaps": [\n'
    "    {\n"
    '      "reason": "<what is missing for full completion>",\n'
    '      "expects": "<what input or other agent would close this gap>"\n'
    "    }\n"
    "  ],\n"
    '  "contribution": [\n'
    "    {\n"
    '      "data": "<one concrete statement your files/tools let you '
    'contribute toward the task>",\n'
    '      "citation": "<the source backing this statement: file name plus '
    "the file's date if present, e.g. 'nexora_overview_2024 (2024-09-01)'>\"\n"
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- Cite only tools you have been granted; fabricated tool names will "
    "be removed.\n"
    "- Cite only files you actually read this turn; the system verifies "
    "every file citation against your tool-call log.\n"
    "- Each entry in `contribution` is ONE statement plus ONE citation. "
    "Split multi-fact contributions across multiple entries. Other agents "
    "will see these verbatim during collaboration — make every statement "
    "load-bearing.\n"
    '- Use "none" for `estimated_completeness` if nothing in your evidence '
    "applies to the task; in that case set `contribution` to an empty array.\n"
)

_BIDDING_MATCHING_INSTRUCTION = (
    "\n\n## GAP MATCHING\n"
    "The blackboard below lists gaps posted by OTHER agents during the "
    "bidding phase. For each gap, decide whether YOU can *contribute* to "
    "filling it using your own tools and knowledge files.\n\n"
    "IMPORTANT: contributing does NOT mean fully resolving the gap. "
    "Partial, supporting, or complementary information counts. If anything "
    "in your files or tools is even tangentially useful to the gap — set "
    "can_contribute=true. Only set can_contribute=false if you have nothing "
    "at all that touches the gap.\n\n"
    "Verification rules are the same as before:\n"
    "- Cite only tools you have been granted.\n"
    "- For each file you cite, you MUST first call `files` with action='read' "
    "to inspect its contents this turn — un-read citations are rejected.\n\n"
    "Respond with ONLY a single JSON object (no prose, no markdown fences):\n\n"
    "{\n"
    '  "gap_coverage": [\n'
    "    {\n"
    '      "gap_id": "<exact gap_id from the blackboard>",\n'
    '      "can_contribute": true,\n'
    '      "evidence": {\n'
    '        "relevant_tools": [...],\n'
    '        "relevant_files": [\n'
    '          {"file_name": "...", "file_type": "...",\n'
    '           "relevance": "what part of the gap this helps with (even partially)"}\n'
    "        ]\n"
    "      },\n"
    '      "rationale": "<one sentence — partial contributions are fine>"\n'
    "    },\n"
    "    {\n"
    '      "gap_id": "<another gap_id>",\n'
    '      "can_contribute": false\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Include exactly one entry per gap on the blackboard. Set "
    "can_contribute=false (and omit evidence) only when you have nothing "
    "relevant — partial relevance is enough to set it true.\n\n"
    "Blackboard:\n"
)


def _extract_bid_json(text: str) -> dict[str, Any] | None:
    """Parse the agent's bidding response into a dict. Tolerates ``` fences."""
    s = text.strip()
    fence_match = re.match(r"^```(?:json|JSON)?\s*\n?(.*?)\n?```\s*$", s, re.DOTALL)
    if fence_match:
        s = fence_match.group(1).strip()
    try:
        parsed = json.loads(s)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    # Fallback: find the first balanced {...} object in the text
    depth = 0
    start = -1
    for i, c in enumerate(s):
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    obj = json.loads(s[start : i + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    start = -1
    return None


def _validate_evidence_block(
    raw_evidence: Any,
    available_tools: set[str],
    available_files: set[str],
    files_actually_read: set[str],
    tools_actually_used: set[str],
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """Strip fabricated tool/file citations from a single evidence block.

    Two unfakeable checks:
    - A cited tool is accepted only when it was granted to the agent AND was
      actually invoked during this turn (proven by the tool-call log). The
      LLM cannot fabricate a tool-call record.
    - A cited file is accepted only when it is attached to the agent AND the
      agent invoked ``files.read`` on it this turn — so the bid is grounded
      in the file's real contents, not in a name the LLM saw in the prompt.
    """
    rejections: dict[str, list[Any]] = {"tools": [], "files": []}
    evidence = raw_evidence if isinstance(raw_evidence, dict) else {}

    raw_tools = evidence.get("relevant_tools") or []
    valid_tools: list[str] = []
    if isinstance(raw_tools, list):
        for t in raw_tools:
            if not isinstance(t, str):
                rejections["tools"].append({"tool": t, "reason": "not a string"})
                continue
            # Strip provider-side display prefixes (e.g. Gemini's "functions.")
            # so the model can echo back whichever form it saw in its schema.
            normalised = t.split(".", 1)[1] if t.startswith("functions.") else t
            if normalised not in available_tools:
                rejections["tools"].append({"tool": t, "reason": "tool not granted to agent"})
                continue
            if normalised not in tools_actually_used:
                rejections["tools"].append({"tool": t, "reason": "tool was not invoked this turn"})
                continue
            valid_tools.append(normalised)

    raw_files = evidence.get("relevant_files") or []
    valid_files: list[dict[str, Any]] = []
    if isinstance(raw_files, list):
        for f in raw_files:
            if not isinstance(f, dict):
                rejections["files"].append({"value": f, "reason": "not an object"})
                continue
            name = f.get("file_name")
            if not isinstance(name, str) or not name:
                rejections["files"].append({"file_name": name, "reason": "missing file_name"})
                continue
            if name not in available_files:
                rejections["files"].append(
                    {"file_name": name, "reason": "file not attached to agent"}
                )
                continue
            if name not in files_actually_read:
                rejections["files"].append(
                    {"file_name": name, "reason": "file was not read via files.read this turn"}
                )
                continue
            valid_files.append(f)

    return {"relevant_tools": valid_tools, "relevant_files": valid_files}, rejections


def _has_evidence(bid: dict[str, Any]) -> bool:
    """True iff the (validated) bid contains any tool or file evidence."""
    ev = bid.get("evidence")
    if not isinstance(ev, dict):
        return False
    return bool(ev.get("relevant_tools") or ev.get("relevant_files"))


def _normalise_contribution(raw: Any) -> list[dict[str, str]]:
    """Coerce the LLM's `contribution` field to a list of ``{data, citation}``.

    Accepts:
    - a list of dicts → kept, with empty data entries dropped
    - a single string (legacy bids) → wrapped as one entry with no citation
    - anything else → empty list
    """
    if isinstance(raw, list):
        out: list[dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            data = item.get("data")
            data_str = data.strip() if isinstance(data, str) else ""
            if not data_str:
                continue
            citation = item.get("citation")
            citation_str = citation.strip() if isinstance(citation, str) else ""
            out.append({"data": data_str, "citation": citation_str})
        return out
    if isinstance(raw, str) and raw.strip():
        return [{"data": raw.strip(), "citation": ""}]
    return []


def _validate_bid(
    raw_bid: dict[str, Any],
    available_tools: list[str],
    available_files: set[str],
    files_actually_read: set[str],
    tools_actually_used: set[str],
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """Strip fabricated citations and return (validated_bid, rejections).

    Without any validated evidence the agent cannot contribute, so its gaps
    are dropped — it cannot post unmet needs to the blackboard if it has
    nothing to offer in return.
    """
    valid_evidence, rejections = _validate_evidence_block(
        raw_bid.get("evidence"),
        set(available_tools or []),
        available_files,
        files_actually_read,
        tools_actually_used,
    )
    contribution = _normalise_contribution(raw_bid.get("contribution"))
    validated = {
        "estimated_completeness": raw_bid.get("estimated_completeness"),
        "evidence": valid_evidence,
        "gaps": raw_bid.get("gaps") or [],
        "contribution": contribution,
    }
    if not _has_evidence(validated):
        validated["gaps"] = []
        validated["contribution"] = []
        validated["yielded"] = True
    return validated, rejections


def _validate_coverage(
    raw_response: dict[str, Any],
    available_tools: list[str],
    available_files: set[str],
    files_actually_read: set[str],
    tools_actually_used: set[str],
    known_gap_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, list[Any]]]:
    """Validate an agent's round-2 ``gap_coverage`` claims.

    Same unfakeable evidence checks as :func:`_validate_bid`, plus a gap-id
    existence check against the blackboard the agent was actually shown.
    """
    tools_set = set(available_tools or [])
    rejections: dict[str, list[Any]] = {
        "unknown_gap_ids": [],
        "tools": [],
        "files": [],
    }
    valid_entries: list[dict[str, Any]] = []

    raw_entries = raw_response.get("gap_coverage")
    if not isinstance(raw_entries, list):
        return [], rejections

    seen_gap_ids: set[str] = set()
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        gap_id = entry.get("gap_id")
        if not isinstance(gap_id, str) or gap_id not in known_gap_ids:
            rejections["unknown_gap_ids"].append(gap_id)
            continue
        if gap_id in seen_gap_ids:
            continue
        seen_gap_ids.add(gap_id)

        # Accept `can_contribute` (current) or `can_cover` (legacy) as the
        # affirmative flag.
        can_contribute = bool(entry.get("can_contribute", entry.get("can_cover")))
        if not can_contribute:
            valid_entries.append({"gap_id": gap_id, "can_contribute": False})
            continue

        valid_ev, ev_rej = _validate_evidence_block(
            entry.get("evidence"),
            tools_set,
            available_files,
            files_actually_read,
            tools_actually_used,
        )
        rejections["tools"].extend(ev_rej["tools"])
        rejections["files"].extend(ev_rej["files"])
        valid_entries.append(
            {
                "gap_id": gap_id,
                "can_contribute": True,
                "evidence": valid_ev,
                "rationale": entry.get("rationale"),
            }
        )
    return valid_entries, rejections


def _build_gap_blackboard(
    bids: dict[str, dict[str, Any]],
    agents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten validated bids into a blackboard list with stable gap ids."""
    name_by_id = {str(a["id"]): a.get("name") or str(a["id"]) for a in agents}
    blackboard: list[dict[str, Any]] = []
    for agent_id, bid in bids.items():
        gaps = bid.get("gaps") or []
        if not isinstance(gaps, list):
            continue
        for idx, gap in enumerate(gaps):
            blackboard.append(
                {
                    "gap_id": f"{agent_id}/g{idx}",
                    "agent_id": agent_id,
                    "agent_name": name_by_id.get(agent_id, agent_id),
                    "gap": gap,
                }
            )
    return blackboard


def _format_blackboard(entries: list[dict[str, Any]]) -> str:
    """Render blackboard entries as text for an agent prompt."""
    if not entries:
        return "(no gaps to match)"
    lines: list[str] = []
    for e in entries:
        gap = e.get("gap") or {}
        if isinstance(gap, dict):
            lines.append(
                f"- gap_id: {e['gap_id']}\n"
                f"  posted_by: {e['agent_name']}\n"
                f"  reason: {gap.get('reason', '')}\n"
                f"  expects: {gap.get('expects', '')}"
            )
        else:
            lines.append(f"- gap_id: {e['gap_id']}\n  posted_by: {e['agent_name']}\n  gap: {gap}")
    return "\n".join(lines)


def _select_collaborators(
    bids: dict[str, dict[str, Any]],
    coverage: dict[str, list[tuple[str, dict[str, Any]]]],
    blackboard: list[dict[str, Any]],
    agents: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pick the collaboration set and list any uncovered gaps.

    An agent is selected iff it provided non-empty validated evidence in
    round 1 (initial bid) OR round 2 (matching). Order is the agents-table
    order for determinism. Each collaborator is returned as
    ``{id, name, covers: [...]}``.
    """
    collaborator_ids: set[str] = set()

    for agent_id, bid in bids.items():
        ev = bid.get("evidence") if isinstance(bid.get("evidence"), dict) else {}
        if ev and (ev.get("relevant_tools") or ev.get("relevant_files")):
            collaborator_ids.add(agent_id)

    for covers in coverage.values():
        for agent_id, ev in covers:
            if ev and (ev.get("relevant_tools") or ev.get("relevant_files")):
                collaborator_ids.add(agent_id)

    gap_lookup = {e["gap_id"]: e for e in blackboard}

    uncovered: list[dict[str, Any]] = []
    covers_by_agent: dict[str, list[dict[str, Any]]] = {}
    for gid, covers in coverage.items():
        gap_entry = gap_lookup.get(gid)
        any_valid_cover = False
        for agent_id, ev in covers:
            if not (ev.get("relevant_tools") or ev.get("relevant_files")):
                continue
            any_valid_cover = True
            covers_by_agent.setdefault(agent_id, []).append(
                {
                    "gap_id": gid,
                    "posted_by": gap_entry["agent_name"] if gap_entry else None,
                    "gap": gap_entry["gap"] if gap_entry else None,
                }
            )
        if gap_entry is not None and not any_valid_cover:
            uncovered.append(
                {
                    "gap_id": gid,
                    "posted_by": gap_entry["agent_name"],
                    "gap": gap_entry["gap"],
                }
            )

    # Gaps that had no coverage attempts at all are also uncovered.
    for entry in blackboard:
        gid = entry["gap_id"]
        if gid in coverage:
            continue
        uncovered.append({"gap_id": gid, "posted_by": entry["agent_name"], "gap": entry["gap"]})

    ordered = [
        {
            "id": str(a["id"]),
            "name": str(a.get("name") or a["id"]),
            "contribution": (bids.get(str(a["id"])) or {}).get("contribution") or [],
            "covers": covers_by_agent.get(str(a["id"]), []),
        }
        for a in agents
        if str(a["id"]) in collaborator_ids
    ]
    return ordered, uncovered


def _format_findings(
    collaborators: list[dict[str, Any]],
    bids: dict[str, dict[str, Any]],
) -> str:
    """Render every collaborator's contribution entries with their citations."""
    lines: list[str] = []
    for c in collaborators:
        cid = str(c.get("id", ""))
        bid = bids.get(cid) or {}
        if bid.get("yielded"):
            continue
        contribution = bid.get("contribution") or []
        if not isinstance(contribution, list) or not contribution:
            continue
        name = c.get("name") or cid
        lines.append(f"- {name}:")
        for item in contribution:
            if not isinstance(item, dict):
                continue
            data = str(item.get("data") or "").strip()
            citation = str(item.get("citation") or "").strip()
            if not data:
                continue
            if citation:
                lines.append(f"    - {data}  [source: {citation}]")
            else:
                lines.append(f"    - {data}  [source: unspecified]")
    return "\n".join(lines) if lines else "(no findings declared)"


async def _run_sequential_collaboration(
    prompt: str,
    collaborators: list[dict[str, Any]],
    agents_by_id: dict[str, dict[str, Any]],
    bids: dict[str, dict[str, Any]],
    call: _AgentCall,
    db: AsyncConnection,
    trial_id: str,
    round_index: int,
    agent_context: dict[str, str] | None,
    passes: int = 2,
) -> str | None:
    """Sequentially produce a coherent answer across the collaborator set.

    For collaborators [A, B] and ``passes=2`` the chain is A → B → A → B.
    Every turn is shown each collaborator's ``contribution`` and cited
    sources from the bidding phase so agents can reconcile differences by
    looking at provenance rather than only their own file. The first agent
    drafts the answer; subsequent agents review the prior answer and revise
    it where needed. The last turn's response is returned.
    """
    chain = [c for _ in range(max(1, passes)) for c in collaborators]
    if not chain:
        return None

    round_id = int(await create_round(db, trial_id, round_index, "bidding_collaboration"))
    findings_block = _format_findings(collaborators, bids)
    findings_prelude = (
        "\n\n## FINDINGS COMPILED BY EACH AGENT (from the bidding phase)\n"
        "Every citation below has been independently verified by the system: "
        "the cited file exists, was attached to the cited agent, and was "
        "actually read by that agent during the bidding phase. Treat each "
        "cited finding as an ESTABLISHED FACT — you do NOT need to "
        'disclaim "I don\'t have access to that file" or hedge with '
        '"reportedly" / "according to other agents". The findings are part '
        "of the shared knowledge of this collaboration; cite them the same "
        "way you would cite a file you read yourself.\n\n"
        f"{findings_block}\n\n"
        "When findings disagree, reconcile by comparing the sources — "
        "prefer the one backed by the most recent source for present-tense "
        "questions ('current', 'now', 'today'). Do not default to only "
        "your own file.\n"
    )

    latest_output: str | None = None
    latest_author_name: str | None = None

    for turn_idx, collaborator in enumerate(chain):
        agent = agents_by_id.get(collaborator["id"])
        if agent is None:
            continue
        agent_id = str(agent["id"])
        turn_num = turn_idx + 1
        total_turns = len(chain)

        if latest_output is None:
            turn_prompt = _with_context(prompt, agent_id, agent_context) + (
                f"\n\n## COLLABORATIVE OUTPUT (turn {turn_num} of {total_turns})\n"
                "Your job is to generate a coherent answer to the user's "
                "question based on these findings. Use your own tools and "
                "knowledge files as needed to fill in any gaps.\n\n"
                "Answer AUTHORITATIVELY — do not write disclaimers like "
                '"I can only confirm from my own files…" or "I do not '
                'have access to file X". The findings block lists everything '
                "the collaboration has verified; cite sources by name, not "
                "by which agent personally read them." + findings_prelude
            )
        else:
            turn_prompt = _with_context(prompt, agent_id, agent_context) + (
                f"\n\n## COLLABORATIVE OUTPUT (turn {turn_num} of {total_turns})\n"
                "Your job is to review the previous agent's answer and "
                "revise it if needed, producing a coherent answer to the "
                "user's question based on these findings. Use your own "
                "tools and knowledge files as needed to fill in any gaps.\n\n"
                f"The previous agent ({latest_author_name or 'unknown'}) "
                f"wrote:\n\n---\n{latest_output}\n---\n\n"
                "Output the FULL revised answer — rewrite the whole thing, "
                "not just a diff.\n\n"
                "Answer AUTHORITATIVELY — do not write disclaimers like "
                '"I can only confirm from my own files…" or "I do not '
                'have access to file X". The findings block lists everything '
                "the collaboration has verified; cite sources by name, not "
                "by which agent personally read them." + findings_prelude
            )

        try:
            response, tools_used = await call(agent, turn_prompt)
        except Exception as exc:
            response = f"[error: {exc}]"
            tools_used = []

        await _persist_self_messages(db, round_id, agent_id, _self_messages(response, tools_used))

        # Record the handoff to the next agent in the chain (skip self-loops).
        if turn_idx + 1 < len(chain):
            next_id = str(chain[turn_idx + 1]["id"])
            if next_id != agent_id:
                await record_message(db, round_id, agent_id, next_id, "agent_to_agent", response)

        latest_output = response
        latest_author_name = collaborator.get("name") or agent_id

    return latest_output


def _fenced_json(obj: Any) -> str:
    """Render *obj* as a fenced ```json``` code block for the markdown UI."""
    return f"```json\n{json.dumps(obj, indent=2, default=str)}\n```"


def _files_read_from_tool_calls(tools_used: list[ToolCall]) -> set[str]:
    """Return the set of file names the agent actually read via files.read."""
    read: set[str] = set()
    for tc in tools_used:
        if tc.name != "files" or tc.input.get("action") != "read":
            continue
        name = tc.input.get("file_name")
        if isinstance(name, str) and name:
            read.add(name)
    return read


async def _run_bidding(
    prompt: str,
    agents: list[dict[str, Any]],
    incoming: dict[str, list[str]],
    call: _AgentCall,
    db: AsyncConnection,
    rounds: int,
    agent_context: dict[str, str] | None,
    trial_id: str,
    files_by_agent: dict[str, dict[str, str]] | None = None,
) -> None:
    """Two-round bidding consensus producing a verified collaboration set.

    Round 1 — each agent submits a *proof bid* declaring which of its tools and
    knowledge files support the task, plus the gaps it cannot fill alone.
    Round 2 — each agent reads the other agents' gaps from a blackboard and
    declares which it can cover, again with verifiable evidence.
    Selection — agents with non-empty validated evidence in either round form
    the collaboration set. Uncovered gaps are reported.

    Every citation in either round is cross-checked against the agent's actual
    tool grants and tool-call log, so the proof cannot be faked.
    """
    files_by_agent = files_by_agent or {}
    await _persist_system_broadcast(db, trial_id, agents, prompt, "bidding_broadcast")
    bids_round_id = await _create_self_message_round(db, trial_id, 2, "bidding_bids")

    async def _bid(
        agent: dict[str, Any],
    ) -> tuple[str, list[SelfMessage], dict[str, Any] | None]:
        agent_id = str(agent["id"])
        full_prompt = _with_context(prompt, agent_id, agent_context) + _BIDDING_INSTRUCTION
        try:
            response, tools_used = await call(agent, full_prompt)
        except Exception as exc:
            err = f"[error: {exc}]"
            return agent_id, [("agent_error", err)], None

        files_actually_read = _files_read_from_tool_calls(tools_used)
        tools_actually_used = {tc.name for tc in tools_used}
        available_files = set(files_by_agent.get(agent["id"], {}).keys())
        # Only keep tool-call self-messages — the agent's raw JSON is shown
        # below as a formatted `bidding_bid` (no need to duplicate it).
        self_messages: list[SelfMessage] = [
            ("tool", _format_tool_message(tool)) for tool in _last_tool_calls(tools_used)
        ]

        raw_bid = _extract_bid_json(response)
        if raw_bid is None:
            # Parsing failed — surface the raw response so the user can debug.
            self_messages.append(("agent_output", response))
            self_messages.append(
                (
                    "bidding_rejection",
                    "Bid rejected: response did not contain a valid JSON object.",
                )
            )
            return agent_id, self_messages, None

        validated, rejections = _validate_bid(
            raw_bid,
            agent.get("tools") or [],
            available_files,
            files_actually_read,
            tools_actually_used,
        )
        self_messages.append(("bidding_bid", _fenced_json(validated)))
        if rejections["tools"] or rejections["files"]:
            self_messages.append(("bidding_rejection", _fenced_json(rejections)))
        if validated.get("yielded"):
            self_messages.append(
                (
                    "bidding_yield",
                    "Agent has no validated evidence — yielding (no gaps posted, "
                    "excluded from gap matching).",
                )
            )
        return agent_id, self_messages, validated

    bid_results = await asyncio.gather(*[_bid(a) for a in agents])
    bids: dict[str, dict[str, Any]] = {}
    for agent_id, self_messages, validated_bid in bid_results:
        await _persist_self_messages(db, bids_round_id, agent_id, self_messages)
        if validated_bid is not None:
            bids[agent_id] = validated_bid

    # ── Round 2: gap matching on a per-agent blackboard ──────────────────────
    blackboard = _build_gap_blackboard(bids, agents)
    coverage: dict[str, list[tuple[str, dict[str, Any]]]] = {}

    if blackboard:
        per_agent_board: dict[str, list[dict[str, Any]]] = {
            str(a["id"]): [e for e in blackboard if e["agent_id"] != str(a["id"])] for a in agents
        }
        blackboard_round_id = int(await create_round(db, trial_id, 3, "bidding_blackboard"))
        for agent in agents:
            agent_id = str(agent["id"])
            agent_bid = bids.get(agent_id)
            if agent_bid is None or agent_bid.get("yielded"):
                continue
            others = per_agent_board[agent_id]
            if not others:
                continue
            await record_message(
                db,
                blackboard_round_id,
                None,
                agent_id,
                "system_blackboard",
                _format_blackboard(others),
            )

        matching_round_id = await _create_self_message_round(db, trial_id, 4, "bidding_matching")

        async def _match(
            agent: dict[str, Any],
        ) -> tuple[str, list[SelfMessage], dict[str, dict[str, Any]]]:
            agent_id = str(agent["id"])
            # Yielders (no validated evidence in round 1) are excluded from matching.
            agent_bid = bids.get(agent_id)
            if agent_bid is None or agent_bid.get("yielded"):
                return agent_id, [], {}
            others = per_agent_board[agent_id]
            if not others:
                return agent_id, [], {}

            known_ids = {e["gap_id"] for e in others}
            match_prompt = (
                _with_context(prompt, agent_id, agent_context)
                + _BIDDING_MATCHING_INSTRUCTION
                + _format_blackboard(others)
            )
            try:
                response, tools_used = await call(agent, match_prompt)
            except Exception as exc:
                err = f"[error: {exc}]"
                return agent_id, [("agent_error", err)], {}

            files_actually_read = _files_read_from_tool_calls(tools_used)
            tools_actually_used = {tc.name for tc in tools_used}
            available_files = set(files_by_agent.get(agent["id"], {}).keys())
            # Tool-call messages only — `bidding_match` carries the formatted
            # response below, no need to duplicate the raw text.
            self_messages: list[SelfMessage] = [
                ("tool", _format_tool_message(tool)) for tool in _last_tool_calls(tools_used)
            ]

            raw = _extract_bid_json(response)
            if raw is None:
                self_messages.append(("agent_output", response))
                self_messages.append(
                    (
                        "bidding_rejection",
                        "Matching rejected: response did not contain a valid JSON object.",
                    )
                )
                return agent_id, self_messages, {}

            valid_entries, rejections = _validate_coverage(
                raw,
                agent.get("tools") or [],
                available_files,
                files_actually_read,
                tools_actually_used,
                known_ids,
            )
            self_messages.append(("bidding_match", _fenced_json({"gap_coverage": valid_entries})))
            if rejections["unknown_gap_ids"] or rejections["tools"] or rejections["files"]:
                self_messages.append(("bidding_rejection", _fenced_json(rejections)))

            agent_coverage = {
                entry["gap_id"]: entry.get("evidence") or {}
                for entry in valid_entries
                if entry.get("can_contribute")
            }
            return agent_id, self_messages, agent_coverage

        match_results = await asyncio.gather(*[_match(a) for a in agents])
        for agent_id, self_messages, agent_coverage in match_results:
            if self_messages:
                await _persist_self_messages(db, matching_round_id, agent_id, self_messages)
            for gap_id, ev in agent_coverage.items():
                coverage.setdefault(gap_id, []).append((agent_id, ev))

    # ── Selection ────────────────────────────────────────────────────────────
    collaborators, uncovered = _select_collaborators(bids, coverage, blackboard, agents)
    selection_round_id = await _create_self_message_round(db, trial_id, 5, "bidding_selection")
    await _persist_system_self_message(
        db,
        selection_round_id,
        "bidding_collaborators",
        _fenced_json({"collaborators": collaborators, "uncovered_gaps": uncovered}),
    )

    # ── Sequential refinement: collaborators take turns (two passes) ─────────
    if collaborators:
        agents_by_id = {str(a["id"]): a for a in agents}
        final_output = await _run_sequential_collaboration(
            prompt,
            collaborators,
            agents_by_id,
            bids,
            call,
            db,
            trial_id,
            round_index=6,
            agent_context=agent_context,
            passes=2,
        )
        if final_output is not None:
            final_round_id = await _create_self_message_round(
                db, trial_id, 7, "bidding_final_output"
            )
            await _persist_system_self_message(
                db, final_round_id, "bidding_final_output", final_output
            )
