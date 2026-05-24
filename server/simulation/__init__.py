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
    guarded_system_prompt = f"## CURRENT DATE\n{date.today().isoformat()}\n\n{guarded_system_prompt}"

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
            # Log and skip – don't abort the whole simulation
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
