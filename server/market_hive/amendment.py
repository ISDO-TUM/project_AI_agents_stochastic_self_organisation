"""Contract amendment engine — request_expertise → vote → new thread (PRD §6.5).

A taker who finds a gap the current team cannot fill calls ``request_expertise``.
That records a *pending* amendment and posts a SYSTEM entry to the Confirmed layer.
At the end of the round the orchestrator calls :meth:`AmendmentEngine.process_pending`,
which gathers a majority vote (all takers + the Market Maker as one equal voter) and,
on approval, creates a new thread and recruits agents for it via a mini-auction.

Design notes
------------
The *pure* operations — proposal, cap enforcement, vote tally, thread creation,
SYSTEM-entry writes — live here and are fully unit-testable against a seeded DB.
Two boundaries are injected as callables so this engine does not depend on parts
of the system that are still being built:

* ``vote_collector`` — turns a (taker, amendment) into ``"approve" | "reject"``.
  The live path uses an LLM (:func:`make_llm_vote_collector`); tests inject a fake.
* ``recruiter`` — runs the mini-auction for a newly created thread and returns the
  new takers' agent IDs. The live path (:func:`make_auction_recruiter`) drives the
  real :class:`~server.market_hive.auction.AuctionEngine`; tests inject a fake.
  ``resolve()`` leaves it optional so the pure logic stays testable without an auction.

One inner seam remains inside :func:`make_auction_recruiter`: an invited agent's
self-selection (bid vs. abstain) is one LLM call per agent, a loop the orchestrator
owns and which is not built yet. The recruiter auto-bids every invited agent until
that driver exists (or a ``self_select`` callback is supplied).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import replace
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from server.llm import call_agent
from server.llm.embeddings import cosine, embed_texts
from server.market_hive.auction import AuctionEngine, Invitation
from server.market_hive.schemas import AmendmentSchema, SimulationStep, ThreadSchema

# (taker_agent_id, amendment) -> "approve" | "reject"
VoteCollectorFn = Callable[[str, AmendmentSchema], Awaitable[Literal["approve", "reject"]]]
# (new_thread, run_id) -> list of recruited taker agent IDs
RecruiterFn = Callable[[ThreadSchema, str], Awaitable[list[str]]]
# casts the Market Maker's single equal vote
MMVoteFn = Callable[[AmendmentSchema], Awaitable[Literal["approve", "reject"]]]
# an invited agent's self-selection: True = bid, False = abstain
SelfSelectFn = Callable[[Invitation], Awaitable[bool]]
# embeds a batch of texts; returns one vector per text (None on failure)
EmbedderFn = Callable[[list[str]], Awaitable[list[list[float]] | None]]


def _row(mapping: Any) -> dict[str, Any]:
    return dict(mapping)


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


class AmendmentEngine:
    """All read/write operations for contract amendments on one DB connection."""

    def __init__(self, db: AsyncConnection) -> None:
        self._db = db

    # ── proposal (called from the request_expertise tool, mid-round) ──────────

    async def propose(
        self,
        *,
        run_id: str,
        proposing_agent_id: str,
        thread_id: str | None,
        domain: str,
        reason: str,
        current_round: int,
        max_amendments: int,
    ) -> dict[str, str]:
        """Record a pending amendment and post a SYSTEM entry to the Confirmed layer.

        Enforces the per-run ``max_amendments`` cap (counts *all* proposals, so an
        agent cannot game the run by re-requesting; see PRD OP-08). Returns
        ``{"amendment_id", "status"}`` where status is ``"pending"`` or
        ``"rejected_limit_reached"``.
        """
        existing = (
            await self._db.execute(
                text("SELECT COUNT(*) FROM amendments WHERE run_id = :run_id"),
                {"run_id": run_id},
            )
        ).scalar_one()
        if existing >= max_amendments:
            return {"amendment_id": "", "status": "rejected_limit_reached"}

        amendment_id = str(uuid.uuid4())
        await self._db.execute(
            text(
                """
                INSERT INTO amendments
                    (id, run_id, proposing_agent_id, thread_id,
                     requested_domain, reason, status)
                VALUES (:id, :run_id, :proposing_agent_id, :thread_id,
                        :domain, :reason, 'pending')
                """
            ),
            {
                "id": amendment_id,
                "run_id": run_id,
                "proposing_agent_id": proposing_agent_id,
                "thread_id": thread_id,
                "domain": domain,
                "reason": reason,
            },
        )

        proposer = await self._agent_name(proposing_agent_id)
        thread_label = await self._thread_title(thread_id) if thread_id else "the contract"
        await self._post_system_entry(
            run_id=run_id,
            thread_id=thread_id,
            content=(f"[{proposer}] requests '{domain}' expertise for {thread_label}: {reason}"),
            round_confirmed=current_round,
        )
        await self._db.commit()
        return {"amendment_id": amendment_id, "status": "pending"}

    # ── resolution (pure tally + side effects; no LLM) ────────────────────────

    async def resolve(
        self,
        *,
        run_id: str,
        amendment_id: str,
        approve_votes: int,
        total_voters: int,
        current_round: int,
        recruiter: RecruiterFn | None = None,
    ) -> dict[str, Any]:
        """Tally a collected vote and apply the outcome.

        ``approved = approve_votes > total_voters / 2`` (strict majority; ties and
        all-abstain fail). On approval a new thread is created with the requested
        domain as its ``required_expertise``, a SYSTEM entry is posted, the run's
        ``amendment_count`` is bumped, and the (optional) recruiter runs a
        mini-auction. Returns the resolution outcome.
        """
        amendment = await self.get(run_id, amendment_id)
        if amendment is None:
            raise ValueError(f"Amendment {amendment_id} not found in run {run_id}")

        approved = approve_votes > total_voters / 2
        status: Literal["approved", "rejected"] = "approved" if approved else "rejected"

        await self._db.execute(
            text(
                "UPDATE amendments SET status = :status, "
                "approve_votes = :approve, total_voters = :total WHERE id = :id"
            ),
            {
                "status": status,
                "approve": approve_votes,
                "total": total_voters,
                "id": amendment_id,
            },
        )

        if not approved:
            await self._post_system_entry(
                run_id=run_id,
                thread_id=amendment.thread_id,
                content=(
                    f"Amendment rejected by vote ({approve_votes}/{total_voters} approved). "
                    f"Requested expertise: '{amendment.requested_domain}'."
                ),
                round_confirmed=current_round,
            )
            await self._db.commit()
            return {
                "status": "rejected",
                "amendment_id": amendment_id,
                "thread_id": None,
                "new_takers": [],
            }

        new_thread = await self._create_thread(
            run_id=run_id,
            domain=amendment.requested_domain,
            reason=amendment.reason,
        )
        await self._post_system_entry(
            run_id=run_id,
            thread_id=new_thread.id,
            content=(
                f"Amendment approved ({approve_votes}/{total_voters}). "
                f"Thread '{new_thread.title}' created for '{amendment.requested_domain}'."
            ),
            round_confirmed=current_round,
        )
        await self._db.execute(
            text("UPDATE swarm_runs SET amendment_count = amendment_count + 1 WHERE id = :id"),
            {"id": run_id},
        )
        await self._db.commit()

        # Mini-auction recruitment for the new thread (see make_auction_recruiter).
        # Optional so resolve() can be unit-tested without driving an auction.
        new_takers: list[str] = []
        if recruiter is not None:
            new_takers = await recruiter(new_thread, run_id)

        return {
            "status": "approved",
            "amendment_id": amendment_id,
            "thread_id": new_thread.id,
            "new_takers": new_takers,
        }

    # ── orchestrator hook ─────────────────────────────────────────────────────

    async def process_pending(
        self,
        *,
        run_id: str,
        current_round: int,
        takers: list[str],
        vote_collector: VoteCollectorFn,
        mm_vote: MMVoteFn,
        recruiter: RecruiterFn | None = None,
    ) -> AsyncIterator[SimulationStep]:
        """Resolve every pending amendment for the round, yielding SSE steps.

        Called once at end-of-round by the orchestrator (PRD §11.2). For each
        pending amendment it collects one vote per taker plus the Market Maker's
        single equal vote, then applies :meth:`resolve`. ``vote_collector`` and
        ``mm_vote`` are injected so this method carries no LLM dependency itself.
        """
        for amendment in await self.list_pending(run_id):
            yield SimulationStep(
                type="amendment",
                msg=(
                    f"{await self._agent_name(amendment.proposing_agent_id)} requests "
                    f"'{amendment.requested_domain}' expertise — vote opening."
                ),
                node_id=amendment.proposing_agent_id,
                thread_id=amendment.thread_id,
                data={"amendment_id": amendment.id},
            )

            approve_votes = 0
            for taker_id in takers:
                if await vote_collector(taker_id, amendment) == "approve":
                    approve_votes += 1
            if await mm_vote(amendment) == "approve":
                approve_votes += 1
            total_voters = len(takers) + 1  # takers + Market Maker (equal vote)

            outcome = await self.resolve(
                run_id=run_id,
                amendment_id=amendment.id,
                approve_votes=approve_votes,
                total_voters=total_voters,
                current_round=current_round,
                recruiter=recruiter,
            )

            if outcome["status"] == "approved":
                yield SimulationStep(
                    type="amendment-approved",
                    msg=(
                        f"Amendment approved ({approve_votes}/{total_voters}). "
                        f"New thread created; recruited {len(outcome['new_takers'])} agent(s)."
                    ),
                    thread_id=outcome["thread_id"],
                    data=outcome,
                )
            else:
                yield SimulationStep(
                    type="amendment-rejected",
                    msg=f"Amendment rejected ({approve_votes}/{total_voters}).",
                    thread_id=amendment.thread_id,
                    data=outcome,
                )

    # ── reads ─────────────────────────────────────────────────────────────────

    async def list_pending(self, run_id: str) -> list[AmendmentSchema]:
        return await self._query_amendments(
            "WHERE run_id = :run_id AND status = 'pending'", {"run_id": run_id}
        )

    async def list_all(self, run_id: str) -> list[AmendmentSchema]:
        return await self._query_amendments("WHERE run_id = :run_id", {"run_id": run_id})

    async def get(self, run_id: str, amendment_id: str) -> AmendmentSchema | None:
        rows = await self._query_amendments(
            "WHERE run_id = :run_id AND id = :id",
            {"run_id": run_id, "id": amendment_id},
        )
        return rows[0] if rows else None

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _query_amendments(self, where: str, params: dict[str, Any]) -> list[AmendmentSchema]:
        result = await self._db.execute(
            text(
                f"""
                SELECT id, run_id, proposing_agent_id, thread_id, requested_domain,
                       reason, status, approve_votes, total_voters, created_at
                FROM amendments {where}
                ORDER BY created_at ASC
                """
            ),
            params,
        )
        return [AmendmentSchema(**_row(r)) for r in result.mappings().fetchall()]

    async def _create_thread(self, *, run_id: str, domain: str, reason: str) -> ThreadSchema:
        contract_id = (
            await self._db.execute(
                text("SELECT id FROM contracts WHERE run_id = :run_id"),
                {"run_id": run_id},
            )
        ).scalar_one()

        thread_id = str(uuid.uuid4())
        title = f"{domain} (amendment)"
        await self._db.execute(
            text(
                """
                INSERT INTO threads
                    (id, contract_id, run_id, title, description, required_expertise,
                     thread_embedding)
                VALUES (:id, :contract_id, :run_id, :title, :description,
                        :required_expertise, :embedding)
                """
            ),
            {
                "id": thread_id,
                "contract_id": contract_id,
                "run_id": run_id,
                "title": title,
                "description": reason,
                "required_expertise": f'["{domain}"]',
                # SEAM: thread_embedding stays NULL until embeddings.py (Phase 2).
                "embedding": None,
            },
        )
        row = (
            (
                await self._db.execute(
                    text(
                        "SELECT id, contract_id, run_id, title, description, "
                        "required_expertise, complexity, thread_embedding, created_at "
                        "FROM threads WHERE id = :id"
                    ),
                    {"id": thread_id},
                )
            )
            .mappings()
            .fetchone()
        )
        return ThreadSchema(**_row(row))

    async def _post_system_entry(
        self,
        *,
        run_id: str,
        thread_id: str | None,
        content: str,
        round_confirmed: int,
    ) -> str:
        """Insert a SYSTEM entry into the Confirmed layer (visible to all takers).

        A SYSTEM confirmed entry needs a thread_id (NOT NULL). Contract-level
        proposals fall back to the run's first thread.
        """
        if thread_id is None:
            thread_id = (
                await self._db.execute(
                    text(
                        "SELECT id FROM threads WHERE run_id = :run_id "
                        "ORDER BY created_at ASC LIMIT 1"
                    ),
                    {"run_id": run_id},
                )
            ).scalar_one()

        entry_id = str(uuid.uuid4())
        await self._db.execute(
            text(
                """
                INSERT INTO confirmed_entries
                    (id, run_id, thread_id, content, entry_type, round_confirmed)
                VALUES (:id, :run_id, :thread_id, :content, 'system', :round_confirmed)
                """
            ),
            {
                "id": entry_id,
                "run_id": run_id,
                "thread_id": thread_id,
                "content": content,
                "round_confirmed": round_confirmed,
            },
        )
        return entry_id

    async def _agent_name(self, agent_id: str) -> str:
        name = (
            await self._db.execute(text("SELECT name FROM agents WHERE id = :id"), {"id": agent_id})
        ).scalar_one_or_none()
        return name or agent_id

    async def _thread_title(self, thread_id: str) -> str:
        title = (
            await self._db.execute(
                text("SELECT title FROM threads WHERE id = :id"), {"id": thread_id}
            )
        ).scalar_one_or_none()
        return title or thread_id


# ── live vote collectors (LLM path; tests inject fakes instead) ───────────────
#
# These are the production defaults the orchestrator passes to ``process_pending``.
# The Market Maker's single equal vote is ``MarketMaker.cast_amendment_vote``
# (PRD §6.1), passed in as the ``mm_vote`` argument.

_TAKER_VOTE_SYSTEM_PROMPT = (
    "You are a taker in a multi-agent swarm. A co-worker proposes adding expertise "
    "the team may be missing, which would spawn a new thread and recruit more "
    "agents. Approve only if the gap is real and blocks good work; reject if the "
    "current team can handle it. Reply with a single word: APPROVE or REJECT."
)


class LiveAmendmentProcessor:
    """Production ``AmendmentProcessor`` for the orchestrator's end-of-round seam.

    Thin glue over :meth:`AmendmentEngine.process_pending`: each taker votes with
    its own LLM (:func:`make_llm_vote_collector`), the Market Maker casts its one
    equal vote via the injected ``mm_vote``, and approved threads recruit agents
    through the real mini-auction (:func:`make_auction_recruiter`, current takers
    excluded). Constructed once per run; the DB connection arrives per call, so
    the engine and collectors are built against the live connection each round.

    ``vote_collector`` is injectable for tests; ``None`` selects the LLM path.
    """

    def __init__(
        self,
        *,
        mm_vote: MMVoteFn,
        config: Any = None,
        vote_collector: VoteCollectorFn | None = None,
    ) -> None:
        self._mm_vote = mm_vote
        self._config = config
        self._vote_collector = vote_collector

    async def process(
        self, *, run_id: str, current_round: int, takers: list[str], db: AsyncConnection
    ) -> AsyncIterator[SimulationStep]:
        engine = AmendmentEngine(db)
        async for step in engine.process_pending(
            run_id=run_id,
            current_round=current_round,
            takers=takers,
            vote_collector=self._vote_collector or make_llm_vote_collector(db),
            mm_vote=self._mm_vote,
            recruiter=make_auction_recruiter(db, config=self._config, exclude_agent_ids=takers),
        ):
            yield step


# ── mini-auction recruiter (real AuctionEngine path) ─────────────────────────


def make_auction_recruiter(
    db: AsyncConnection,
    *,
    config: Any = None,
    exclude_agent_ids: Iterable[str] = (),
    self_select: SelfSelectFn | None = None,
    max_new_takers: int | None = None,
    embedder: EmbedderFn = embed_texts,
) -> RecruiterFn:
    """Build a ``RecruiterFn`` that runs a real mini-auction for an approved thread.

    Implements the PRD mini-auction (§6.5 step 3a) on top of :class:`AuctionEngine`:
    invite agents whose embedding matches the **new thread**, exclude the current
    takers, let each invited agent self-select (bid/abstain), then rank by
    ``bid_score`` and assign the thread's takers. ``select_takers`` writes
    ``is_taker``/``is_observer`` on the bid rows, so recruited agents persist exactly
    like any other taker.

    Thread-scoped matching: ``AuctionEngine.invite`` scores against the *contract*
    embedding, but §6.5 wants the *new thread*. So we take invite()'s candidate set
    (which also gives names, trust, and the inclusive fallback) and re-score each
    agent's ``capability_embedding`` against the new ``thread_embedding`` via
    ``cosine``, dropping anyone below ``invite_floor``. The thread embedding is
    computed (and persisted) on first use when absent. When an embedding is missing
    on either side, the inclusive invite() decision is kept — so this works before
    embeddings are populated and sharpens automatically once they are.

    Args:
        config: a ``SwarmRunConfig`` (or anything with the auction fields) to size
            ``invite_floor`` / ``max_takers`` etc. ``None`` uses engine defaults.
        exclude_agent_ids: current takers — already on the run, never re-recruited.
        self_select: an invited agent's decision (``True`` = bid). **SEAM:** the real
            choice is one LLM call per agent (``submit_bid``/``abstain``, §6.2), a
            loop the orchestrator owns and which does not exist yet. Until it does,
            the default auto-bids every invited agent; pass a real callback (or a
            test fake) to drive genuine self-selection.
        max_new_takers: cap on recruited takers; overrides the config's ``max_takers``.
        embedder: embeds the thread title+description when it has no stored embedding.
            Defaults to :func:`server.llm.embeddings.embed_texts` (returns ``None`` on
            failure → inclusive fallback). Tests inject a deterministic fake.
    """
    exclude = set(exclude_agent_ids)

    async def recruit(thread: ThreadSchema, run_id: str) -> list[str]:
        auction = AuctionEngine.from_config(db, config) if config is not None else AuctionEngine(db)
        if max_new_takers is not None:
            auction.max_takers = max_new_takers

        contract_id = (
            await db.execute(text("SELECT id FROM contracts WHERE run_id = :r"), {"r": run_id})
        ).scalar_one()

        invitations = await auction.invite(run_id=run_id, contract_id=contract_id)
        candidates = [inv for inv in invitations if inv.agent_id not in exclude]
        if not candidates:
            return []

        candidates = await _rescore_against_thread(
            db, thread, candidates, auction.invite_floor, embedder
        )

        bidders = 0
        for inv in candidates:
            wants_in = True if self_select is None else await self_select(inv)
            if wants_in:
                await auction.record_bid(
                    run_id=run_id,
                    agent_id=inv.agent_id,
                    contract_id=contract_id,
                    thread_id=thread.id,
                    justification="mini-auction (contract amendment)",
                    preliminary_score=inv.preliminary_score,
                )
                bidders += 1
            else:
                await auction.record_abstention(
                    run_id=run_id,
                    agent_id=inv.agent_id,
                    contract_id=contract_id,
                    thread_id=thread.id,
                    reason="mini-auction abstain",
                )

        if bidders == 0:
            return []  # no bidders → thread stays uncovered (caller may dissolve it)

        selection = await auction.select_takers(
            run_id=run_id, contract_id=contract_id, thread_id=thread.id
        )
        return [] if selection.aborted else selection.takers

    return recruit


async def _rescore_against_thread(
    db: AsyncConnection,
    thread: ThreadSchema,
    candidates: list[Invitation],
    invite_floor: float,
    embedder: EmbedderFn,
) -> list[Invitation]:
    """Re-score invited candidates against the new thread's embedding (PRD §6.5).

    Returns candidates whose ``capability_embedding`` matches the thread at or above
    ``invite_floor``, each with its ``preliminary_score`` replaced by the thread-
    scoped cosine. Candidates with a missing embedding (theirs or the thread's) keep
    the inclusive invite() decision unchanged.
    """
    thread_emb = thread.thread_embedding
    if thread_emb is None:
        vecs = await embedder([f"{thread.title}\n{thread.description}"])
        thread_emb = vecs[0] if vecs else None
        if thread_emb is not None:
            await db.execute(
                text("UPDATE threads SET thread_embedding = :e WHERE id = :id"),
                {"e": json.dumps(thread_emb), "id": thread.id},
            )
            await db.commit()

    if thread_emb is None:
        return candidates  # no thread embedding → cannot discriminate; keep all

    rows = (
        (await db.execute(text("SELECT id, capability_embedding FROM agents")))
        .mappings()
        .fetchall()
    )
    emb_by_agent = {r["id"]: _parse_embedding(r["capability_embedding"]) for r in rows}

    matched: list[Invitation] = []
    for inv in candidates:
        agent_emb = emb_by_agent.get(inv.agent_id)
        if agent_emb is not None and len(agent_emb) == len(thread_emb):
            score = cosine(agent_emb, thread_emb)
            if score < invite_floor:
                continue  # not a match for this thread
            matched.append(replace(inv, preliminary_score=score))
        else:
            matched.append(inv)  # missing agent embedding → keep inclusive
    return matched


def make_llm_vote_collector(db: AsyncConnection) -> VoteCollectorFn:
    """Build a ``VoteCollectorFn`` that asks each taker's own LLM to vote.

    Each taker votes with its configured provider/model/system prompt. This is the
    production path the orchestrator passes to :meth:`AmendmentEngine.process_pending`;
    unit tests bypass it with a deterministic fake.
    """

    async def collect(taker_id: str, amendment: AmendmentSchema) -> Literal["approve", "reject"]:
        row = (
            (
                await db.execute(
                    text("SELECT system_prompt, provider, model FROM agents WHERE id = :id"),
                    {"id": taker_id},
                )
            )
            .mappings()
            .fetchone()
        )
        if row is None:
            return "reject"
        user_prompt = (
            f"Proposed expertise: {amendment.requested_domain}\n"
            f"Reason given: {amendment.reason}\n\n"
            "Should a new thread be created for this expertise? Reply APPROVE or REJECT."
        )
        response, _ = await call_agent(
            prompt=user_prompt,
            provider=row["provider"],
            model=row["model"],
            system_prompt=f"{row['system_prompt']}\n\n{_TAKER_VOTE_SYSTEM_PROMPT}",
        )
        # Silence/abstention is not approval (PRD §6.5); default to reject.
        if "approve" in response.strip().lower():
            return "approve"
        return "reject"

    return collect
