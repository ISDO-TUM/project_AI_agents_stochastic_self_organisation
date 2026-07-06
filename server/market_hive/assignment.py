"""Taker → thread assignment for multi-step contracts (PRD §6.2 Phase 4, no-LLM v1).

The PRD's Phase 4 has every taker run one LLM call per thread to bid or abstain.
This module is the deterministic v1 of that phase: each taker is matched to the
thread(s) whose ``thread_embedding`` best fits its ``capability_embedding``, so
specialists work their slice of a decomposed contract instead of every taker
working every thread (which multiplies per-round LLM cost by the thread count
and re-creates exactly the expertise mismatch the Market Maker exists to avoid).

Guarantees, in line with the "never block the run" philosophy:

* every taker is assigned to at least one thread (its best match);
* every thread gets at least ``min_per_thread`` takers when enough exist —
  promotion needs multiple citers, so a one-agent thread could never confirm
  findings;
* when embeddings are missing on either side we cannot discriminate, so the
  affected taker/thread is assigned inclusively (matches the auction's fallback).

Single-thread contracts short-circuit to "everyone works the one thread", which
is exactly the pre-multi-thread behavior.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from server.llm.embeddings import cosine
from server.market_hive.schemas import ThreadSchema

# Below this, a thread can't gather the distinct citers promotion requires.
DEFAULT_MIN_PER_THREAD = 2


def _parse_embedding(raw: Any) -> list[float] | None:
    """Parse a JSON-encoded embedding column. None / empty / all-zero → None."""
    if not raw:
        return None
    try:
        vec = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return None
    if not vec or not any(vec):
        return None
    return [float(x) for x in vec]


async def assign_takers_to_threads(
    db: AsyncConnection,
    *,
    takers: list[str],
    threads: list[ThreadSchema],
    min_per_thread: int = DEFAULT_MIN_PER_THREAD,
) -> dict[str, list[str]]:
    """Map every thread id to the takers who will work it.

    Assignment lists preserve the order of ``takers`` (deterministic output for
    a given input). See the module docstring for the guarantees.
    """
    if not threads:
        return {}
    if len(threads) == 1 or len(takers) <= min_per_thread:
        return {thread.id: list(takers) for thread in threads}

    rows = (
        (await db.execute(text("SELECT id, capability_embedding FROM agents")))
        .mappings()
        .fetchall()
    )
    emb_by_agent = {r["id"]: _parse_embedding(r["capability_embedding"]) for r in rows}

    # cosine per (taker, thread) where both sides have an embedding.
    scores: dict[str, dict[str, float]] = {}
    for taker in takers:
        agent_emb = emb_by_agent.get(taker)
        if agent_emb is None:
            continue
        per_thread: dict[str, float] = {}
        for thread in threads:
            if thread.thread_embedding is not None and len(thread.thread_embedding) == len(
                agent_emb
            ):
                per_thread[thread.id] = cosine(agent_emb, thread.thread_embedding)
        if per_thread:
            scores[taker] = per_thread

    assigned: dict[str, set[str]] = {thread.id: set() for thread in threads}

    for thread in threads:
        if thread.thread_embedding is None:
            # Unscoreable thread → cannot discriminate; everyone works it.
            assigned[thread.id].update(takers)

    for taker in takers:
        taker_scores = scores.get(taker)
        if taker_scores is None:
            # Unscoreable taker → assign inclusively.
            for thread_id in assigned:
                assigned[thread_id].add(taker)
        else:
            best = max(taker_scores, key=lambda tid: taker_scores[tid])
            assigned[best].add(taker)

    # Coverage top-up: fill every under-staffed thread with its best remaining
    # matches so each thread can sustain a discussion and promote findings.
    for thread in threads:
        candidates = sorted(
            (t for t in takers if t not in assigned[thread.id] and thread.id in scores.get(t, {})),
            key=lambda t: scores[t][thread.id],
            reverse=True,
        )
        for taker in candidates:
            if len(assigned[thread.id]) >= min_per_thread:
                break
            assigned[thread.id].add(taker)

    return {thread.id: [t for t in takers if t in assigned[thread.id]] for thread in threads}
