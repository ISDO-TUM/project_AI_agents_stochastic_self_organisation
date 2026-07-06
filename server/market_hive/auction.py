"""Auction engine — agent self-selection into a contract (PRD §6.2).

The auction is the phase where agents self-select into a contract. It runs in
four phases:

  1. **Invitation** (server-side, no LLM): every agent is scored against the
     contract embedding; those at or above ``invite_floor`` are invited.
  2. **Self-selection** (one LLM call per invited agent): the agent calls
     ``submit_bid`` or ``abstain``. That loop is driven by the orchestrator;
     this module only *records* the resulting bids/abstentions.
  3. **Taker selection**: bidders are ranked and the top ``max_takers`` become
     takers; the rest become observers. A run with zero bidders is aborted.
  4. **Thread assignment** (multi-step only): each taker bids per thread, and
     this module reports which threads ended up with no takers so the caller
     can trigger a mini-auction / ``request_expertise``.

This module owns only the *deterministic* server-side logic. The LLM-driven
self-selection conversation lives in the orchestrator, which calls
``record_bid`` / ``record_abstention`` as the agents make tool calls and then
``select_takers`` once the auction closes.

Two PRD points are reconciled here (both flagged in the progress doc):

* **Taker ranking.** §6.2 prose says "top ``max_takers`` by ``preliminary_score``"
  while the same section also gives a fuller ``bid_score`` formula. The
  ``gamma`` term in that formula is ``contract.confidence``, which is constant
  across all bidders for a given contract, so it never changes the *ranking* —
  ranking by ``bid_score`` is therefore equivalent to ranking by
  ``alpha·cosine + beta·trust``. We rank by the full ``bid_score`` (the richer
  signal the formula was written for) and store both scores on the bid row.
* **Abstention vs. observer.** §6.2's "observer designation" lumps abstainers
  in with bid-and-lost agents, but the ``abstain`` tool spec (§8) is explicit
  that a voluntary abstention is a *non-participant* with **no** trust change,
  while only *bid-and-lost* agents become observers (trust decremented at run
  end). We follow the tool spec: abstainers are non-participants; observers are
  exactly the bidders who were not selected.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from server.llm.embeddings import cosine
from server.market_hive.trust import trust_for_all

logger = logging.getLogger(__name__)

# ── Defaults (mirror SWARM_DEFAULTS in PRD §15) ────────────────────────────────
DEFAULT_INVITE_FLOOR = 0.3
DEFAULT_MIN_TAKERS = 2
DEFAULT_MAX_TAKERS = 5
DEFAULT_ALPHA = 0.5
DEFAULT_BETA = 0.4
DEFAULT_GAMMA = 0.1
DEFAULT_TRUST = 0.5  # starting trust for an agent with no agent_trust row


@dataclass
class Invitation:
    """An agent invited to the auction, with the scores used to rank it."""

    agent_id: str
    agent_name: str
    preliminary_score: float  # cosine(capability_embedding, contract_embedding)
    trust_score: float  # agent_trust[task_type], default 0.5


@dataclass
class TakerSelection:
    """Outcome of taker selection for a contract or thread."""

    takers: list[str] = field(default_factory=list)  # selected agent_ids
    observers: list[str] = field(default_factory=list)  # bid-and-lost agent_ids
    aborted: bool = False
    reason: str | None = None


class AuctionEngine:
    """Deterministic server-side auction logic for one DB connection."""

    def __init__(
        self,
        db: AsyncConnection,
        *,
        invite_floor: float = DEFAULT_INVITE_FLOOR,
        min_takers: int = DEFAULT_MIN_TAKERS,
        max_takers: int = DEFAULT_MAX_TAKERS,
        alpha: float = DEFAULT_ALPHA,
        beta: float = DEFAULT_BETA,
        gamma: float = DEFAULT_GAMMA,
    ) -> None:
        self._db = db
        self.invite_floor = invite_floor
        self.min_takers = min_takers
        self.max_takers = max_takers
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma

    @classmethod
    def from_config(cls, db: AsyncConnection, config: Any) -> AuctionEngine:
        """Build an engine from a ``SwarmRunConfig`` (or any object with the fields)."""
        return cls(
            db,
            invite_floor=config.invite_floor,
            min_takers=config.min_takers,
            max_takers=config.max_takers,
            alpha=config.alpha,
            beta=config.beta,
            gamma=config.gamma,
        )

    # ── scoring ────────────────────────────────────────────────────────────

    def compute_bid_score(
        self,
        *,
        preliminary_score: float,
        trust_score: float,
        mm_confidence: float,
    ) -> float:
        """``bid_score`` per PRD §6.2.

        The PRD writes the third term as ``gamma * (1 - (1 - confidence))``,
        which is algebraically just ``gamma * confidence``.
        """
        return self.alpha * preliminary_score + self.beta * trust_score + self.gamma * mm_confidence

    # ── Phase 1: invitation ──────────────────────────────────────────────────

    async def invite(self, *, run_id: str, contract_id: str) -> list[Invitation]:
        """Score every agent against the contract embedding; return the invited set.

        An agent is invited when its cosine similarity to the contract embedding
        is ``>= invite_floor``. When the contract has no embedding yet, or an
        agent has no ``capability_embedding``, we cannot discriminate, so we
        invite inclusively (score 0.0) rather than abort the run — consistent
        with the Market Maker's "never block the run" philosophy. For the same
        reason, if the floor would invite *nobody*, every agent is invited
        instead (real scores kept for ranking) so self-selection — not a cosine
        pre-filter — decides who participates.
        """
        contract = (
            (
                await self._db.execute(
                    text("SELECT task_type, contract_embedding FROM contracts WHERE id = :id"),
                    {"id": contract_id},
                )
            )
            .mappings()
            .fetchone()
        )
        if contract is None:
            return []

        task_type: str = contract["task_type"]
        contract_emb = self._parse_embedding(contract["contract_embedding"])

        rows = (
            (await self._db.execute(text("SELECT id, name, capability_embedding FROM agents")))
            .mappings()
            .fetchall()
        )

        trust_by_agent = await self._trust_scores(task_type, contract_emb)

        invitations: list[Invitation] = []
        all_agents: list[Invitation] = []
        for row in rows:
            agent_emb = self._parse_embedding(row["capability_embedding"])
            if contract_emb is not None and agent_emb is not None:
                score = cosine(agent_emb, contract_emb)
                invited = score >= self.invite_floor
            else:
                # Missing embedding on either side → cannot discriminate; invite.
                score = 0.0
                invited = True
            candidate = Invitation(
                agent_id=row["id"],
                agent_name=row["name"],
                preliminary_score=score,
                trust_score=trust_by_agent.get(row["id"], DEFAULT_TRUST),
            )
            all_agents.append(candidate)
            if invited:
                invitations.append(candidate)

        # The cosine floor is a pre-filter to skip clearly-irrelevant agents, not
        # a hard run gate. If it excludes *everyone* (e.g. a short contract prompt
        # vs. role descriptions scores below the floor for all agents), inviting
        # nobody would abort the whole run — which contradicts the "never block the
        # run" philosophy. Fall back to inviting every agent (real cosine scores
        # preserved for ranking) and let the LLM self-selection (bid/abstain) be
        # the real filter. When some agents do clear the floor, this is a no-op.
        if not invitations:
            return all_agents
        return invitations

    # ── Phase 2: recording self-selection ────────────────────────────────────

    async def resolve_thread_id(
        self, *, contract_id: str | None, thread_id: str | None
    ) -> str | None:
        """Validate an LLM-supplied ``thread_id`` against real threads for this contract.

        The auction prompt shows agents each thread's id to copy verbatim, but an
        LLM can still echo the title or invent an id instead — inserting that
        straight into ``bids.thread_id`` would FK-violate (PRD "never block the
        run" philosophy: a bad copy should degrade to a contract-level bid, not
        crash the turn).
        """
        if thread_id is None or contract_id is None:
            return thread_id
        row = (
            await self._db.execute(
                text("SELECT 1 FROM threads WHERE id = :id AND contract_id = :contract_id"),
                {"id": thread_id, "contract_id": contract_id},
            )
        ).fetchone()
        if row is None:
            logger.warning(
                "auction: thread_id %r not found for contract %s — treating as "
                "contract-level bid",
                thread_id,
                contract_id,
            )
            return None
        return thread_id

    async def record_bid(
        self,
        *,
        run_id: str,
        agent_id: str,
        contract_id: str | None = None,
        thread_id: str | None = None,
        justification: str = "",
        preliminary_score: float = 0.0,
    ) -> str:
        """Record a ``submit_bid`` call. Returns the bid_id."""
        return await self._insert_bid(
            run_id=run_id,
            agent_id=agent_id,
            contract_id=contract_id,
            thread_id=thread_id,
            justification=justification,
            preliminary_score=preliminary_score,
            abstained=False,
        )

    async def record_abstention(
        self,
        *,
        run_id: str,
        agent_id: str,
        contract_id: str | None = None,
        thread_id: str | None = None,
        reason: str = "",
    ) -> str:
        """Record an ``abstain`` call. A voluntary abstention is a non-participant.

        ``is_observer`` stays false: abstainers carry no trust penalty (PRD §8).
        """
        return await self._insert_bid(
            run_id=run_id,
            agent_id=agent_id,
            contract_id=contract_id,
            thread_id=thread_id,
            justification=reason,
            preliminary_score=0.0,
            abstained=True,
        )

    # ── Phase 3: taker selection ──────────────────────────────────────────────

    async def select_takers(
        self,
        *,
        run_id: str,
        contract_id: str,
        thread_id: str | None = None,
    ) -> TakerSelection:
        """Select takers from the recorded bids and mark observers.

        Ranks active (non-abstained) bidders by ``bid_score`` and keeps the top
        ``max_takers``. The remaining bidders become observers. A run with zero
        active bidders is aborted. ``thread_id=None`` selects at the contract
        level; pass a ``thread_id`` to select for a single thread (multi-step).
        """
        contract = (
            (
                await self._db.execute(
                    text(
                        "SELECT task_type, confidence, contract_embedding "
                        "FROM contracts WHERE id = :id"
                    ),
                    {"id": contract_id},
                )
            )
            .mappings()
            .fetchone()
        )
        mm_confidence = float(contract["confidence"]) if contract else 0.0
        task_type = contract["task_type"] if contract else ""
        contract_emb = self._parse_embedding(contract["contract_embedding"]) if contract else None
        trust_by_agent = await self._trust_scores(task_type, contract_emb)

        thread_clause = (
            "AND thread_id = :thread_id" if thread_id is not None else "AND thread_id IS NULL"
        )
        params: dict[str, Any] = {"run_id": run_id, "contract_id": contract_id}
        if thread_id is not None:
            params["thread_id"] = thread_id

        bidders = (
            (
                await self._db.execute(
                    text(
                        f"""
                    SELECT id, agent_id, preliminary_score
                    FROM bids
                    WHERE run_id = :run_id
                      AND contract_id = :contract_id
                      AND abstained = false
                      {thread_clause}
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .fetchall()
        )

        if not bidders:
            return TakerSelection(
                aborted=True,
                reason="No agents qualified. Run aborted.",
            )

        ranked = sorted(
            bidders,
            key=lambda b: self.compute_bid_score(
                preliminary_score=float(b["preliminary_score"]),
                trust_score=trust_by_agent.get(b["agent_id"], DEFAULT_TRUST),
                mm_confidence=mm_confidence,
            ),
            reverse=True,
        )

        taker_rows = ranked[: self.max_takers]
        observer_rows = ranked[self.max_takers :]

        taker_ids = [b["agent_id"] for b in taker_rows]
        observer_ids = [b["agent_id"] for b in observer_rows]

        for b in taker_rows:
            await self._db.execute(
                text("UPDATE bids SET is_taker = true, is_observer = false WHERE id = :id"),
                {"id": b["id"]},
            )
        for b in observer_rows:
            await self._db.execute(
                text("UPDATE bids SET is_taker = false, is_observer = true WHERE id = :id"),
                {"id": b["id"]},
            )
        await self._db.commit()

        return TakerSelection(takers=taker_ids, observers=observer_ids)

    # ── Phase 4: thread coverage (multi-step) ─────────────────────────────────

    async def uncovered_threads(
        self,
        *,
        run_id: str,
        contract_id: str,
    ) -> list[str]:
        """Return thread_ids that have zero takers after thread assignment.

        The caller (orchestrator / amendment engine) uses this to trigger a
        mini-auction or dissolve a thread into its parent.
        """
        thread_rows = (
            await self._db.execute(
                text("SELECT id FROM threads WHERE contract_id = :cid"),
                {"cid": contract_id},
            )
        ).fetchall()
        all_threads = [r[0] for r in thread_rows]

        covered_rows = (
            await self._db.execute(
                text(
                    """
                    SELECT DISTINCT thread_id FROM bids
                    WHERE run_id = :run_id
                      AND is_taker = true
                      AND thread_id IS NOT NULL
                    """
                ),
                {"run_id": run_id},
            )
        ).fetchall()
        covered = {r[0] for r in covered_rows}

        return [tid for tid in all_threads if tid not in covered]

    # ── queries ───────────────────────────────────────────────────────────────

    async def get_takers(self, *, run_id: str) -> list[str]:
        """Distinct agent_ids selected as takers for this run."""
        rows = (
            await self._db.execute(
                text(
                    "SELECT DISTINCT agent_id FROM bids WHERE run_id = :run_id AND is_taker = true"
                ),
                {"run_id": run_id},
            )
        ).fetchall()
        return [r[0] for r in rows]

    async def get_observers(self, *, run_id: str) -> list[str]:
        """Distinct agent_ids that bid and lost (observers).

        An agent that won a taker slot anywhere in the run is never an observer,
        even if it lost a different thread bid.
        """
        observer_rows = (
            await self._db.execute(
                text(
                    "SELECT DISTINCT agent_id FROM bids "
                    "WHERE run_id = :run_id AND is_observer = true"
                ),
                {"run_id": run_id},
            )
        ).fetchall()
        observers = {r[0] for r in observer_rows}
        takers = set(await self.get_takers(run_id=run_id))
        return sorted(observers - takers)

    # ── helpers ────────────────────────────────────────────────────────────────

    async def _trust_scores(
        self, domain: str, contract_embedding: list[float] | None
    ) -> dict[str, float]:
        """Map of agent_id → trust_score for this contract (only agents with
        ledger history). Similarity-weighted against ``contract_embedding``
        when present; falls back to exact domain-label matching offline."""
        scores: dict[str, float] = await trust_for_all(
            self._db, contract_embedding=contract_embedding, domain_label=domain
        )
        return scores

    async def _insert_bid(
        self,
        *,
        run_id: str,
        agent_id: str,
        contract_id: str | None,
        thread_id: str | None,
        justification: str,
        preliminary_score: float,
        abstained: bool,
    ) -> str:
        bid_id = str(uuid.uuid4())
        await self._db.execute(
            text(
                """
                INSERT INTO bids
                    (id, run_id, contract_id, thread_id, agent_id,
                     justification, preliminary_score, is_taker, is_observer, abstained)
                VALUES
                    (:id, :run_id, :contract_id, :thread_id, :agent_id,
                     :justification, :preliminary_score, false, false, :abstained)
                """
            ),
            {
                "id": bid_id,
                "run_id": run_id,
                "contract_id": contract_id,
                "thread_id": thread_id,
                "agent_id": agent_id,
                "justification": justification,
                "preliminary_score": preliminary_score,
                "abstained": abstained,
            },
        )
        await self._db.commit()
        return bid_id

    @staticmethod
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
