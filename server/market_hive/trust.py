"""Trust registry — cross-run ``agent_trust`` update at run end (PRD §6.7).

This is the swarm's only *persistent* learning loop. Within a run, citations act
as pheromones (good posts get promoted); the trust registry lifts that signal
across runs: agents whose confirmed findings the swarm actually built on gain
domain trust, which in turn lifts their bid score in future auctions
(``auction.py`` reads ``agent_trust``). There is no central router — the right
experts rise to the top of the relevant markets purely from their track record.

Called once, at run end, behind the ``TrustRegistry`` protocol the orchestrator
already depends on. ``NoopTrustRegistry`` is kept for tests / runs that want the
loop disabled without special-casing the orchestrator.

Design choices (faithful to §6.7, with the gaps it leaves made explicit):

* **One domain per run.** The contract's ``task_type`` is the trust domain, matching
  how the auction reads ``trust_score[task_type]``.
* **Winner gain is proportional to confirmed-citation share.** A taker's share is
  ``their confirmed-finding citations / all confirmed-finding citations`` this run.
  ``confirmed_entries`` carries no author, so authorship is traced through
  ``source_draft_id → draft_entries.author_id`` (anchors/system entries have no
  draft source and are naturally excluded alongside the ``entry_type='finding'``
  filter).
* **Observer loss is a flat penalty.** Observers were invited but lost — a small,
  share-independent nudge downward.
* **``runs_participated`` counts takers only.** Observers never got run access
  (zero LLM calls), so they did not participate; their trust still moves, but the
  participation counter does not.
* **Deltas come from the PRD ``SWARM_DEFAULTS`` (§15):** winner gain ``0.03``,
  observer loss ``0.02``. Winner gain scales by citation share, so a run's *maximum*
  gain is ``0.03`` (full share). Override via the constructor / ``from_config``.
* **Read-modify-write, clamped to ``[0, 1]``.** Mirrors ``convergence._apply_reputation_delta``
  — portable across Postgres (prod) and SQLite (tests), no dialect-specific upsert.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# ── Defaults (PRD §6.7 / §15) ──────────────────────────────────────────────────
DEFAULT_DELTA_WINNER_GAIN = 0.03  # max per-run gain, scaled by citation share
DEFAULT_DELTA_OBSERVER_LOSS = 0.02  # flat per-run penalty for observers
DEFAULT_TRUST = 0.5  # starting cross-run trust for a new (agent, domain)


class NoopTrustRegistry:
    """Placeholder: records nothing. Use to disable the cross-run loop."""

    async def update(
        self, *, run_id: str, takers: list[str], observers: list[str], db: AsyncConnection
    ) -> None:
        return None


class TrustRegistry:
    """Applies cross-run ``agent_trust`` changes once, at run end (PRD §6.7)."""

    def __init__(
        self,
        *,
        delta_winner_gain: float = DEFAULT_DELTA_WINNER_GAIN,
        delta_observer_loss: float = DEFAULT_DELTA_OBSERVER_LOSS,
    ) -> None:
        self.delta_winner_gain = delta_winner_gain
        self.delta_observer_loss = delta_observer_loss

    @classmethod
    def from_config(cls, config: Any) -> TrustRegistry:
        """Build from a ``SwarmRunConfig``.

        The current config does not surface trust deltas; this keeps a stable
        construction seam for when they are added (mirrors ``ConvergenceEngine``).
        """
        return cls()

    async def update(
        self, *, run_id: str, takers: list[str], observers: list[str], db: AsyncConnection
    ) -> None:
        domain = await self._contract_domain(run_id=run_id, db=db)
        if domain is None:
            # No contract for this run (e.g. aborted before the Market Maker) —
            # there is no domain to attribute trust to. Nothing to record.
            return

        shares = await self._confirmed_citation_shares(run_id=run_id, db=db)

        # Takers: gain proportional to their share of confirmed-finding citations.
        # A taker with no confirmed citations still gets a row + a participation
        # tick (delta 0.0), so trust is recorded even on a flat contribution.
        for agent_id in takers:
            delta = self.delta_winner_gain * shares.get(agent_id, 0.0)
            await self._apply_trust_delta(
                run_id=run_id,
                agent_id=agent_id,
                domain=domain,
                delta=delta,
                participated=True,
                db=db,
            )

        # Observers: flat penalty, no participation tick (they got no run access).
        # An agent that won a taker slot is never in this list (auction excludes it).
        for agent_id in observers:
            await self._apply_trust_delta(
                run_id=run_id,
                agent_id=agent_id,
                domain=domain,
                delta=-self.delta_observer_loss,
                participated=False,
                db=db,
            )

    # ── helpers ──────────────────────────────────────────────────────────────────

    async def _contract_domain(self, *, run_id: str, db: AsyncConnection) -> str | None:
        """The run's trust domain — the contract ``task_type`` (one per run)."""
        row = (
            await db.execute(
                text("SELECT task_type FROM contracts WHERE run_id = :run_id LIMIT 1"),
                {"run_id": run_id},
            )
        ).fetchone()
        return str(row[0]) if row is not None else None

    async def _confirmed_citation_shares(
        self, *, run_id: str, db: AsyncConnection
    ) -> dict[str, float]:
        """Map agent_id → share of this run's confirmed-finding citations.

        ``confirmed_entries`` has no author, so authorship is traced through
        ``source_draft_id → draft_entries.author_id``. Anchors/system entries have
        no draft source and are excluded by both the join and the type filter.
        Returns ``{}`` when no findings were confirmed (every share is then 0).
        """
        rows = (
            await db.execute(
                text(
                    "SELECT d.author_id, SUM(c.citation_count) AS cites "
                    "FROM confirmed_entries c "
                    "JOIN draft_entries d ON c.source_draft_id = d.id "
                    "WHERE c.run_id = :run_id AND c.entry_type = 'finding' "
                    "GROUP BY d.author_id"
                ),
                {"run_id": run_id},
            )
        ).fetchall()
        counts = {r[0]: float(r[1] or 0.0) for r in rows}
        total = sum(counts.values())
        if total <= 0.0:
            return {}
        return {author: cites / total for author, cites in counts.items()}

    async def _apply_trust_delta(
        self,
        *,
        run_id: str,
        agent_id: str,
        domain: str,
        delta: float,
        participated: bool,
        db: AsyncConnection,
    ) -> float:
        """Read-modify-write a clamped ``agent_trust`` score (portable; no upsert)."""
        row = (
            await db.execute(
                text(
                    "SELECT trust_score, runs_participated FROM agent_trust "
                    "WHERE agent_id = :agent_id AND domain = :domain"
                ),
                {"agent_id": agent_id, "domain": domain},
            )
        ).fetchone()
        current = float(row[0]) if row is not None else DEFAULT_TRUST
        new_score = max(0.0, min(1.0, current + delta))
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
                {
                    "score": new_score,
                    "inc": runs_inc,
                    "agent_id": agent_id,
                    "domain": domain,
                },
            )
        else:
            await db.execute(
                text(
                    "INSERT INTO agent_trust "
                    "    (agent_id, domain, trust_score, runs_participated) "
                    "VALUES (:agent_id, :domain, :score, :inc)"
                ),
                {
                    "agent_id": agent_id,
                    "domain": domain,
                    "score": new_score,
                    "inc": runs_inc,
                },
            )
        return new_score
