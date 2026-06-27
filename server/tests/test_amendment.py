"""Unit tests for the Contract Amendment engine (PRD §6.5).

Covers the pure DB operations (propose / cap / resolve / thread creation) and the
orchestrator hook (``process_pending``) with injected fakes for the LLM vote and
mini-auction recruitment seams.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Literal, NamedTuple

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import metadata
from server.market_hive.amendment import AmendmentEngine, make_auction_recruiter
from server.market_hive.auction import Invitation
from server.market_hive.schemas import AmendmentSchema, ThreadSchema
from server.market_hive.tools import RequestExpertiseInput, RequestExpertiseTool


class Seed(NamedTuple):
    run_id: str
    contract_id: str
    thread_id: str
    agent_ids: list[str]


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncGenerator[AsyncConnection, None]:
    async with engine.connect() as conn:
        yield conn


async def _seed(conn: AsyncConnection, *, n_agents: int = 2) -> Seed:
    """Seed a run with one contract, one thread, and N agents. Returns the IDs."""
    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())

    await conn.execute(text("INSERT INTO swarm_runs (id) VALUES (:id)"), {"id": run_id})
    await conn.execute(
        text(
            "INSERT INTO contracts (id, run_id, original_prompt, task_type) "
            "VALUES (:id, :run_id, :p, :t)"
        ),
        {"id": contract_id, "run_id": run_id, "p": "analyze this", "t": "analysis"},
    )
    await conn.execute(
        text(
            "INSERT INTO threads (id, contract_id, run_id, title, description) "
            "VALUES (:id, :cid, :run_id, :title, :desc)"
        ),
        {
            "id": thread_id,
            "cid": contract_id,
            "run_id": run_id,
            "title": "Original Thread",
            "desc": "the original scope",
        },
    )
    agent_ids: list[str] = []
    for i in range(n_agents):
        aid = str(uuid.uuid4())
        agent_ids.append(aid)
        await conn.execute(
            text(
                "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
                "VALUES (:id, :name, :desc, :sp, :prov, :model)"
            ),
            {
                "id": aid,
                "name": f"Agent{i}",
                "desc": "d",
                "sp": "s",
                "prov": "openai",
                "model": "gpt-4o",
            },
        )
    await conn.commit()
    return Seed(run_id=run_id, contract_id=contract_id, thread_id=thread_id, agent_ids=agent_ids)


async def _count(conn: AsyncConnection, sql: str, params: dict[str, object]) -> int:
    return int((await conn.execute(text(sql), params)).scalar_one())


# ── propose ──────────────────────────────────────────────────────────────────


async def test_propose_creates_pending_amendment_and_system_entry(db: AsyncConnection) -> None:
    s = await _seed(db)
    eng = AmendmentEngine(db)

    result = await eng.propose(
        run_id=s.run_id,
        proposing_agent_id=s.agent_ids[0],
        thread_id=s.thread_id,
        domain="financial_modeling",
        reason="DCF assumptions need a finance specialist",
        current_round=2,
        max_amendments=2,
    )

    assert result["status"] == "pending"
    assert result["amendment_id"]

    pending = await eng.list_pending(s.run_id)
    assert len(pending) == 1
    assert pending[0].requested_domain == "financial_modeling"
    assert pending[0].proposing_agent_id == s.agent_ids[0]

    # SYSTEM entry posted to the Confirmed layer, visible to all
    n_system = await _count(
        db,
        "SELECT COUNT(*) FROM confirmed_entries WHERE run_id = :r AND entry_type = 'system'",
        {"r": s.run_id},
    )
    assert n_system == 1


async def test_propose_enforces_max_amendments_cap(db: AsyncConnection) -> None:
    s = await _seed(db)
    eng = AmendmentEngine(db)

    first = await eng.propose(
        run_id=s.run_id,
        proposing_agent_id=s.agent_ids[0],
        thread_id=s.thread_id,
        domain="finance",
        reason="r1",
        current_round=2,
        max_amendments=1,
    )
    second = await eng.propose(
        run_id=s.run_id,
        proposing_agent_id=s.agent_ids[1],
        thread_id=s.thread_id,
        domain="law",
        reason="r2",
        current_round=2,
        max_amendments=1,
    )

    assert first["status"] == "pending"
    assert second["status"] == "rejected_limit_reached"
    assert second["amendment_id"] == ""
    assert (
        await _count(db, "SELECT COUNT(*) FROM amendments WHERE run_id = :r", {"r": s.run_id}) == 1
    )


# ── resolve ──────────────────────────────────────────────────────────────────


async def _make_pending(db: AsyncConnection, s: Seed) -> str:
    eng = AmendmentEngine(db)
    result = await eng.propose(
        run_id=s.run_id,
        proposing_agent_id=s.agent_ids[0],
        thread_id=s.thread_id,
        domain="finance",
        reason="needs a finance specialist",
        current_round=2,
        max_amendments=2,
    )
    # AmendmentEngine resolves to Any under the repo's `cd server && mypy .` setup
    # (absolute `server.market_hive.*` imports are unfollowable), so coerce to str.
    return str(result["amendment_id"])


async def test_resolve_approved_creates_thread_and_bumps_count(db: AsyncConnection) -> None:
    s = await _seed(db)
    amendment_id = await _make_pending(db, s)
    eng = AmendmentEngine(db)

    threads_before = await _count(
        db, "SELECT COUNT(*) FROM threads WHERE run_id = :r", {"r": s.run_id}
    )

    outcome = await eng.resolve(
        run_id=s.run_id,
        amendment_id=amendment_id,
        approve_votes=3,
        total_voters=4,
        current_round=2,
    )

    assert outcome["status"] == "approved"
    assert outcome["thread_id"]

    threads_after = await _count(
        db, "SELECT COUNT(*) FROM threads WHERE run_id = :r", {"r": s.run_id}
    )
    assert threads_after == threads_before + 1

    new_thread = (
        (
            await db.execute(
                text("SELECT title, required_expertise FROM threads WHERE id = :id"),
                {"id": outcome["thread_id"]},
            )
        )
        .mappings()
        .fetchone()
    )
    assert new_thread is not None
    assert "finance" in new_thread["required_expertise"]

    amendment = await eng.get(s.run_id, amendment_id)
    assert amendment is not None and amendment.status == "approved"

    count = await _count(
        db, "SELECT amendment_count FROM swarm_runs WHERE id = :r", {"r": s.run_id}
    )
    assert count == 1


async def test_resolve_rejected_creates_no_thread(db: AsyncConnection) -> None:
    s = await _seed(db)
    amendment_id = await _make_pending(db, s)
    eng = AmendmentEngine(db)

    threads_before = await _count(
        db, "SELECT COUNT(*) FROM threads WHERE run_id = :r", {"r": s.run_id}
    )

    outcome = await eng.resolve(
        run_id=s.run_id,
        amendment_id=amendment_id,
        approve_votes=1,
        total_voters=4,
        current_round=2,
    )

    assert outcome["status"] == "rejected"
    assert outcome["thread_id"] is None
    threads_after = await _count(
        db, "SELECT COUNT(*) FROM threads WHERE run_id = :r", {"r": s.run_id}
    )
    assert threads_after == threads_before

    amendment = await eng.get(s.run_id, amendment_id)
    assert amendment is not None and amendment.status == "rejected"


async def test_resolve_tie_fails_strict_majority(db: AsyncConnection) -> None:
    s = await _seed(db)
    amendment_id = await _make_pending(db, s)
    eng = AmendmentEngine(db)

    # 2 of 4 is not a strict majority -> rejected
    outcome = await eng.resolve(
        run_id=s.run_id,
        amendment_id=amendment_id,
        approve_votes=2,
        total_voters=4,
        current_round=2,
    )
    assert outcome["status"] == "rejected"


async def test_resolve_runs_recruiter_on_approval(db: AsyncConnection) -> None:
    s = await _seed(db)
    amendment_id = await _make_pending(db, s)
    eng = AmendmentEngine(db)

    seen: dict[str, str] = {}

    async def fake_recruiter(thread: ThreadSchema, run_id: str) -> list[str]:
        seen["thread_title"] = thread.title
        seen["run_id"] = run_id
        return ["recruit-1", "recruit-2"]

    outcome = await eng.resolve(
        run_id=s.run_id,
        amendment_id=amendment_id,
        approve_votes=3,
        total_voters=4,
        current_round=2,
        recruiter=fake_recruiter,
    )

    assert outcome["new_takers"] == ["recruit-1", "recruit-2"]
    assert seen["run_id"] == s.run_id
    assert "finance" in seen["thread_title"]


# ── process_pending (orchestrator hook) ──────────────────────────────────────


async def test_process_pending_approves_with_majority(db: AsyncConnection) -> None:
    s = await _seed(db, n_agents=3)
    await _make_pending(db, s)
    eng = AmendmentEngine(db)

    async def approve_all(taker_id: str, amendment: AmendmentSchema) -> Literal["approve"]:
        return "approve"

    async def mm_approve(amendment: AmendmentSchema) -> Literal["approve"]:
        return "approve"

    steps = [
        step
        async for step in eng.process_pending(
            run_id=s.run_id,
            current_round=2,
            takers=s.agent_ids,
            vote_collector=approve_all,
            mm_vote=mm_approve,
        )
    ]

    types = [step.type for step in steps]
    assert "amendment" in types
    assert "amendment-approved" in types

    pending = await eng.list_pending(s.run_id)
    assert pending == []  # resolved, no longer pending


async def test_process_pending_rejects_when_only_mm_approves(db: AsyncConnection) -> None:
    s = await _seed(db, n_agents=3)
    await _make_pending(db, s)
    eng = AmendmentEngine(db)

    async def reject_all(taker_id: str, amendment: AmendmentSchema) -> Literal["reject"]:
        return "reject"

    async def mm_approve(amendment: AmendmentSchema) -> Literal["approve"]:
        return "approve"

    steps = [
        step
        async for step in eng.process_pending(
            run_id=s.run_id,
            current_round=2,
            takers=s.agent_ids,  # 3 takers + MM = 4 voters; only MM approves -> 1/4
            vote_collector=reject_all,
            mm_vote=mm_approve,
        )
    ]

    types = [step.type for step in steps]
    assert "amendment-rejected" in types
    assert "amendment-approved" not in types


# ── request_expertise tool ───────────────────────────────────────────────────


async def test_request_expertise_tool_creates_amendment(db: AsyncConnection) -> None:
    s = await _seed(db)
    tool = RequestExpertiseTool()

    out = await tool.execute(
        RequestExpertiseInput(
            domain="regulatory_compliance",
            reason="contract touches GDPR",
            thread_id=s.thread_id,
        ),
        context={
            "db": db,
            "run_id": s.run_id,
            "agent_id": s.agent_ids[0],
            "round": 3,
            "max_amendments": 2,
        },
    )

    assert '"status": "pending"' in out
    eng = AmendmentEngine(db)
    pending = await eng.list_pending(s.run_id)
    assert len(pending) == 1
    assert isinstance(pending[0], AmendmentSchema)
    assert pending[0].requested_domain == "regulatory_compliance"


async def test_request_expertise_tool_respects_cap(db: AsyncConnection) -> None:
    s = await _seed(db)
    tool = RequestExpertiseTool()
    ctx: dict[str, object] = {
        "db": db,
        "run_id": s.run_id,
        "agent_id": s.agent_ids[0],
        "round": 3,
        "max_amendments": 0,
    }

    out = await tool.execute(
        RequestExpertiseInput(domain="x", reason="y", thread_id=s.thread_id),
        context=ctx,
    )
    assert '"status": "rejected_limit_reached"' in out


# ── mini-auction recruiter (real AuctionEngine) ──────────────────────────────


async def _no_embed(texts: list[str]) -> list[list[float]] | None:
    """Embedder fake that yields no vector → recruiter keeps the inclusive path."""
    return None


async def _set_capability_embedding(db: AsyncConnection, agent_id: str, vec: list[float]) -> None:
    await db.execute(
        text("UPDATE agents SET capability_embedding = :e WHERE id = :id"),
        {"e": json.dumps(vec), "id": agent_id},
    )
    await db.commit()


async def test_auction_recruiter_assigns_non_taker_agents(db: AsyncConnection) -> None:
    # 4 agents total: first 2 are current takers, last 2 are idle non-takers.
    # No embeddings → invite() and the re-score both fall back to inclusive, so all
    # idle agents are invited, auto-bid, and selected.
    s = await _seed(db, n_agents=4)
    takers = s.agent_ids[:2]
    idle = s.agent_ids[2:]

    amendment_id = await _make_pending(db, s)
    eng = AmendmentEngine(db)
    recruiter = make_auction_recruiter(db, exclude_agent_ids=takers, embedder=_no_embed)

    outcome = await eng.resolve(
        run_id=s.run_id,
        amendment_id=amendment_id,
        approve_votes=3,
        total_voters=4,
        current_round=2,
        recruiter=recruiter,
    )

    # Only the idle (non-taker) agents are recruited onto the new thread.
    assert set(outcome["new_takers"]) == set(idle)

    # select_takers persists them as takers on the new thread.
    bid_takers = (
        await db.execute(
            text("SELECT agent_id FROM bids WHERE thread_id = :t AND is_taker = true"),
            {"t": outcome["thread_id"]},
        )
    ).fetchall()
    assert {r[0] for r in bid_takers} == set(idle)


async def test_auction_recruiter_respects_max_new_takers(db: AsyncConnection) -> None:
    s = await _seed(db, n_agents=5)
    amendment_id = await _make_pending(db, s)
    eng = AmendmentEngine(db)
    # No exclusions, cap at 2 — invite all 5, but select only the top 2.
    recruiter = make_auction_recruiter(db, max_new_takers=2, embedder=_no_embed)

    outcome = await eng.resolve(
        run_id=s.run_id,
        amendment_id=amendment_id,
        approve_votes=3,
        total_voters=4,
        current_round=2,
        recruiter=recruiter,
    )

    assert len(outcome["new_takers"]) == 2


async def test_auction_recruiter_honours_self_select_abstention(db: AsyncConnection) -> None:
    # 3 idle non-takers; one of them abstains via the self_select seam.
    s = await _seed(db, n_agents=4)
    takers = s.agent_ids[:1]
    idle = s.agent_ids[1:]
    abstainer = idle[0]

    amendment_id = await _make_pending(db, s)
    eng = AmendmentEngine(db)

    async def self_select(inv: Invitation) -> bool:
        return bool(inv.agent_id != abstainer)

    recruiter = make_auction_recruiter(
        db, exclude_agent_ids=takers, self_select=self_select, embedder=_no_embed
    )

    outcome = await eng.resolve(
        run_id=s.run_id,
        amendment_id=amendment_id,
        approve_votes=3,
        total_voters=4,
        current_round=2,
        recruiter=recruiter,
    )

    # The abstainer bids nothing, so it is never selected; the others are.
    assert abstainer not in outcome["new_takers"]
    assert set(outcome["new_takers"]) == set(idle) - {abstainer}


async def test_auction_recruiter_scores_against_thread_embedding(db: AsyncConnection) -> None:
    # 1 taker (excluded) + 2 idle non-takers with embeddings: one aligned with the
    # new thread's vector, one orthogonal. Only the aligned agent should be recruited.
    s = await _seed(db, n_agents=3)
    taker = s.agent_ids[0]
    aligned = s.agent_ids[1]
    orthogonal = s.agent_ids[2]
    await _set_capability_embedding(db, aligned, [1.0, 0.0, 0.0])
    await _set_capability_embedding(db, orthogonal, [0.0, 1.0, 0.0])

    amendment_id = await _make_pending(db, s)
    eng = AmendmentEngine(db)

    async def thread_embedder(texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]  # thread vector aligns with `aligned`

    recruiter = make_auction_recruiter(db, exclude_agent_ids=[taker], embedder=thread_embedder)

    outcome = await eng.resolve(
        run_id=s.run_id,
        amendment_id=amendment_id,
        approve_votes=3,
        total_voters=4,
        current_round=2,
        recruiter=recruiter,
    )

    # cosine(aligned, thread)=1.0 ≥ floor; cosine(orthogonal, thread)=0.0 < floor.
    assert outcome["new_takers"] == [aligned]

    # The computed thread embedding is persisted back onto the new thread.
    stored = (
        await db.execute(
            text("SELECT thread_embedding FROM threads WHERE id = :id"),
            {"id": outcome["thread_id"]},
        )
    ).scalar_one()
    assert stored is not None
