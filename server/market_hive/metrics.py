"""Consensus quality metrics — one snapshot per terminated run (PRD observability).

Pure computation over already-persisted rows: no LLM calls, no writes, zero
behavioral influence on the swarm. Every top-level block is *independently
nullable* — missing embeddings null out ``duplication``, a schema that
predates a given feature nulls out that feature's block, and a block with
nothing to report (no contestation activity, no ratification) is null rather
than a wall of zeros. Feature tolerance is structural: each optional block is
wrapped in a try/except SELECT, never an import-time feature check, so this
module works unmodified against both old and new database schemas.

Computed once, at run finalization, immediately before the ``convergence``
step — see ``orchestrator.run_swarm``.
"""

from __future__ import annotations

import json
import math
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from server.llm.embeddings import cosine


def _gini(values: list[float]) -> float:
    """Standard Gini coefficient over non-negative values; 0.0 for empty/uniform."""
    n = len(values)
    if n == 0:
        return 0.0
    s = sorted(values)
    total = sum(s)
    if total == 0:
        return 0.0
    cum = sum((i + 1) * v for i, v in enumerate(s))
    return (2 * cum) / (n * total) - (n + 1) / n


def _entropy(counts: list[int]) -> float:
    """Shannon entropy (bits) over a distribution of non-negative counts; 0.0
    for empty/degenerate (single-bucket) distributions."""
    total = sum(counts)
    if total <= 0:
        return 0.0
    probs = [c / total for c in counts if c > 0]
    return -sum(p * math.log2(p) for p in probs)


async def compute_run_metrics(db: AsyncConnection, run_id: str) -> dict[str, Any]:
    """Compute every metrics block for one run. Never raises — a block that
    can't be computed (missing schema, no data) is ``None``, not an error."""
    out: dict[str, Any] = {}
    out["duplication"] = await _duplication_block(db, run_id)
    out["citations"] = await _citations_block(db, run_id)
    out["convergence"] = await _convergence_block(db, run_id)
    out["participation"] = await _participation_block(db, run_id)
    out["contestation"] = await _optional_block(db, run_id, _contestation_block)
    out["ratification"] = await _optional_block(db, run_id, _ratification_block)
    out["cost"] = await _cost_block(db, run_id)
    return out


async def _optional_block(db: AsyncConnection, run_id: str, fn: Any) -> dict[str, Any] | None:
    try:
        result: dict[str, Any] | None = await fn(db, run_id)
        return result
    except Exception:
        await db.rollback()
        return None


async def _duplication_block(db: AsyncConnection, run_id: str) -> dict[str, Any] | None:
    """Mean, over entries with a real embedding, of that entry's highest
    same-thread cosine similarity to any other entry. ``None`` when fewer than
    two real (non-zero) embeddings exist in any single thread — offline runs
    (zero-vector fallback) null this out entirely rather than reporting a
    meaningless 0.0 or 1.0."""
    rows = (
        await db.execute(
            text(
                "SELECT thread_id, content_embedding FROM draft_entries "
                "WHERE run_id = :r AND content_embedding IS NOT NULL"
            ),
            {"r": run_id},
        )
    ).fetchall()

    by_thread: dict[str, list[list[float]]] = {}
    for thread_id, raw in rows:
        try:
            vec = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not vec or not any(vec):
            continue
        by_thread.setdefault(thread_id, []).append(vec)

    max_per_entry: list[float] = []
    for vecs in by_thread.values():
        if len(vecs) < 2:
            continue
        for i, v in enumerate(vecs):
            best = max(cosine(v, other) for j, other in enumerate(vecs) if j != i)
            max_per_entry.append(best)

    if not max_per_entry:
        return None
    return {"mean_max_pairwise_cosine": sum(max_per_entry) / len(max_per_entry)}


async def _citations_block(db: AsyncConnection, run_id: str) -> dict[str, Any]:
    """Citation concentration: Gini over each author's total citations
    received, plus mean per-entry Shannon entropy over citer distribution."""
    total = (
        await db.execute(text("SELECT COUNT(*) FROM citations WHERE run_id = :r"), {"r": run_id})
    ).scalar_one()

    by_author = (
        await db.execute(
            text(
                "SELECT d.author_id, COUNT(*) AS n FROM citations c "
                "JOIN draft_entries d ON d.id = c.cited_entry_id "
                "WHERE c.run_id = :r GROUP BY d.author_id"
            ),
            {"r": run_id},
        )
    ).fetchall()
    gini_received = _gini([float(n) for _, n in by_author])

    per_entry = (
        await db.execute(
            text(
                "SELECT cited_entry_id, citing_agent_id, COUNT(*) AS n FROM citations "
                "WHERE run_id = :r GROUP BY cited_entry_id, citing_agent_id"
            ),
            {"r": run_id},
        )
    ).fetchall()
    by_entry: dict[str, list[int]] = {}
    for entry_id, _citer, n in per_entry:
        by_entry.setdefault(entry_id, []).append(n)
    entropies = [_entropy(counts) for counts in by_entry.values()]
    mean_entropy = sum(entropies) / len(entropies) if entropies else 0.0

    return {
        "total": total,
        "gini_received": gini_received,
        "mean_citer_entropy": mean_entropy,
    }


async def _convergence_block(db: AsyncConnection, run_id: str) -> dict[str, Any]:
    """Per-round promotion counts, the first round anything confirmed, and the
    fraction of all draft entries that evaporated (soft-deleted as stale)."""
    promo_rows = (
        await db.execute(
            text(
                "SELECT round_confirmed, COUNT(*) AS n FROM confirmed_entries "
                "WHERE run_id = :r AND entry_type = 'finding' GROUP BY round_confirmed"
            ),
            {"r": run_id},
        )
    ).fetchall()
    confirmed_per_round = {str(round_): n for round_, n in promo_rows}
    first_promotion_round = min((round_ for round_, _ in promo_rows), default=None)

    total_drafts = (
        await db.execute(
            text("SELECT COUNT(*) FROM draft_entries WHERE run_id = :r"), {"r": run_id}
        )
    ).scalar_one()
    evaporated = (
        await db.execute(
            text("SELECT COUNT(*) FROM draft_entries WHERE run_id = :r AND is_visible = false"),
            {"r": run_id},
        )
    ).scalar_one()
    evaporation_rate = (evaporated / total_drafts) if total_drafts else 0.0

    return {
        "confirmed_per_round": confirmed_per_round,
        "first_promotion_round": first_promotion_round,
        "evaporation_rate": evaporation_rate,
    }


async def _participation_block(db: AsyncConnection, run_id: str) -> dict[str, Any]:
    """Per-agent post counts, the auction abstention rate, and (when
    ``turn_log`` exists — resilient runs) the adaptive-skip rate."""
    post_rows = (
        await db.execute(
            text(
                "SELECT author_id, COUNT(*) AS n FROM draft_entries "
                "WHERE run_id = :r GROUP BY author_id"
            ),
            {"r": run_id},
        )
    ).fetchall()
    posts_by_agent: dict[str, int] = {str(author_id): int(n) for author_id, n in post_rows}

    total_bids = (
        await db.execute(text("SELECT COUNT(*) FROM bids WHERE run_id = :r"), {"r": run_id})
    ).scalar_one()
    abstained = (
        await db.execute(
            text("SELECT COUNT(*) FROM bids WHERE run_id = :r AND abstained = true"),
            {"r": run_id},
        )
    ).scalar_one()
    abstention_rate = (abstained / total_bids) if total_bids else 0.0

    skip_rate: float | None = None
    try:
        total_turns = (
            await db.execute(text("SELECT COUNT(*) FROM turn_log WHERE run_id = :r"), {"r": run_id})
        ).scalar_one()
        skipped = (
            await db.execute(
                text("SELECT COUNT(*) FROM turn_log WHERE run_id = :r AND status = 'skipped'"),
                {"r": run_id},
            )
        ).scalar_one()
        skip_rate = (skipped / total_turns) if total_turns else 0.0
    except Exception:
        await db.rollback()

    return {
        "posts_by_agent": posts_by_agent,
        "abstention_rate": abstention_rate,
        "skip_rate": skip_rate,
    }


async def _contestation_block(db: AsyncConnection, run_id: str) -> dict[str, Any] | None:
    """Dispute/contest/re-affirm/retract activity (contestable consensus).
    Raises (caught by ``_optional_block``) on a schema without ``disputes`` or
    ``confirmed_entries.status`` — pre-feature databases. ``None`` when the
    feature exists but nothing contestation-related happened this run."""
    disputes_total = (
        await db.execute(text("SELECT COUNT(*) FROM disputes WHERE run_id = :r"), {"r": run_id})
    ).scalar_one()
    contested = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM confirmed_entries WHERE run_id = :r AND status = 'contested'"
            ),
            {"r": run_id},
        )
    ).scalar_one()
    retracted = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM confirmed_entries WHERE run_id = :r AND status = 'retracted'"
            ),
            {"r": run_id},
        )
    ).scalar_one()
    if disputes_total == 0 and contested == 0 and retracted == 0:
        return None
    return {
        "disputes_total": disputes_total,
        "contested_count": contested,
        "retracted_count": retracted,
    }


async def _ratification_block(db: AsyncConnection, run_id: str) -> dict[str, Any] | None:
    """The run's ratification vote (ratified synthesis). ``None`` when the
    column doesn't exist (caught by ``_optional_block``) or was never set."""
    raw = (
        await db.execute(text("SELECT ratification FROM swarm_runs WHERE id = :r"), {"r": run_id})
    ).scalar()
    if not raw:
        return None
    result: dict[str, Any] = json.loads(raw)
    return result


async def _cost_block(db: AsyncConnection, run_id: str) -> dict[str, Any]:
    """Total tokens spent and tokens per confirmed finding (``None`` when
    nothing confirmed — the ratio is undefined, not infinite)."""
    raw = (
        await db.execute(text("SELECT token_usage FROM swarm_runs WHERE id = :r"), {"r": run_id})
    ).scalar()
    usage = json.loads(raw) if raw else {}
    tokens_total = usage.get("total", 0)

    n_confirmed = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM confirmed_entries "
                "WHERE run_id = :r AND entry_type = 'finding'"
            ),
            {"r": run_id},
        )
    ).scalar_one()
    tokens_per_confirmed_finding = (tokens_total / n_confirmed) if n_confirmed else None

    return {
        "tokens_total": tokens_total,
        "tokens_per_confirmed_finding": tokens_per_confirmed_finding,
    }
