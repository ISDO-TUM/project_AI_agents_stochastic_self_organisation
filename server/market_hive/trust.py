"""Trust registry — append-only evidence ledger at run end (PRD §6.7).

This is the swarm's only *persistent* learning loop. Within a run, citations act
as pheromones (good posts get promoted); the trust registry lifts that signal
across runs: agents whose confirmed findings the swarm actually built on gain
domain trust, which in turn lifts their bid score in future auctions
(``auction.py`` reads it). There is no central router — the right experts rise
to the top of the relevant markets purely from their track record.

Called once, at run end, behind the ``TrustRegistry`` protocol the orchestrator
already depends on. ``NoopTrustRegistry`` is kept for tests / runs that want the
loop disabled without special-casing the orchestrator.

Hardened design (2026-07-04-trust-registry-hardening), replacing the earlier
zero-sum share/observer-penalty model:

* **``trust_events`` is the source of truth.** Every ``TrustRegistry.update`` call
  emits *absolute*, performance-only events — a taker's credit never depends on
  a co-taker's outcome, so two takers who both did well both get full credit.
  ``agent_trust`` becomes a materialized read cache recomputed from the ledger,
  so existing readers (``AgentTrustPanel``, etc.) keep working unchanged.
* **Bayesian shrinkage + recency decay.** ``score_events`` blends a weak prior
  (``K_PRIOR`` pseudo-evidence at 0.5) with the agent's weighted event history
  (``DECAY`` per event-age), so one lucky run cannot outweigh a long track
  record, and stale evidence fades relative to fresh evidence. Bounded to
  ``[0, 1]`` by construction (a weighted average of the prior and outcomes in
  ``[0, 1]``) — no clamping needed anywhere.
* **Domain matching by embedding similarity**, not exact ``task_type`` string
  equality — a "legal review" and a "contract analysis" contract can now share
  trust evidence proportional to how semantically close they are. Offline
  (no embeddings) falls back to exact ``domain_label`` equality.
* **Observers and abstainers get zero events.** They were invited but did not
  do work this run — that is not evidence of anything, good or bad.
* **Idempotent.** ``UNIQUE(run_id, agent_id, kind)`` means re-running ``update``
  for an already-recorded run inserts nothing new (each kind is one row per
  run per agent, aggregating that kind's volume for the run).
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from server.llm.embeddings import cosine

# ── Scoring constants ─────────────────────────────────────────────────────────
DEFAULT_TRUST = 0.5  # returned for agents with no ledger history at all
K_PRIOR = 4.0  # prior pseudo-evidence count — shrinks small samples toward PRIOR
DECAY = 0.9  # per-event-age recency decay
PRIOR = 0.5  # the prior belief itself (neutral)

# Base per-instance weight for each event kind (aggregated per run — see
# ``_taker_events``). ``citations_received`` has no fixed base weight: its
# weight is a saturating function of the citation count (see below).
_WEIGHT_FINDING_CONFIRMED = 1.0
_WEIGHT_ENTRY_EVAPORATED = 0.4
_WEIGHT_FINDING_RETRACTED = 1.5


@dataclass(frozen=True)
class TrustEvent:
    """One piece of evidence in an agent's ledger, ready for scoring.

    ``age`` is an events-ago ordinal (0 = newest) within whatever event set is
    being scored — the caller assigns it after sorting/filtering, it is not
    stored as such in the DB (``created_at`` is the source of truth for order).
    """

    kind: str
    outcome: float  # in [0, 1]
    weight: float
    domain_embedding: list[float] | None
    domain_label: str
    age: int


def _similarity(ev: TrustEvent, contract_embedding: list[float] | None) -> float:
    """Domain-match weight for one event against the contract being scored.

    Offline (no contract embedding) or an event with no stored domain embedding
    falls back to 1.0 — the caller is expected to have already pre-filtered the
    event list to exact ``domain_label`` matches in that case, so "no
    discrimination possible" and "already matched" collapse to the same value.
    """
    if contract_embedding is None or ev.domain_embedding is None:
        return 1.0
    return max(0.0, cosine(ev.domain_embedding, contract_embedding)) ** 2


def score_events(
    events: list[TrustEvent],
    *,
    contract_embedding: list[float] | None,
    k_prior: float = K_PRIOR,
    decay: float = DECAY,
) -> float:
    """Bayesian-shrunk, recency-decayed, domain-weighted trust score in [0, 1].

    ``trust = (k_prior·PRIOR + Σ wᵢ·outcomeᵢ) / (k_prior + Σ wᵢ)`` where
    ``wᵢ = event.weight · decay**event.age · similarity(event, contract)``.
    A weighted average of values in ``[0, 1]`` (the prior and every outcome) is
    itself in ``[0, 1]`` — no clamping is ever needed.
    """
    num = k_prior * PRIOR
    den = k_prior
    for ev in events:
        w = ev.weight * (decay**ev.age) * _similarity(ev, contract_embedding)
        num += w * ev.outcome
        den += w
    return num / den


class NoopTrustRegistry:
    """Placeholder: records nothing. Use to disable the cross-run loop."""

    async def update(
        self, *, run_id: str, takers: list[str], observers: list[str], db: AsyncConnection
    ) -> None:
        return None


class TrustRegistry:
    """Emits an append-only ledger of performance events at run end (PRD §6.7)."""

    @classmethod
    def from_config(cls, config: Any) -> TrustRegistry:
        """Build from a ``SwarmRunConfig``.

        The current config does not surface trust knobs; this keeps a stable
        construction seam (mirrors ``ConvergenceEngine``).
        """
        return cls()

    async def update(
        self, *, run_id: str, takers: list[str], observers: list[str], db: AsyncConnection
    ) -> None:
        """Record this run's performance events for every taker.

        Observers/abstainers get zero events — no penalty of any kind, they
        simply did not participate. Idempotent: re-running for an
        already-recorded run inserts nothing (the UNIQUE guard on
        ``trust_events`` is caught and treated as already-done).
        """
        domain = await self._contract_domain(run_id=run_id, db=db)
        if domain is None:
            # No contract for this run (e.g. aborted before the Market Maker) —
            # there is no domain to attribute trust to. Nothing to record.
            return
        contract_embedding = await self._contract_embedding(run_id=run_id, db=db)
        embedding_json = json.dumps(contract_embedding) if contract_embedding else None

        for agent_id in takers:
            inserted_any = False
            for kind, outcome, weight in await self._taker_events(
                db, run_id=run_id, agent_id=agent_id
            ):
                if await self._insert_event(
                    db,
                    run_id=run_id,
                    agent_id=agent_id,
                    kind=kind,
                    outcome=outcome,
                    weight=weight,
                    domain_label=domain,
                    domain_embedding=embedding_json,
                ):
                    inserted_any = True
            await self._recompute_cache(
                db, agent_id=agent_id, domain=domain, participated=inserted_any
            )

    # ── event derivation ─────────────────────────────────────────────────────

    async def _taker_events(
        self, db: AsyncConnection, *, run_id: str, agent_id: str
    ) -> list[tuple[str, float, float]]:
        """This taker's absolute ``(kind, outcome, weight)`` events for the run.

        One aggregated row per kind (the UNIQUE(run_id, agent_id, kind) guard
        allows no more): each kind's weight sums that kind's per-instance base
        weight over however many times it happened this run, except
        ``citations_received`` whose weight is a saturating function of the
        total citation count, not a linear sum.
        """
        events: list[tuple[str, float, float]] = []

        n_confirmed = await self._count_confirmed_findings(db, run_id=run_id, agent_id=agent_id)
        if n_confirmed > 0:
            events.append(("finding_confirmed", 1.0, _WEIGHT_FINDING_CONFIRMED * n_confirmed))

        n_cites = await self._count_citations_received(db, run_id=run_id, agent_id=agent_id)
        if n_cites > 0:
            w = min(1.0, math.log1p(n_cites) / math.log1p(10))
            events.append(("citations_received", 1.0, w))

        n_evaporated = await self._count_evaporated(db, run_id=run_id, agent_id=agent_id)
        if n_evaporated > 0:
            events.append(("entry_evaporated", 0.0, _WEIGHT_ENTRY_EVAPORATED * n_evaporated))

        n_retracted = await self._count_retracted(db, run_id=run_id, agent_id=agent_id)
        if n_retracted > 0:
            events.append(("finding_retracted", 0.0, _WEIGHT_FINDING_RETRACTED * n_retracted))

        return events

    async def _count_confirmed_findings(
        self, db: AsyncConnection, *, run_id: str, agent_id: str
    ) -> int:
        return (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM confirmed_entries ce "
                    "JOIN draft_entries de ON de.id = ce.source_draft_id "
                    "WHERE ce.run_id = :run_id AND ce.entry_type = 'finding' "
                    "AND de.author_id = :agent_id"
                ),
                {"run_id": run_id, "agent_id": agent_id},
            )
        ).scalar_one()

    async def _count_citations_received(
        self, db: AsyncConnection, *, run_id: str, agent_id: str
    ) -> int:
        """Citations received on entries this agent authored that are still
        visible — a soft-deleted (evaporated) entry's earlier citations don't
        count as ongoing evidence of quality."""
        return (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM citations c "
                    "JOIN draft_entries d ON d.id = c.cited_entry_id "
                    "WHERE c.run_id = :run_id AND d.author_id = :agent_id "
                    "AND d.is_visible = true"
                ),
                {"run_id": run_id, "agent_id": agent_id},
            )
        ).scalar_one()

    async def _count_evaporated(self, db: AsyncConnection, *, run_id: str, agent_id: str) -> int:
        """Entries this agent authored that were soft-deleted as stale — but
        not merged into a confirmed finding (contestable-consensus dedup),
        which is reinforcement, not evaporation. Feature-detected: pre-dedup
        databases have no ``merged_into`` column, so every invisible entry
        counts as evaporated there."""
        try:
            return (
                await db.execute(
                    text(
                        "SELECT COUNT(*) FROM draft_entries "
                        "WHERE run_id = :run_id AND author_id = :agent_id "
                        "AND is_visible = false AND merged_into IS NULL"
                    ),
                    {"run_id": run_id, "agent_id": agent_id},
                )
            ).scalar_one()
        except Exception:
            await db.rollback()
            return (
                await db.execute(
                    text(
                        "SELECT COUNT(*) FROM draft_entries "
                        "WHERE run_id = :run_id AND author_id = :agent_id AND is_visible = false"
                    ),
                    {"run_id": run_id, "agent_id": agent_id},
                )
            ).scalar_one()

    async def _count_retracted(self, db: AsyncConnection, *, run_id: str, agent_id: str) -> int:
        """Findings this agent authored that were retracted (contestable
        consensus). Feature-detected: 0 when the ``status`` column doesn't exist."""
        try:
            return (
                await db.execute(
                    text(
                        "SELECT COUNT(*) FROM confirmed_entries ce "
                        "JOIN draft_entries de ON de.id = ce.source_draft_id "
                        "WHERE ce.run_id = :run_id AND de.author_id = :agent_id "
                        "AND ce.status = 'retracted'"
                    ),
                    {"run_id": run_id, "agent_id": agent_id},
                )
            ).scalar_one()
        except Exception:
            await db.rollback()
            return 0

    # ── persistence ──────────────────────────────────────────────────────────

    async def _contract_domain(self, *, run_id: str, db: AsyncConnection) -> str | None:
        """The run's trust domain label — the contract ``task_type`` (one per run)."""
        row = (
            await db.execute(
                text("SELECT task_type FROM contracts WHERE run_id = :run_id LIMIT 1"),
                {"run_id": run_id},
            )
        ).fetchone()
        return str(row[0]) if row is not None else None

    async def _contract_embedding(
        self, *, run_id: str, db: AsyncConnection
    ) -> list[float] | None:
        row = (
            await db.execute(
                text("SELECT contract_embedding FROM contracts WHERE run_id = :run_id LIMIT 1"),
                {"run_id": run_id},
            )
        ).fetchone()
        if row is None or not row[0]:
            return None
        try:
            vec = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None
        return vec if vec and any(vec) else None

    async def _insert_event(
        self,
        db: AsyncConnection,
        *,
        run_id: str,
        agent_id: str,
        kind: str,
        outcome: float,
        weight: float,
        domain_label: str,
        domain_embedding: str | None,
    ) -> bool:
        """Insert one ledger row. Returns ``False`` (no-op) if this
        ``(run_id, agent_id, kind)`` was already recorded — idempotency."""
        try:
            async with db.begin_nested():
                await db.execute(
                    text(
                        """
                        INSERT INTO trust_events
                            (id, run_id, agent_id, kind, outcome, weight,
                             domain_label, domain_embedding)
                        VALUES (:id, :run_id, :agent_id, :kind, :outcome, :weight,
                                :domain_label, :domain_embedding)
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "run_id": run_id,
                        "agent_id": agent_id,
                        "kind": kind,
                        "outcome": outcome,
                        "weight": weight,
                        "domain_label": domain_label,
                        "domain_embedding": domain_embedding,
                    },
                )
            await db.commit()
            return True
        except IntegrityError:
            await db.rollback()
            return False

    async def _recompute_cache(
        self, db: AsyncConnection, *, agent_id: str, domain: str, participated: bool
    ) -> None:
        """Recompute the ``agent_trust`` materialized-cache row for (agent, domain)
        from the agent's full ledger, label-filtered to this domain (offline
        scoring — the cache has no contract to compare embeddings against)."""
        events = await self._ledger_events_for_domain(db, agent_id=agent_id, domain=domain)
        score = score_events(events, contract_embedding=None)

        row = (
            await db.execute(
                text(
                    "SELECT runs_participated FROM agent_trust "
                    "WHERE agent_id = :agent_id AND domain = :domain"
                ),
                {"agent_id": agent_id, "domain": domain},
            )
        ).fetchone()
        runs_inc = 1 if participated else 0

        if row is not None:
            await db.execute(
                text(
                    "UPDATE agent_trust "
                    "SET trust_score = :score, "
                    "    runs_participated = runs_participated + :inc, "
                    "    updated_at = CURRENT_TIMESTAMP "
                    "WHERE agent_id = :agent_id AND domain = :domain"
                ),
                {"score": score, "inc": runs_inc, "agent_id": agent_id, "domain": domain},
            )
        else:
            await db.execute(
                text(
                    "INSERT INTO agent_trust "
                    "    (agent_id, domain, trust_score, runs_participated) "
                    "VALUES (:agent_id, :domain, :score, :inc)"
                ),
                {"agent_id": agent_id, "domain": domain, "score": score, "inc": runs_inc},
            )
        await db.commit()

    async def _ledger_events_for_domain(
        self, db: AsyncConnection, *, agent_id: str, domain: str
    ) -> list[TrustEvent]:
        rows = (
            await db.execute(
                text(
                    "SELECT kind, outcome, weight, domain_label, domain_embedding "
                    "FROM trust_events WHERE agent_id = :agent_id AND domain_label = :domain "
                    "ORDER BY created_at DESC"
                ),
                {"agent_id": agent_id, "domain": domain},
            )
        ).mappings().all()
        events: list[TrustEvent] = []
        for age, row in enumerate(rows):
            emb = json.loads(row["domain_embedding"]) if row["domain_embedding"] else None
            events.append(
                TrustEvent(
                    kind=row["kind"],
                    outcome=float(row["outcome"]),
                    weight=float(row["weight"]),
                    domain_embedding=emb,
                    domain_label=row["domain_label"],
                    age=age,
                )
            )
        return events


# ── Auction-facing lookup (similarity-weighted, replaces exact-match) ────────


async def trust_for_all(
    db: AsyncConnection, *, contract_embedding: list[float] | None, domain_label: str
) -> dict[str, float]:
    """Score every agent with ledger history for one contract (auction ranking).

    Offline (``contract_embedding is None``): pre-filters to exact
    ``domain_label`` matches, then scores with similarity forced to 1.0 for
    what remains (label equality substitutes for cosine). Online: scores the
    agent's *entire* ledger against the contract embedding — a semantically
    close but differently-labeled domain still contributes, proportional to
    ``cosine(event, contract) ** 2``. Agents with no ledger rows are absent
    from the result; the caller defaults them to ``DEFAULT_TRUST``.
    """
    rows = (
        await db.execute(
            text(
                "SELECT agent_id, kind, outcome, weight, domain_label, domain_embedding "
                "FROM trust_events ORDER BY agent_id, created_at DESC"
            )
        )
    ).mappings().all()

    by_agent: dict[str, list[TrustEvent]] = {}
    for row in rows:
        if contract_embedding is None and row["domain_label"] != domain_label:
            continue
        emb = json.loads(row["domain_embedding"]) if row["domain_embedding"] else None
        bucket = by_agent.setdefault(row["agent_id"], [])
        bucket.append(
            TrustEvent(
                kind=row["kind"],
                outcome=float(row["outcome"]),
                weight=float(row["weight"]),
                domain_embedding=emb,
                domain_label=row["domain_label"],
                age=len(bucket),
            )
        )

    return {
        agent_id: score_events(events, contract_embedding=contract_embedding)
        for agent_id, events in by_agent.items()
    }


async def migrate_agent_trust_to_ledger(conn: AsyncConnection) -> None:
    """One-time cutover: turn each pre-ledger ``agent_trust`` row into a
    synthetic ``legacy_prior`` event so earned trust survives the ledger
    becoming the source of truth.

    Idempotent (skips an (agent, domain) that already has a ``legacy_prior``
    row) — safe to call on every startup. ``run_id`` is NULL for these events
    (no real run backs them); NULLs are not compared for SQL UNIQUE purposes,
    so the DB-level guard on ``trust_events`` cannot enforce "one legacy row
    per (agent, domain)" itself — this function does that with an explicit
    pre-check instead.
    """
    rows = (
        await conn.execute(
            text("SELECT agent_id, domain, trust_score, runs_participated FROM agent_trust")
        )
    ).mappings().all()
    for row in rows:
        existing = (
            await conn.execute(
                text(
                    "SELECT 1 FROM trust_events WHERE agent_id = :agent_id "
                    "AND domain_label = :domain AND kind = 'legacy_prior'"
                ),
                {"agent_id": row["agent_id"], "domain": row["domain"]},
            )
        ).fetchone()
        if existing is not None:
            continue
        await conn.execute(
            text(
                """
                INSERT INTO trust_events
                    (id, run_id, agent_id, kind, outcome, weight, domain_label, domain_embedding)
                VALUES (:id, NULL, :agent_id, 'legacy_prior', :outcome, :weight, :domain, NULL)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "agent_id": row["agent_id"],
                "outcome": float(row["trust_score"]),
                "weight": float(max(1, row["runs_participated"])),
                "domain": row["domain"],
            },
        )
    await conn.commit()
