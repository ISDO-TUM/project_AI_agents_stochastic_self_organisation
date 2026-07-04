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
import logging
import re
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Protocol

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
from server.llm.embeddings import cosine_similarity, embed_texts
from server.llm.langfuse_setup import agent_trace_metadata, langfuse_metadata
from server.schemas import ToolCall
from server.tools.builtin.registry import RegistryIndex
from server.tools.builtin.table import TableStore

logger = logging.getLogger(__name__)

ConsensusMode = Literal[
    "broadcast_no_consensus",
    "weighted_opinion_pooling",
    "plurality_voting",
    "bidding",
]


class _AgentCall(Protocol):
    """Bound agent-call closure passed into runner functions."""

    def __call__(
        self,
        agent: dict[str, Any],
        prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> Awaitable[tuple[str, list[ToolCall]]]: ...


MessageDelivery = tuple[str | None, str, str]
SelfMessage = tuple[str, str]

# ── helpers ───────────────────────────────────────────────────────────────────


async def _call_agent(
    agent: dict[str, Any],
    prompt: str,
    files: dict[str, str],
    ruleset: str | None = None,
    registry: RegistryIndex | None = None,
    tables: dict[str, TableStore] | None = None,
) -> tuple[str, list[ToolCall]]:
    """Invoke an agent and return (response_text, tools_used).

    `ruleset`, when provided, is prepended to the agent's system prompt so every
    LLM call in a simulation run automatically abides by the shared rules.

    The prompt is sanitised for injection attempts before being forwarded to the
    LLM.  The system prompt is wrapped with anti-hallucination guardrails.

    When a `registry` index is provided (dynamic topology), the `registry`
    discovery tool is offered to the agent and the index is passed in context so
    the agent can semantically search for peers before declaring its CONNECT
    line. The index is always placed in the tool context (it may be ``None``).
    """
    # Sanitise the incoming prompt (raises PromptInjectionError on attack)
    try:
        sanitize_prompt(prompt, field_name="simulation prompt")
    except PromptInjectionError as exc:
        return f"[GUARDRAIL BLOCKED] {exc}", []

    tool_names = list(agent["tools"] or [])
    if registry is not None and "registry" not in tool_names:
        tool_names.append("registry")

    file_names = list(files.keys())
    raw_system_prompt = hint_files_in_prompt(agent["system_prompt"] or None, file_names, tool_names)

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
        tool_names=tool_names or None,
        tool_context={
            "files": files,
            "registry": registry,
            "tables": tables if tables is not None else {},
            "agent_id": agent["id"],
        },
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


_COMMON_SENTENCE_STARTERS = frozenset(
    {
        "a",
        "about",
        "after",
        "all",
        "also",
        "always",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "based",
        "be",
        "because",
        "been",
        "before",
        "being",
        "both",
        "but",
        "by",
        "can",
        "could",
        "currently",
        "do",
        "does",
        "during",
        "each",
        "even",
        "every",
        "first",
        "for",
        "from",
        "get",
        "given",
        "had",
        "has",
        "have",
        "he",
        "her",
        "here",
        "his",
        "how",
        "however",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "just",
        "last",
        "let",
        "like",
        "make",
        "many",
        "may",
        "me",
        "might",
        "more",
        "most",
        "much",
        "must",
        "my",
        "never",
        "new",
        "next",
        "no",
        "none",
        "not",
        "now",
        "of",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "out",
        "over",
        "per",
        "please",
        "recent",
        "regarding",
        "run",
        "scope",
        "shall",
        "she",
        "should",
        "since",
        "so",
        "some",
        "still",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "under",
        "until",
        "up",
        "upon",
        "use",
        "using",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "will",
        "with",
        "would",
        "yes",
        "yet",
        "you",
        "your",
    }
)

_ALPHANUMERIC_CODE_RE = re.compile(r"^[A-Za-z]+-\d+[\w-]*$")
_CAMELCASE_RE = re.compile(r"[a-z][A-Z]")


def _extract_entities(text: str) -> set[str]:
    """Extract entity-like tokens: proper nouns, codes, abbreviations."""
    entities: set[str] = set()
    tokens = text.split()
    for i, raw in enumerate(tokens):
        cleaned = raw.strip(".,;:!?\"'()[]{}")
        if len(cleaned) < 2:
            continue
        if _ALPHANUMERIC_CODE_RE.match(cleaned):
            entities.add(cleaned.lower())
            continue
        if cleaned.isupper() and cleaned.isalpha():
            entities.add(cleaned.lower())
            continue
        if _CAMELCASE_RE.search(cleaned):
            entities.add(cleaned.lower())
            continue
        if cleaned[0].isupper() and not cleaned.isupper():
            at_sentence_start = i == 0 or tokens[i - 1][-1] in ".!?"
            if at_sentence_start and cleaned.lower() in _COMMON_SENTENCE_STARTERS:
                continue
            entities.add(cleaned.lower())
    return entities


_ENTITY_WEIGHT = 0.7
_TEXT_WEIGHT = 0.3


def _entity_aware_similarity(a: str, b: str) -> float:
    """Blended similarity: entity-set Jaccard (0.7) + full-text Jaccard (0.3).

    Falls back to text-only Jaccard when either text has no extractable entities.
    """
    text_sim = _jaccard(a, b)
    a_ents = _extract_entities(a)
    b_ents = _extract_entities(b)
    if not a_ents or not b_ents:
        return text_sim
    entity_sim = len(a_ents & b_ents) / len(a_ents | b_ents)
    return _ENTITY_WEIGHT * entity_sim + _TEXT_WEIGHT * text_sim


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


def _aggregate_trust(trust: dict[str, dict[str, float]]) -> dict[str, float]:
    """Sum incoming trust per agent — how much the group trusts each agent.

    For each target agent `t`, returns `sum over sources s of trust[s][t]`.
    Used by the weighted-pool consensus selector to weight agents' replies
    by how trustworthy the rest of the pool found them to be.
    """
    agg: dict[str, float] = {}
    for src_trust in trust.values():
        for target, w in src_trust.items():
            agg[target] = agg.get(target, 0.0) + w
    return agg


def _weighted_consensus(
    responses: dict[str, str],
    aggregate_trust: dict[str, float],
) -> tuple[str | None, str | None]:
    """Pick the reply from the agent the group trusts most.

    Falls back to ``_centroid_response`` when every agent has zero aggregate
    trust (e.g. a disconnected graph), so we still return a sensible answer
    instead of None.

    Ties are broken by reply length (longer = more informative) for
    determinism — without this two agents with identical aggregate trust
    would resolve to whichever the dict iteration happened to visit first.
    """
    if not responses:
        return None, None
    candidates = {aid: aggregate_trust.get(aid, 0.0) for aid in responses}
    if all(w <= 0.0 for w in candidates.values()):
        return _centroid_response(responses)
    best_id = max(
        responses.keys(),
        key=lambda aid: (candidates[aid], len(responses[aid])),
    )
    return responses[best_id], best_id


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

_WEIGHTED_POOL_INSTRUCTION = (
    "\n\nIMPORTANT: Reply with ONLY these three lines. "
    "No preamble, no extra text, no repetition.\n"
    "ANSWER: <a concrete answer — you MUST commit to one>\n"
    "SOURCE: <document name and key quote, or 'none'>\n"
    "REASONING: <one sentence why>\n\n"
    "Rules:\n"
    "- You must always give a definitive answer. Never answer "
    "'unknown', 'uncertain', or 'N/A'.\n"
    "- Either defend your own source or adopt a peer's answer "
    "if their source is more recent or authoritative.\n"
    "- Once you change your answer based on better evidence, "
    "do not revert to your previous answer.\n\n"
    "GOOD example (entire response):\n"
    "ANSWER: Acme Computers\n"
    "SOURCE: 2026_master_agreement.txt — 'Vendor: Acme Computers'\n"
    "REASONING: The master agreement names Acme as the sole supplier.\n\n"
    "BAD example — do NOT do this:\n"
    "Based on my analysis, I believe... ANSWER: Acme Computers ...\n"
)

_ANSWER_RE = re.compile(
    r"^\s*(?:>\s*)?(?:[-*+]\s*|\d+[.)]\s*)?(?:\*\*)?ANSWER(?:\*\*)?\s*[:\-]\s*(?:\*\*)?(.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_SOURCE_RE = re.compile(
    r"^\s*(?:>\s*)?(?:[-*+]\s*|\d+[.)]\s*)?(?:\*\*)?SOURCE(?:\*\*)?\s*[:\-]\s*(?:\*\*)?(.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_REASONING_RE = re.compile(
    r"^\s*(?:>\s*)?(?:[-*+]\s*|\d+[.)]\s*)?(?:\*\*)?REASONING(?:\*\*)?\s*[:\-]\s*(?:\*\*)?(.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def _extract_answer(text: str) -> str | None:
    """Pull the last ANSWER: ... line from a response."""
    matches = _ANSWER_RE.findall(text)
    if not matches:
        return None
    return matches[-1].strip() or None


def _extract_source(text: str) -> str | None:
    """Pull the last SOURCE: ... line from a response."""
    matches = _SOURCE_RE.findall(text)
    if not matches:
        return None
    return matches[-1].strip() or None


def _extract_reasoning(text: str) -> str | None:
    """Pull the last REASONING: ... line from a response."""
    matches = _REASONING_RE.findall(text)
    if not matches:
        return None
    return matches[-1].strip() or None


def _extract_structured_response(text: str) -> dict[str, str | None]:
    """Extract all structured fields from a weighted-pool response."""
    return {
        "answer": _extract_answer(text),
        "source": _extract_source(text),
        "reasoning": _extract_reasoning(text),
    }


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


# ── dynamic topology: discovery, selection, reputation ─────────────────────────
#
# These helpers power the optional ``dynamic`` topology, where agents rebuild the
# communication graph themselves each round. They are pure functions + small
# dataclasses with no DB access, so they are unit-tested in isolation. ``static``
# topology never touches any of this (see ``TopologyController``).

_CONNECT_RE = re.compile(r"^\s*CONNECT:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)


def _parse_connect(text: str) -> list[str]:
    """Pull agent ids from the last CONNECT: line (commas/spaces/brackets ok)."""
    matches = _CONNECT_RE.findall(text)
    if not matches:
        return []
    raw = matches[-1].strip().strip("[]")
    parts = [p.strip().strip("[]") for p in re.split(r"[,\s]+", raw)]
    return [p for p in parts if p]


def _apply_selection(
    declared: list[str],
    prior: list[str],
    valid_ids: set[str],
    reputation: dict[str, float],
    k: int,
    self_id: str,
) -> list[str]:
    """Resolve one agent's incoming neighbours for the next round.

    Drops invalid/self ids; if nothing valid remains, falls back to the previous
    round's neighbours (the floor); ranks by reputation; caps at k. A non-positive
    k means *unlimited* fan-out — every validly-declared peer is kept.
    """

    def _clean(ids: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for i in ids:
            if i in valid_ids and i != self_id and i not in seen:
                seen.add(i)
                out.append(i)
        return out

    candidates = _clean(declared) or _clean(prior)
    candidates.sort(key=lambda i: reputation.get(i, 0.5), reverse=True)
    return candidates if k <= 0 else candidates[:k]


def _grounded(text: str) -> bool:
    """Cheap grounding proxy: did the agent supply a REASON line?"""
    return _extract_reason(text) is not None


def _centroid_text(responses: dict[str, str]) -> str:
    """Cheap consensus proxy: all current-round responses joined."""
    return "\n".join(responses.values())


_REP_INIT = 0.5
_REP_ALPHA = 0.5  # EMA factor
_REP_W_GROUND = 0.5
_REP_W_AGREE = 0.5


@dataclass
class Reputation:
    """Running per-agent 'worth calling?' score in [0, 1].

    A deliberate slim stand-in for EigenTrust: each round an agent's score is
    nudged by whether it grounded its answer (supplied a REASON) and how much it
    agrees with the emerging consensus (Jaccard to the joined responses). Used to
    bias neighbour selection toward agents the group finds useful.
    """

    score: dict[str, float] = field(default_factory=dict)

    def update(self, responses: dict[str, str], consensus: str) -> None:
        for aid, resp in responses.items():
            ground = 1.0 if _grounded(resp) else 0.0
            agree = _jaccard(resp, consensus)
            signal = _REP_W_GROUND * ground + _REP_W_AGREE * agree
            old = self.score.get(aid, _REP_INIT)
            self.score[aid] = (1 - _REP_ALPHA) * old + _REP_ALPHA * signal


_CONNECT_INSTRUCTION = (
    "\n\nYou may choose who you hear from next round. Use the `registry` tool to "
    "discover relevant peers: action='search' with a short query describing the "
    "expertise you need, action='list' for the full roster, or action='get' to "
    "read one peer. Then end your response with a single line naming the agent "
    "ids you want to hear from next round (most useful first):\n"
    "CONNECT: <id>, <id>\n"
)


def _same_adjacency(a: dict[str, list[str]], b: dict[str, list[str]]) -> bool:
    if a.keys() != b.keys():
        return False
    return all(set(a[k]) == set(b[k]) for k in a)


@dataclass
class TopologyController:
    """Owns the per-round graph: static keeps it fixed, dynamic rewires it.

    The runners loop over a single ``incoming`` adjacency map and persist each
    round's deliveries from it. In ``static`` mode this controller is a no-op
    wrapper around the seed graph (byte-for-byte identical behaviour to before).
    In ``dynamic`` mode, ``prompt_suffix`` nudges each agent to use the registry
    tool and emit a ``CONNECT:`` line, and ``rewire`` rebuilds the directed graph
    from those declarations between rounds.
    """

    mode: str
    fanout: int
    agents: list[dict[str, Any]]
    incoming: dict[str, list[str]]
    reputation: Reputation
    converged: bool = False

    @classmethod
    def create(
        cls,
        mode: str,
        fanout: int,
        agents: list[dict[str, Any]],
        seed_incoming: dict[str, list[str]],
    ) -> TopologyController:
        return cls(
            mode=mode,
            fanout=fanout,
            agents=agents,
            incoming={k: list(v) for k, v in seed_incoming.items()},
            reputation=Reputation(),
        )

    def prompt_suffix(self, agent: dict[str, Any]) -> str:
        """Pull-model: tell the agent to use the registry tool + emit CONNECT.

        No peer directory is pushed — the agent fetches peers on demand. Returns
        an empty string in static mode so prompts are unchanged.
        """
        if self.mode != "dynamic":
            return ""
        return _CONNECT_INSTRUCTION

    def rewire(self, responses: dict[str, str]) -> dict[str, list[str]]:
        """Return the next round's incoming map. No-op (returns current) in static."""
        if self.mode != "dynamic":
            return self.incoming
        self.reputation.update(responses, _centroid_text(responses))
        valid_ids = {a["id"] for a in self.agents}
        new_incoming: dict[str, list[str]] = {}
        for a in self.agents:
            aid = a["id"]
            declared = _parse_connect(responses.get(aid, ""))
            new_incoming[aid] = _apply_selection(
                declared,
                self.incoming.get(aid, []),
                valid_ids,
                self.reputation.score,
                self.fanout,
                aid,
            )
        self.converged = _same_adjacency(self.incoming, new_incoming)
        self.incoming = new_incoming
        return self.incoming


# ── public interface ──────────────────────────────────────────────────────────


async def run_topology(
    prompt: str,
    db: AsyncConnection,
    rounds: int = 3,
    mode: ConsensusMode = "broadcast_no_consensus",
    agent_context: dict[str, str] | None = None,
    trial_id: str | None = None,
    ruleset: str | None = None,
    topology: str = "static",
    fanout: int = 3,
    user_id: str | None = None,
) -> None:
    """Run a topology simulation under the chosen consensus mode.

    All database reads happen here, up front and sequentially. Each agent's
    knowledge files are pre-loaded so the concurrent LLM phase never touches the
    connection (a single async connection cannot serve concurrent queries).

    ``topology`` selects how the communication graph evolves: ``static``
    (default) keeps the UI/seed graph fixed for the whole run, while ``dynamic``
    lets agents rebuild it each round by discovering peers through the registry
    tool and emitting CONNECT lines. ``fanout`` caps how many neighbours an agent
    may pick per round in dynamic mode. ``user_id`` restricts the run to that
    user's agents (plus legacy/shared rows); ``None`` keeps the full pool.
    """
    agents_stmt = select(agents_table)
    if user_id is not None:
        agents_stmt = agents_stmt.where(
            (agents_table.c.user_id == user_id) | (agents_table.c.user_id.is_(None))
        )
    result = await db.execute(agents_stmt)
    agents: list[dict[str, Any]] = [deserialise_agent_row(row) for row in result.mappings().all()]

    if not agents:
        return

    # Consensus is only meaningful with at least two communicating agents; a lone
    # agent has nothing to reconcile. Skip voting/pooling entirely so no empty
    # "no valid votes" tally is ever generated for a single-agent run.
    if len(agents) < 2:
        mode = "broadcast_no_consensus"

    files_by_agent = await load_files_by_agent(db)
    incoming = _build_incoming(agents)
    controller = TopologyController.create(topology, fanout, agents, incoming)
    # The semantic index is only built when discovery is actually enabled; static
    # runs pay no embedding cost and offer no registry tool (registry is None).
    registry = await RegistryIndex.build(agents, files_by_agent) if topology == "dynamic" else None
    if trial_id is None:
        trial_id = await create_trial(db, prompt, _trial_description(mode), mode)

    # One shared table workspace per run — agents in a pipeline see each other's
    # mutations (e.g. a predictor adds a column, a reviewer reads it) without
    # re-loading the file.
    shared_tables: dict[str, TableStore] = {}

    # Per-agent "last version seen" for each table — lets us nudge an agent to
    # re-read a table that a sibling mutated since this agent's previous turn,
    # since nothing else would otherwise tell it the data moved under it.
    table_versions_seen: dict[str, dict[str, int]] = {}

    def _table_change_notes(agent_id: str) -> str:
        seen = table_versions_seen.setdefault(agent_id, {})
        notes: list[str] = []
        for name, store in shared_tables.items():
            if store.df is None:
                continue
            last = seen.get(name)
            if last is not None and last != store.version:
                notes.append(
                    f"[Table '{name}' changed since your last turn — now at version "
                    f"{store.version}. Re-read it with 'table_query' before relying "
                    "on what you remember.]"
                )
            seen[name] = store.version
        return ("\n\n" + "\n".join(notes)) if notes else ""

    async def call(
        agent: dict[str, Any],
        prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, list[ToolCall]]:
        with langfuse_metadata(agent_trace_metadata(trial_id, agent, **(metadata or {}))):
            return await _call_agent(
                agent,
                prompt + _table_change_notes(agent["id"]),
                files_by_agent.get(agent["id"], {}),
                ruleset,
                registry=registry,
                tables=shared_tables,
            )

    if mode == "weighted_opinion_pooling":
        await _run_weighted_opinion_pool(
            prompt, agents, controller, call, db, rounds, agent_context, trial_id
        )
        return
    if mode == "plurality_voting":
        await _run_voting(prompt, agents, controller, call, db, rounds, agent_context, trial_id)
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
        prompt, agents, controller, call, db, rounds, agent_context, trial_id
    )


# ── mode 1: broadcast (no consensus) ──────────────────────────────────────────


async def _run_broadcast_no_consensus(
    prompt: str,
    agents: list[dict[str, Any]],
    controller: TopologyController,
    call: _AgentCall,
    db: AsyncConnection,
    rounds: int,
    agent_context: dict[str, str] | None,
    trial_id: str,
) -> None:
    agent_by_id = {a["id"]: a for a in agents}
    incoming = controller.incoming
    await _persist_system_broadcast(db, trial_id, agents, prompt, "broadcast_no_consensus")
    broadcast_output_round_id = await _create_self_message_round(
        db, trial_id, 2, "broadcast_no_consensus_outputs"
    )

    async def _broadcast(
        agent: dict[str, Any],
    ) -> tuple[str, list[SelfMessage]]:
        agent_id = str(agent["id"])
        try:
            response, tools_used = await call(
                agent,
                _with_context(prompt, agent_id, agent_context),
                {"round_index": 2, "phase": "broadcast_no_consensus_outputs"},
            )
        except Exception as exc:
            logger.exception(
                "Agent call failed — agent=%s model=%s phase=broadcast_no_consensus",
                agent.get("name", agent_id),
                agent.get("model", "unknown"),
            )
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
        # Static: an empty graph means nothing more can happen, so stop. Dynamic:
        # keep going even with no edges so agents can self-organise from scratch
        # (a fully-wireless start); convergence/round-limit still bound the loop.
        if controller.mode != "dynamic" and not any(incoming.values()):
            break
        round_id = await create_round(db, trial_id, round_num + 2, "discussion")

        async def _discuss(
            agent: dict[str, Any],
            incoming: dict[str, list[str]] = incoming,
            current_round_index: int = round_num + 2,
        ) -> tuple[str, list[MessageDelivery], list[SelfMessage], str] | None:
            senders = [sid for sid in incoming[agent["id"]] if sid in responses]
            suffix = controller.prompt_suffix(agent)
            # Static: isolated agents stay silent. Dynamic: an agent with no
            # incoming edges still gets a turn so it can discover peers via the
            # registry and emit a CONNECT line — enabling a seedless start.
            if not senders and not suffix:
                return None

            if senders:
                context_lines = [
                    f"- {agent_by_id[sid]['name']}: {responses[sid]}" for sid in senders
                ]
                peer_block = (
                    "Other agents responded:\n"
                    + "\n".join(context_lines)
                    + "\n\nConsidering these perspectives, what is your updated view?"
                )
            else:
                peer_block = (
                    "You have no incoming connections yet. Use the registry to find peers "
                    "whose input would improve your answer next round."
                )
            discussion_prompt = f"Original question: {prompt}\n\n" + peer_block + suffix

            agent_id = str(agent["id"])
            deliveries: list[MessageDelivery] = [(sid, agent_id, responses[sid]) for sid in senders]

            try:
                response, tools_used = await call(
                    agent,
                    discussion_prompt,
                    {"round_index": current_round_index, "phase": "discussion"},
                )
            except Exception as exc:
                logger.exception(
                    "Agent call failed — agent=%s model=%s phase=discussion_no_consensus",
                    agent.get("name", agent_id),
                    agent.get("model", "unknown"),
                )
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

        # Dynamic topology: rebuild the graph from this round's CONNECT lines.
        # Reassigning `incoming` means the next round's `_discuss` (redefined each
        # iteration) closes over the rewired graph. In static mode this returns
        # the same dict and `converged` stays False, so behaviour is unchanged.
        incoming = controller.rewire(responses)
        if controller.converged:
            await _persist_system_self_message(
                db, round_id, "topology_converged", "Topology stabilised — stopping."
            )
            break


# ── mode 2: weighted opinion pooling (Option A) ───────────────────────────────


_WEIGHT_BLEND = 0.3  # how much old trust to retain each round (EMA factor)
_WEIGHT_EPSILON = 0.05  # max per-edge trust change tolerated as "stable"
_WEIGHT_STABILITY_K = 1  # consecutive stable rounds needed for convergence
_SIM_FLOOR = 0.001  # floor on similarity — prevents division-by-zero


def _normalise_trust(weights: dict[str, float]) -> dict[str, float]:
    """Renormalise a per-neighbour weight dict to sum to 1.0.

    The EMA blend keeps weights summing to 1 in theory (convex combination
    of two probability distributions), but floating-point drift accumulates
    over many rounds. Renormalising defensively keeps the invariant exact.
    """
    total = sum(weights.values())
    if total <= 0.0:
        n = len(weights)
        return dict.fromkeys(weights, 1.0 / n) if n else {}
    return {k: v / total for k, v in weights.items()}


async def _run_weighted_opinion_pool(
    prompt: str,
    agents: list[dict[str, Any]],
    controller: TopologyController,
    call: _AgentCall,
    db: AsyncConnection,
    rounds: int,
    agent_context: dict[str, str] | None,
    trial_id: str,
) -> None:
    agent_by_id = {a["id"]: a for a in agents}
    incoming = controller.incoming
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
        full_prompt = _with_context(prompt, agent_id, agent_context) + _WEIGHTED_POOL_INSTRUCTION
        try:
            response, tools = await call(
                agent,
                full_prompt,
                {"round_index": 2, "phase": "weighted_opinion_pooling_broadcast_outputs"},
            )
        except Exception as exc:
            logger.exception(
                "Agent call failed — agent=%s model=%s phase=weighted_opinion_pooling_broadcast",
                agent.get("name", agent_id),
                agent.get("model", "unknown"),
            )
            err = f"[error: {exc}]"
            return err, [("agent_error", err)]
        return response, _self_messages(response, tools)

    bcast = await asyncio.gather(*[_broadcast(a) for a in agents])
    responses: dict[str, str] = {}
    for agent, (resp, self_messages) in zip(agents, bcast, strict=True):
        agent_id = str(agent["id"])
        await _persist_self_messages(db, broadcast_output_round_id, agent_id, self_messages)
        responses[agent_id] = resp

    broadcast_responses: dict[str, str] = dict(responses)
    stable_streak = 0

    # Seed trust from broadcast responses so the initial disagreement is
    # captured before agents have a chance to flip during discussion.
    bcast_ids = [aid for aid in broadcast_responses if incoming[aid]]
    bcast_answers = [
        _extract_answer(broadcast_responses[aid]) or broadcast_responses[aid] for aid in bcast_ids
    ]
    bcast_embeddings_list = await embed_texts(bcast_answers)
    bcast_embeddings: dict[str, list[float]] | None = None
    if bcast_embeddings_list is not None:
        bcast_embeddings = dict(zip(bcast_ids, bcast_embeddings_list, strict=True))

    for a in agents:
        aid = a["id"]
        nbrs = incoming[aid]
        if not nbrs or aid not in broadcast_responses:
            continue
        bcast_sims: dict[str, float] = {}
        for n in nbrs:
            nbr_text = broadcast_responses.get(n, "")
            if bcast_embeddings is not None and aid in bcast_embeddings and n in bcast_embeddings:
                sim = cosine_similarity(bcast_embeddings[aid], bcast_embeddings[n])
                bcast_sims[n] = max(sim, _SIM_FLOOR)
            else:
                my_answer = _extract_answer(broadcast_responses[aid]) or broadcast_responses[aid]
                nbr_answer = _extract_answer(nbr_text) or nbr_text
                bcast_sims[n] = max(_entity_aware_similarity(my_answer, nbr_answer), _SIM_FLOOR)
        total = sum(bcast_sims.values())
        if total > 0:
            trust[aid] = _normalise_trust({n: s / total for n, s in bcast_sims.items()})

    # Persist broadcast trust seeding so the UI shows scores after round 1.
    agg_seed = _aggregate_trust(trust)
    if agg_seed:
        ranked = sorted(agg_seed.items(), key=lambda kv: -kv[1])[:5]
        top_str = ", ".join(
            f"{agent_by_id[a]['name']}={w:.2f}" for a, w in ranked if a in agent_by_id
        )
        await _persist_system_self_message(
            db,
            broadcast_output_round_id,
            "trust_update",
            f"Broadcast trust seed: {top_str}",
        )
        for a in agents:
            aid = a["id"]
            if not trust[aid]:
                continue
            trust_data = json.dumps(
                {
                    "agent_id": aid,
                    "agent_name": agent_by_id[aid]["name"],
                    "round": 0,
                    "trust_vector": {
                        agent_by_id[n]["name"]: round(w, 4)
                        for n, w in trust[aid].items()
                        if n in agent_by_id
                    },
                }
            )
            await _persist_system_self_message(
                db,
                broadcast_output_round_id,
                "trust_evolution",
                trust_data,
            )

    for round_num in range(1, rounds + 1):
        # Static stops on an empty graph; dynamic keeps going so a seedless graph
        # can self-organise (bounded by convergence + the round limit).
        if controller.mode != "dynamic" and not any(incoming.values()):
            break
        round_id = await create_round(db, trial_id, round_num + 2, "weighted_opinion_pooling")

        async def _discuss(
            agent: dict[str, Any],
            incoming: dict[str, list[str]] = incoming,
            current_round_index: int = round_num + 2,
        ) -> tuple[str, list[MessageDelivery], list[SelfMessage], str] | None:
            nbrs = [n for n in incoming[agent["id"]] if n in responses]
            suffix = controller.prompt_suffix(agent)
            # Static: silent when isolated. Dynamic: still answer + discover so a
            # seedless graph can bootstrap from scratch.
            if not nbrs and not suffix:
                return None

            agent_id = str(agent["id"])
            weights = trust[agent_id]
            own_prev = _extract_structured_response(responses.get(agent_id, ""))
            own_answer = own_prev["answer"] or "no previous answer"
            own_source = own_prev["source"] or "none"

            # Detect if the agent changed its answer from the broadcast.
            bcast_parsed = _extract_structured_response(broadcast_responses.get(agent_id, ""))
            bcast_answer = bcast_parsed["answer"]
            changed = (
                bcast_answer
                and own_answer != "no previous answer"
                and bcast_answer.lower() != own_answer.lower()
            )
            change_note = (
                f"\nYou originally answered '{bcast_answer}' but changed to "
                f"'{own_answer}' based on stronger evidence. "
                "Do NOT revert to your original answer."
                if changed
                else ""
            )

            context_lines: list[str] = []
            for n in nbrs:
                parsed = _extract_structured_response(responses[n])
                answer_text = parsed["answer"] or responses[n]
                source_text = f" [source: {parsed['source']}]" if parsed["source"] else ""
                context_lines.append(
                    f"- {agent_by_id[n]['name']} "
                    f"(trust {weights.get(n, 0.0):.2f}): "
                    f"{answer_text}{source_text}"
                )
            if nbrs:
                peer_block = (
                    "Other agents responded (weighted by your trust in them):\n"
                    + "\n".join(context_lines)
                    + "\n\nGiving more weight to higher-trust voices, "
                    "what is your updated answer?"
                )
            else:
                peer_block = (
                    "You have no incoming connections yet. Use the registry to find peers "
                    "whose input would improve your answer next round."
                )
            discussion_prompt = (
                f"Original question: {prompt}\n\n"
                f"Your previous answer: {own_answer} "
                f"[source: {own_source}]{change_note}\n\n"
                + peer_block
                + _WEIGHTED_POOL_INSTRUCTION
                + suffix
            )

            deliveries: list[MessageDelivery] = [(n, agent_id, responses[n]) for n in nbrs]

            try:
                resp, tools = await call(
                    agent,
                    discussion_prompt,
                    {
                        "round_index": current_round_index,
                        "phase": "weighted_opinion_pooling_discussion",
                    },
                )
            except Exception as exc:
                logger.exception(
                    "Agent call failed — agent=%s model=%s"
                    " phase=weighted_opinion_pooling_discussion",
                    agent.get("name", agent_id),
                    agent.get("model", "unknown"),
                )
                err = f"[error: {exc}]"
                return agent_id, deliveries, [("agent_error", err)], err

            return agent_id, deliveries, _self_messages(resp, tools), resp

        results = await asyncio.gather(*[_discuss(a) for a in agents])

        # Persist in logical order: all deliveries → all self-messages
        # so the activity log reads: incoming → tools → output → trust.
        parsed_results: list[tuple[str, list[MessageDelivery], list[SelfMessage], str]] = []
        for result in results:
            if result is not None:
                parsed_results.append(result)

        for _, deliveries, _, _ in parsed_results:
            await _persist_agent_deliveries(db, round_id, deliveries, "weighted_agent_to_agent")

        prev_responses = dict(responses)
        new_responses: dict[str, str] = {}
        for agent_id, _, self_messages, new_resp in parsed_results:
            await _persist_self_messages(db, round_id, agent_id, self_messages)
            new_responses[agent_id] = new_resp

        # Trust update: embed extracted answers and use cosine similarity.
        # Falls back to entity-aware Jaccard if the embedding call fails.
        responding_ids = [aid for aid in new_responses if incoming[aid]]
        responding_answers = [
            _extract_answer(new_responses[aid]) or new_responses[aid] for aid in responding_ids
        ]
        embeddings_list = await embed_texts(responding_answers)
        embeddings: dict[str, list[float]] | None = None
        if embeddings_list is not None:
            embeddings = dict(zip(responding_ids, embeddings_list, strict=True))

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
                if embeddings is not None and aid in embeddings and n in embeddings:
                    sims[n] = max(cosine_similarity(embeddings[aid], embeddings[n]), _SIM_FLOOR)
                else:
                    my_answer = _extract_answer(my_new) or my_new
                    nbr_answer = _extract_answer(nbr_text) or nbr_text
                    sims[n] = max(_entity_aware_similarity(my_answer, nbr_answer), _SIM_FLOOR)
            total = sum(sims.values())
            target = {n: s / total for n, s in sims.items()}
            old = trust[aid]
            blended = {
                n: _WEIGHT_BLEND * old.get(n, 1.0 / len(nbrs)) + (1 - _WEIGHT_BLEND) * target[n]
                for n in nbrs
            }
            updated = _normalise_trust(blended)
            for n in nbrs:
                max_trust_change = max(
                    max_trust_change, abs(updated[n] - old.get(n, 1.0 / len(nbrs)))
                )
            trust[aid] = updated

        responses.update(new_responses)

        agg = _aggregate_trust(trust)
        if agg:
            ranked = sorted(agg.items(), key=lambda kv: -kv[1])[:5]
            top_str = ", ".join(
                f"{agent_by_id[a]['name']}={w:.2f}" for a, w in ranked if a in agent_by_id
            )
            await _persist_system_self_message(
                db,
                round_id,
                "trust_update",
                f"Aggregate trust (top): {top_str}  |  Δmax = {max_trust_change:.3f}",
            )

            for a in agents:
                aid = a["id"]
                if not trust[aid]:
                    continue
                trust_data = json.dumps(
                    {
                        "agent_id": aid,
                        "agent_name": agent_by_id[aid]["name"],
                        "round": round_num,
                        "trust_vector": {
                            agent_by_id[n]["name"]: round(w, 4)
                            for n, w in trust[aid].items()
                            if n in agent_by_id
                        },
                    }
                )
                await _persist_system_self_message(db, round_id, "trust_evolution", trust_data)

        # Stability-based convergence: require K consecutive rounds of small
        # delta before declaring convergence. A single quiet round was prone
        # to spurious early stops on noisy first iterations.
        if max_trust_change < _WEIGHT_EPSILON:
            stable_streak += 1
        else:
            stable_streak = 0

        weights_stable = stable_streak >= _WEIGHT_STABILITY_K

        # Static: trust stability alone stops the run (unchanged behaviour).
        if controller.mode != "dynamic":
            if weights_stable:
                await _persist_system_self_message(
                    db,
                    round_id,
                    "convergence",
                    f"Converged after {round_num} round(s) (Δmax < {_WEIGHT_EPSILON}).",
                )
                break
            continue

        # Dynamic: rewire EVERY round from the agents' CONNECT lines BEFORE deciding
        # to stop, then reconcile each trust vector to the new neighbour set — new
        # neighbours get the uniform prior, dropped ones are removed and the vector
        # is renormalised. The previous order (break-then-rewire) meant trust
        # convergence — which can fire after a single round (K == 1) — short-
        # circuited the run before the graph ever evolved, so isolated agents could
        # never join. We keep exploring until the *graph* also settles.
        incoming = controller.rewire(responses)
        for a in agents:
            aid = a["id"]
            nbrs = incoming[aid]
            vec = trust.get(aid, {})
            uniform = 1.0 / len(nbrs) if nbrs else 0.0
            vec = {n: vec.get(n, uniform) for n in nbrs}  # add new, drop missing
            total = sum(vec.values())
            trust[aid] = {n: w / total for n, w in vec.items()} if total > 0 else vec
        if controller.converged:
            note = (
                f"Answer and topology both stabilised after {round_num} round(s)."
                if weights_stable
                else "Topology stabilised — stopping."
            )
            await _persist_system_self_message(db, round_id, "topology_converged", note)
            break

    agg_trust = _aggregate_trust(trust)
    consensus, consensus_aid = _weighted_consensus(responses, agg_trust)

    if consensus is not None and not any(agg_trust.get(aid, 0.0) > 0 for aid in responses):
        if broadcast_responses:
            consensus_aid = max(
                broadcast_responses.items(),
                key=lambda kv: _jaccard(kv[1], consensus),
            )[0]

    if consensus is not None:
        winner_trust = agg_trust.get(consensus_aid or "", 0.0)
        attribution = (
            f" (aggregate trust = {winner_trust:.2f})"
            if winner_trust > 0
            else " (no edges — textual centroid)"
        )
        consensus_round_id = await _create_self_message_round(
            db, trial_id, round_num + 3, "weighted_opinion_pooling_consensus"
        )
        await _persist_system_self_message(
            db,
            consensus_round_id,
            "consensus",
            f"Selected consensus answer{attribution}:\n{consensus}",
        )


# ── mode 3: plurality voting (Option B) ───────────────────────────────────────


_VOTE_STABILITY_K = 2  # consecutive rounds the plurality must hold to converge


async def _run_voting(
    prompt: str,
    agents: list[dict[str, Any]],
    controller: TopologyController,
    call: _AgentCall,
    db: AsyncConnection,
    rounds: int,
    agent_context: dict[str, str] | None,
    trial_id: str,
) -> None:
    agent_by_id = {a["id"]: a for a in agents}
    incoming = controller.incoming
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
            response, tools = await call(
                agent,
                full_prompt,
                {"round_index": 2, "phase": "plurality_voting_broadcast_outputs"},
            )
        except Exception as exc:
            logger.exception(
                "Agent call failed — agent=%s model=%s phase=plurality_voting_broadcast",
                agent.get("name", agent_id),
                agent.get("model", "unknown"),
            )
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
            incoming: dict[str, list[str]] = incoming,
            current_round_index: int = next_round_index,
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
                    + controller.prompt_suffix(agent)
                    + _VOTE_INSTRUCTION
                )
            elif controller.mode == "dynamic":
                # Dynamic (phone-book): a truly isolated agent is NOT spoon-fed the
                # global tally. It must use the registry to find peers and CONNECT,
                # so next round's rewire wires it and real agent-to-agent messages
                # flow. No delivery is recorded — its registry tool calls are what
                # the activity log shows for this turn.
                agent_id = str(agent["id"])
                deliveries = []
                delivery_type = "voting_agent_to_agent"  # unused: no deliveries
                full_prompt = (
                    f"Original question: {prompt}\n\n"
                    f"Your previous answer:\n{own_prev}\n\n"
                    "You have no incoming connections yet, so you cannot see other "
                    "agents' answers. Use the registry tool to find the peers whose "
                    "expertise would most improve your answer, then CONNECT to them so "
                    "you hear from them next round."
                    + unknown_nudge
                    + source_nudge
                    + controller.prompt_suffix(agent)
                    + _VOTE_INSTRUCTION
                )
            else:
                # Static: fall back to global tally so an isolated agent isn't blind.
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
                resp, tools = await call(
                    agent,
                    full_prompt,
                    {
                        "round_index": current_round_index,
                        "phase": "plurality_voting_discussion",
                    },
                )
            except Exception as exc:
                logger.exception(
                    "Agent call failed — agent=%s model=%s phase=plurality_voting_discussion",
                    agent.get("name", agent_id),
                    agent.get("model", "unknown"),
                )
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

        consensus_stable = stable_streak >= _VOTE_STABILITY_K

        # Static: a stable plurality alone stops the run (unchanged behaviour).
        if controller.mode != "dynamic":
            if consensus_stable:
                break
            continue

        # Dynamic: rewire EVERY round from the agents' CONNECT lines BEFORE deciding
        # to stop, so an isolated agent's phone-registry picks are always honoured.
        # The previous order (break-then-rewire) meant a stable plurality — the
        # common case — short-circuited the run before the graph ever evolved, so
        # isolated agents could never join. We keep exploring until the *graph*
        # also settles (or the round limit is hit), not on consensus alone.
        incoming = controller.rewire(responses)
        if controller.converged:
            note = (
                "Answer and topology both stabilised — stopping."
                if consensus_stable
                else "Topology stabilised — stopping."
            )
            await _persist_system_self_message(db, round_id, "topology_converged", note)
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
    '      "expects": "<what information or other agent would close this gap>"\n'
    "    }\n"
    "  ],\n"
    '  "contribution": [\n'
    "    {\n"
    '      "data": "<information or tools you have that is relevant for the task>",\n'
    '      "citation": "<the source backing this statement: file name plus '
    "the file's date if present'>\"\n"
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- Cite only tools you have been granted; fabricated tool names will "
    "be removed.\n"
    "- Cite only files you actually read this turn; the system verifies "
    "every file citation against your tool-call log.\n"
    "- `evidence.relevant_files[*].relevance` should quote or paraphrase "
    "the specific line(s) from the file that support your contribution — "
    "vague descriptions like 'discusses the company' are weak signals.\n"
    '- Use "none" for `estimated_completeness` if nothing in your evidence '
    "applies to the task; in that case set `contribution` to an empty array.\n"
)

_BIDDING_MATCHING_INSTRUCTION = (
    "\n\n## GAP MATCHING\n"
    "The BLACKBOARD below lists gaps posted by OTHER agents. YOUR FINDINGS "
    "below are your own bid findings, each with a stable id (F0, F1, …).\n\n"
    "Go through every gap. Add one entry to `gap_coverage` for each gap you "
    "can help answer, and omit the gaps you cannot. Two ways to contribute, "
    "usable together:\n"
    "- `reuses_finding`: ids of YOUR FINDINGS that already answer the gap "
    '(e.g. ["F0"]); the system links them, so you need not retype the data.\n'
    "- `contribution`: NEW facts you find by reading a file this turn, each "
    "with a citation.\n"
    "Partial or complementary information still counts — contribute it.\n\n"
    "Rules:\n"
    "- Cite only tools you were granted.\n"
    "- Every NEW contribution must come from a file you actually read this "
    "turn (`files` action='read'); un-read citations are rejected.\n"
    "- `reuses_finding` ids must appear in YOUR FINDINGS.\n\n"
    "Respond with ONLY this JSON (no prose, no fences). If you can help with "
    'no gap, return `{"gap_coverage": []}`:\n\n'
    "{\n"
    '  "gap_coverage": [\n'
    "    {\n"
    '      "gap_id": "<exact gap_id from the blackboard>",\n'
    '      "can_contribute": true,\n'
    '      "reuses_finding": ["F0"],\n'
    '      "evidence": {\n'
    '        "relevant_tools": [...],\n'
    '        "relevant_files": [\n'
    '          {"file_name": "...", "file_type": "...", "relevance": "..."}\n'
    "        ]\n"
    "      },\n"
    '      "contribution": [\n'
    '        {"data": "<a new fact answering this gap>",\n'
    '         "citation": "<file name + date, e.g. '
    'nexora_overview_2024 (2024-09-01)>"}\n'
    "      ],\n"
    '      "rationale": "<one sentence: why this fills the gap>"\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Each entry must set `can_contribute: true` and carry a non-empty "
    "`reuses_finding` OR `contribution` (or both).\n\n"
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
    # An agent that has cited evidence but produced no actionable contribution
    # is treated as non-participating — same as if it had no evidence at all.
    if not _has_evidence(validated) or not contribution:
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
    known_finding_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, list[Any]]]:
    """Validate an agent's round-2 ``gap_coverage`` claims.

    Same unfakeable evidence checks as :func:`_validate_bid`, plus a gap-id
    existence check against the blackboard the agent was actually shown and a
    finding-id existence check on any ``reuses_finding`` references (which must
    name one of the agent's own bid findings, F0/F1/…).
    """
    tools_set = set(available_tools or [])
    rejections: dict[str, list[Any]] = {
        "unknown_gap_ids": [],
        "unknown_finding_ids": [],
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

        # Validate reuses_finding references against the agent's own findings.
        raw_reuses = entry.get("reuses_finding")
        reuse_candidates: list[str] = []
        if isinstance(raw_reuses, str) and raw_reuses.strip():
            reuse_candidates = [raw_reuses.strip()]
        elif isinstance(raw_reuses, list):
            reuse_candidates = [r.strip() for r in raw_reuses if isinstance(r, str) and r.strip()]
        valid_reuses: list[str] = []
        for r in reuse_candidates:
            if r in known_finding_ids:
                valid_reuses.append(r)
            else:
                rejections["unknown_finding_ids"].append(r)

        contribution = _normalise_contribution(entry.get("contribution"))
        if not contribution and not valid_reuses:
            # Claimed to contribute but added no new data and reused nothing
            # real — downgrade.
            valid_entries.append({"gap_id": gap_id, "can_contribute": False})
            continue
        valid_entries.append(
            {
                "gap_id": gap_id,
                "can_contribute": True,
                "reuses_finding": valid_reuses,
                "evidence": valid_ev,
                "contribution": contribution,
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


def _format_own_findings(contribution: list[dict[str, Any]]) -> str:
    """Render the agent's own validated bid findings with stable F-ids."""
    if not contribution:
        return "(you declared no findings in your bid)"
    lines: list[str] = []
    for i, item in enumerate(contribution):
        if not isinstance(item, dict):
            continue
        data = str(item.get("data") or "").strip()
        if not data:
            continue
        cite = str(item.get("citation") or "").strip() or "unspecified"
        lines.append(f"- F{i}: {data}  [source: {cite}]")
    return "\n".join(lines) or "(you declared no findings in your bid)"


_FINDING_ID_RE = re.compile(r"^F(\d+)$")


def _finding_index(fid: str) -> int | None:
    """Parse a finding id like ``F3`` into its integer index, or None."""
    m = _FINDING_ID_RE.match(fid.strip()) if isinstance(fid, str) else None
    return int(m.group(1)) if m else None


def _select_collaborators(
    bids: dict[str, dict[str, Any]],
    coverage: dict[str, list[dict[str, Any]]],
    blackboard: list[dict[str, Any]],
    agents: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pick the collaboration set and list any uncovered gaps.

    An agent is selected iff it produced an actual *contribution* — a direct
    finding in its round-1 bid OR added data on a gap during round-2 matching.
    Agents that only cited evidence but yielded without an actionable
    contribution are excluded, so only agents with something to say take part
    in answer generation. Order is the agents-table order for determinism.
    Each collaborator is returned as ``{id, name, contribution, covers}`` where
    each cover entry includes the ``added_data`` the agent posted to that gap.
    """
    collaborator_ids: set[str] = set()

    for agent_id, bid in bids.items():
        if bid.get("contribution"):
            collaborator_ids.add(agent_id)

    for covers in coverage.values():
        for entry in covers:
            if entry.get("contribution"):
                collaborator_ids.add(str(entry.get("agent_id") or ""))

    gap_lookup = {e["gap_id"]: e for e in blackboard}

    uncovered: list[dict[str, Any]] = []
    covers_by_agent: dict[str, list[dict[str, Any]]] = {}
    for gid, entries in coverage.items():
        gap_entry = gap_lookup.get(gid)
        any_valid_cover = False
        for entry in entries:
            if not entry.get("contribution"):
                continue
            any_valid_cover = True
            aid = str(entry.get("agent_id") or "")
            covers_by_agent.setdefault(aid, []).append(
                {
                    "gap_id": gid,
                    "posted_by": gap_entry["agent_name"] if gap_entry else None,
                    "gap": gap_entry["gap"] if gap_entry else None,
                    "added_data": entry.get("contribution") or [],
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
    coverage: dict[str, list[dict[str, Any]]] | None = None,
    blackboard: list[dict[str, Any]] | None = None,
) -> str:
    """Render every collaborator's contribution entries with their citations.

    When ``coverage`` and ``blackboard`` are provided, also render a "Gap
    board" section showing each gap (posted by whom, what was expected) and
    the data each contributing agent added to it.
    """
    lines: list[str] = ["### Direct findings (from bidding):"]
    has_direct = False
    for c in collaborators:
        cid = str(c.get("id", ""))
        bid = bids.get(cid) or {}
        if bid.get("yielded"):
            continue
        contribution = bid.get("contribution") or []
        if not isinstance(contribution, list) or not contribution:
            continue
        has_direct = True
        name = c.get("name") or cid
        lines.append(f"- {name}:")
        for item in contribution:
            if not isinstance(item, dict):
                continue
            data = str(item.get("data") or "").strip()
            citation = str(item.get("citation") or "").strip()
            if not data:
                continue
            cite_str = citation or "unspecified"
            lines.append(f"    - {data}  [source: {cite_str}]")
    if not has_direct:
        lines.append("(none declared)")

    if blackboard:
        name_by_id = {str(c.get("id")): c.get("name") or str(c.get("id")) for c in collaborators}
        gap_lookup = {e["gap_id"]: e for e in blackboard}
        coverage = coverage or {}

        lines.append("")
        lines.append("### Gap board (data added during matching):")
        any_filled = False
        for gid, entries in coverage.items():
            gap_entry = gap_lookup.get(gid)
            if gap_entry is None:
                continue
            valid_items: list[tuple[str, list[dict[str, Any]]]] = []
            for entry in entries:
                ev = entry.get("evidence") or {}
                if not (ev.get("relevant_tools") or ev.get("relevant_files")):
                    continue
                aid = str(entry.get("agent_id") or "")
                contrib = entry.get("contribution") or []
                if isinstance(contrib, list) and contrib:
                    valid_items.append((name_by_id.get(aid, aid), contrib))
            if not valid_items:
                continue
            any_filled = True
            gap_dict = gap_entry["gap"] if isinstance(gap_entry["gap"], dict) else {}
            gap_summary = str(gap_dict.get("reason") or gap_dict.get("expects") or gid)
            lines.append(f"- Gap from {gap_entry['agent_name']} ({gap_summary}):")
            for ag_name, contrib in valid_items:
                for item in contrib:
                    if not isinstance(item, dict):
                        continue
                    data = str(item.get("data") or "").strip()
                    citation = str(item.get("citation") or "").strip()
                    if not data:
                        continue
                    cite_str = citation or "unspecified"
                    lines.append(f"    - {ag_name}: {data}  [source: {cite_str}]")
        if not any_filled:
            lines.append("(no gap-coverage data added)")

        uncovered_summary = [
            e
            for e in blackboard
            if e["gap_id"] not in coverage
            or not any(
                (c.get("evidence") or {}).get("relevant_tools")
                or (c.get("evidence") or {}).get("relevant_files")
                for c in coverage[e["gap_id"]]
            )
        ]
        if uncovered_summary:
            lines.append("")
            lines.append("### Uncovered gaps (no agent supplied data):")
            for e in uncovered_summary:
                gap_dict = e["gap"] if isinstance(e["gap"], dict) else {}
                summary = str(gap_dict.get("reason") or gap_dict.get("expects") or e["gap_id"])
                lines.append(f"- from {e['agent_name']}: {summary}")

    return "\n".join(lines)


async def _answer_consensus(
    answers: dict[str, str],
) -> tuple[float, str | None]:
    """Measure how strongly a set of agent answers agree.

    Returns ``(mean_pairwise_similarity, medoid_agent_id)``:

    - ``mean_pairwise_similarity`` — the average similarity over every unique
      pair of answers, in ``[0, 1]``. This is the convergence signal.
    - ``medoid_agent_id`` — the agent whose answer is, on average, most similar
      to all the others: the single best representative of the group.

    Similarity is semantic (OpenAI embeddings + cosine), falling back to
    entity-aware Jaccard when the embedding backend is unavailable. Fewer than
    two non-empty answers is trivially converged (similarity ``1.0``).
    """
    items = [(aid, text) for aid, text in answers.items() if text and text.strip()]
    if not items:
        return 1.0, None
    if len(items) == 1:
        return 1.0, items[0][0]

    ids = [aid for aid, _ in items]
    texts = [text for _, text in items]
    n = len(items)

    vectors = await embed_texts(texts)
    if vectors is None or len(vectors) != n:
        vectors = None  # embedding backend unavailable — use lexical fallback

    summed = [0.0] * n
    total = 0.0
    pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            sim = (
                cosine_similarity(vectors[i], vectors[j])
                if vectors is not None
                else _entity_aware_similarity(texts[i], texts[j])
            )
            total += sim
            pairs += 1
            summed[i] += sim
            summed[j] += sim

    mean = total / pairs if pairs else 1.0
    medoid = max(range(n), key=lambda i: summed[i])
    return max(0.0, min(1.0, mean)), ids[medoid]


async def _run_parallel_consensus(
    prompt: str,
    collaborators: list[dict[str, Any]],
    agents_by_id: dict[str, dict[str, Any]],
    bids: dict[str, dict[str, Any]],
    coverage: dict[str, list[dict[str, Any]]],
    blackboard: list[dict[str, Any]],
    call: _AgentCall,
    db: AsyncConnection,
    trial_id: str,
    round_index: int,
    agent_context: dict[str, str] | None,
    convergence_threshold: float = 0.85,
    max_rounds: int = 5,
) -> str | None:
    """Parallel convergence on a shared answer.

    Round 1 — every collaborator drafts an answer independently from the
    bidding board (in parallel). The system then measures the semantic
    similarity across those answers (mean pairwise cosine over embeddings).
    If they already agree closely enough (``>= convergence_threshold``) the
    consensus is reached. Otherwise every agent reads ALL the other agents'
    answers and redrafts, and the loop repeats. It terminates on convergence
    or after ``max_rounds`` (safety cap), returning the medoid — the answer
    most representative of the group.
    """
    if not collaborators:
        return None

    valid = [c for c in collaborators if str(c["id"]) in agents_by_id]
    if not valid:
        return None

    round_id = int(await create_round(db, trial_id, round_index, "bidding_collaboration"))
    findings_block = _format_findings(collaborators, bids, coverage, blackboard)
    findings_prelude = (
        "\n\n## THE BIDDING BOARD\n"
        "Below is the bidding board. It contains ALL existing information "
        "gathered during the bidding phase that provides value to the user's "
        "question. Every citation below has been independently verified by the "
        "system: the cited file exists, was attached to the cited agent, and "
        "was actually read by that agent during the bidding phase. Treat each "
        "cited finding as an ESTABLISHED FACT — you do NOT need to "
        'disclaim "I don\'t have access to that file" or hedge with '
        '"reportedly" / "according to other agents". The findings are part '
        "of the shared knowledge of this collaboration; cite them the same "
        "way you would cite a file you read yourself.\n\n"
        f"{findings_block}\n\n"
        "Base your answer on ALL of the information on this board, not only on "
        "what you personally found or already believe. Do not omit or "
        "down-weight a finding just because another agent contributed it. "
        "When findings disagree, reconcile by comparing the sources and let "
        "the user get the whole context, especially if any conflicts arise."
    )

    async def _draft(
        agent: dict[str, Any],
        prior: dict[str, str] | None,
        round_num: int,
    ) -> tuple[str, str, list[ToolCall]]:
        agent_id = str(agent["id"])
        if prior is None:
            instruction = (
                f"\n\n## CRAFT YOUR ANSWER (round {round_num})\n"
                "This is the bidding board containing all existing information "
                "that provides value to the user's question. Based on ALL of "
                "this information — not just your own findings — craft a "
                "complete answer to the user's question. Write polished, "
                "user-facing prose."
            )
        else:
            others = "\n\n".join(
                f"### Answer from {agents_by_id.get(oid, {}).get('name', oid)}\n{ans}"
                for oid, ans in prior.items()
                if oid != agent_id and ans.strip()
            )
            instruction = (
                f"\n\n## THE OTHER AGENTS' ANSWERS (round {round_num})\n"
                f"{others}\n\n"
                "## REVISE TOWARD CONSENSUS\n"
                "The agents have NOT yet converged on a single shared answer. "
                "Read the other agents' answers above together with the "
                "bidding board, then write a revised answer: adopt every "
                "well-supported claim the others surfaced that you missed, "
                "drop any claim of yours the board does not support, and move "
                "toward one shared answer. Where the board shows a genuine "
                "conflict, keep it and explain it rather than papering over "
                "it. Output the FULL revised answer as polished, user-facing "
                "prose."
            )
        turn_prompt = (
            _with_context(prompt, agent_id, agent_context) + findings_prelude + instruction
        )
        try:
            response, tools_used = await call(agent, turn_prompt)
        except Exception as exc:
            logger.exception(
                "Agent call failed — agent=%s model=%s phase=bidding_draft",
                agent.get("name", agent_id),
                agent.get("model", "unknown"),
            )
            return agent_id, f"[error: {exc}]", []
        return agent_id, response, tools_used

    answers: dict[str, str] = {}
    similarity = 0.0
    medoid_id: str | None = None
    converged = False
    rounds_run = 0

    for round_num in range(1, max(1, max_rounds) + 1):
        prior = None if round_num == 1 else dict(answers)
        results = await asyncio.gather(
            *[_draft(agents_by_id[str(c["id"])], prior, round_num) for c in valid]
        )

        answers = {}
        for agent_id, response, tools_used in results:
            self_messages: list[SelfMessage] = [
                ("tool", _format_tool_message(tool)) for tool in _last_tool_calls(tools_used)
            ]
            self_messages.append(("agent_output", response))
            await _persist_self_messages(db, round_id, agent_id, self_messages)
            answers[agent_id] = response

        rounds_run = round_num
        similarity, medoid_id = await _answer_consensus(answers)
        await _persist_system_self_message(
            db,
            round_id,
            "bidding_convergence",
            f"Round {round_num}: mean pairwise answer similarity "
            f"{similarity:.3f} (threshold {convergence_threshold:.2f}).",
        )
        if similarity >= convergence_threshold:
            converged = True
            break

    summary = (
        f"Converged after {rounds_run} round(s): answers agree at "
        f"{similarity:.3f} >= {convergence_threshold:.2f}."
        if converged
        else f"Did not converge after {rounds_run} round(s) "
        f"(cap: {max_rounds}; best similarity {similarity:.3f} "
        f"< {convergence_threshold:.2f}). Returning the most representative answer."
    )
    await _persist_system_self_message(db, round_id, "bidding_convergence", summary)

    if medoid_id is not None and medoid_id in answers:
        return answers[medoid_id]
    return next((ans for ans in answers.values() if ans.strip()), None)


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
            logger.exception(
                "Agent call failed — agent=%s model=%s phase=bidding_bid",
                agent.get("name", agent_id),
                agent.get("model", "unknown"),
            )
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
    coverage: dict[str, list[dict[str, Any]]] = {}

    if blackboard:
        per_agent_board: dict[str, list[dict[str, Any]]] = {
            str(a["id"]): [e for e in blackboard if e["agent_id"] != str(a["id"])] for a in agents
        }
        blackboard_round_id = int(await create_round(db, trial_id, 3, "bidding_blackboard"))
        # Emit a single consolidated SYSTEM message listing every gap, rather
        # than one personalised broadcast per agent. Per-agent filtering still
        # happens inside the matching prompt (`_match` uses `per_agent_board`)
        # so agents only see other agents' gaps in their own prompt; the
        # audit log shows the complete board once.
        await record_message(
            db,
            blackboard_round_id,
            None,
            None,
            "system_blackboard",
            _format_blackboard(blackboard),
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
            own_findings = agent_bid.get("contribution") or []
            known_finding_ids = {f"F{i}" for i in range(len(own_findings))}
            match_prompt = (
                _with_context(prompt, agent_id, agent_context)
                + _BIDDING_MATCHING_INSTRUCTION
                + "## YOUR FINDINGS\n"
                + _format_own_findings(own_findings)
                + "\n\n## BLACKBOARD\n"
                + _format_blackboard(others)
            )
            try:
                response, tools_used = await call(agent, match_prompt)
            except Exception as exc:
                logger.exception(
                    "Agent call failed — agent=%s model=%s phase=bidding_match",
                    agent.get("name", agent_id),
                    agent.get("model", "unknown"),
                )
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
                known_finding_ids,
            )
            # Persist the validated entries verbatim — they carry only the NEW
            # contributions plus `reuses_finding` references, so the board can
            # wire reused bid findings to gaps without duplicating their text.
            self_messages.append(("bidding_match", _fenced_json({"gap_coverage": valid_entries})))
            if (
                rejections["unknown_gap_ids"]
                or rejections["unknown_finding_ids"]
                or rejections["tools"]
                or rejections["files"]
            ):
                self_messages.append(("bidding_rejection", _fenced_json(rejections)))

            # Resolve reuses into concrete data + inherited evidence so the
            # selection/findings phase sees the reused finding as real coverage.
            agent_evidence = agent_bid.get("evidence") or {}
            agent_coverage: dict[str, dict[str, Any]] = {}
            for entry in valid_entries:
                if not entry.get("can_contribute"):
                    continue
                contribution = list(entry.get("contribution") or [])
                evidence = entry.get("evidence") or {}
                reuses = entry.get("reuses_finding") or []
                if reuses:
                    # A reused finding carries no fresh evidence block; inherit
                    # the bid's (those files were proven read in round 1).
                    if not (evidence.get("relevant_tools") or evidence.get("relevant_files")):
                        evidence = agent_evidence
                    seen = {str(c.get("data", "")).strip().lower() for c in contribution}
                    for fid in reuses:
                        idx = _finding_index(fid)
                        if idx is None or idx >= len(own_findings):
                            continue
                        f = own_findings[idx]
                        data = str(f.get("data") or "").strip()
                        if not data or data.lower() in seen:
                            continue
                        seen.add(data.lower())
                        contribution.append({"data": data, "citation": f.get("citation", "")})
                if not contribution:
                    continue
                agent_coverage[entry["gap_id"]] = {
                    "evidence": evidence,
                    "contribution": contribution,
                }
            return agent_id, self_messages, agent_coverage

        match_results = await asyncio.gather(*[_match(a) for a in agents])
        for agent_id, self_messages, agent_coverage in match_results:
            if self_messages:
                await _persist_self_messages(db, matching_round_id, agent_id, self_messages)
            for gap_id, payload in agent_coverage.items():
                coverage.setdefault(gap_id, []).append(
                    {
                        "agent_id": agent_id,
                        "evidence": payload["evidence"],
                        "contribution": payload["contribution"],
                    }
                )

    # ── Selection ────────────────────────────────────────────────────────────
    collaborators, uncovered = _select_collaborators(bids, coverage, blackboard, agents)
    selection_round_id = await _create_self_message_round(db, trial_id, 5, "bidding_selection")
    await _persist_system_self_message(
        db,
        selection_round_id,
        "bidding_collaborators",
        _fenced_json({"collaborators": collaborators, "uncovered_gaps": uncovered}),
    )

    # ── Parallel consensus: collaborators draft in parallel, then converge ───
    if collaborators:
        agents_by_id = {str(a["id"]): a for a in agents}
        final_output = await _run_parallel_consensus(
            prompt,
            collaborators,
            agents_by_id,
            bids,
            coverage,
            blackboard,
            call,
            db,
            trial_id,
            round_index=6,
            agent_context=agent_context,
            convergence_threshold=0.85,
            max_rounds=5,
        )
        if final_output is not None:
            final_round_id = await _create_self_message_round(
                db, trial_id, 7, "bidding_final_output"
            )
            await _persist_system_self_message(
                db, final_round_id, "bidding_final_output", final_output
            )
