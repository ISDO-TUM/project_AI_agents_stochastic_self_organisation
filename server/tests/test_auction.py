"""Unit tests for the AuctionEngine (PRD §6.2)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import metadata
from server.market_hive.auction import AuctionEngine


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


# ── seeding helpers ────────────────────────────────────────────────────────────


async def _seed_run(conn: AsyncConnection, run_id: str) -> None:
    await conn.execute(text("INSERT INTO swarm_runs (id) VALUES (:id)"), {"id": run_id})


async def _seed_contract(
    conn: AsyncConnection,
    *,
    run_id: str,
    contract_id: str,
    task_type: str = "analysis",
    confidence: float = 0.8,
    embedding: list[float] | None = None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO contracts "
            "(id, run_id, original_prompt, task_type, confidence, contract_embedding) "
            "VALUES (:id, :run_id, :p, :t, :c, :emb)"
        ),
        {
            "id": contract_id,
            "run_id": run_id,
            "p": "test prompt",
            "t": task_type,
            "c": confidence,
            "emb": json.dumps(embedding) if embedding is not None else None,
        },
    )
    await conn.commit()


async def _seed_thread(
    conn: AsyncConnection, *, run_id: str, contract_id: str, thread_id: str, title: str = "T"
) -> None:
    await conn.execute(
        text(
            "INSERT INTO threads (id, contract_id, run_id, title, description) "
            "VALUES (:id, :cid, :run_id, :title, :desc)"
        ),
        {"id": thread_id, "cid": contract_id, "run_id": run_id, "title": title, "desc": "d"},
    )
    await conn.commit()


async def _seed_agent(
    conn: AsyncConnection,
    *,
    agent_id: str,
    name: str = "Agent",
    embedding: list[float] | None = None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO agents "
            "(id, name, description, system_prompt, provider, model, capability_embedding) "
            "VALUES (:id, :name, :desc, :sp, :prov, :model, :emb)"
        ),
        {
            "id": agent_id,
            "name": name,
            "desc": "d",
            "sp": "s",
            "prov": "openai",
            "model": "gpt-4o",
            "emb": json.dumps(embedding) if embedding is not None else None,
        },
    )
    await conn.commit()


async def _seed_trust(
    conn: AsyncConnection,
    *,
    agent_id: str,
    domain: str,
    score: float,
    domain_embedding: list[float] | None = None,
) -> None:
    """Seed one ledger event landing at exactly ``score`` under score_events'
    shrinkage formula: solving ``(K_PRIOR*0.5 + w*1.0) / (K_PRIOR + w) = score``
    for weight (K_PRIOR=4.0, outcome=1.0) gives ``w = 4*(score - 0.5) / (1 - score)``."""
    weight = 4.0 * (score - 0.5) / (1 - score)
    await conn.execute(
        text(
            "INSERT INTO trust_events "
            "(id, run_id, agent_id, kind, outcome, weight, domain_label, domain_embedding) "
            "VALUES (:id, NULL, :aid, 'finding_confirmed', 1.0, :weight, :domain, :emb)"
        ),
        {
            "id": str(uuid.uuid4()),
            "aid": agent_id,
            "weight": weight,
            "domain": domain,
            "emb": json.dumps(domain_embedding) if domain_embedding is not None else None,
        },
    )
    await conn.commit()


# ── scoring ──────────────────────────────────────────────────────────────────


def test_compute_bid_score_uses_weights(db: AsyncConnection) -> None:
    eng = AuctionEngine(db, alpha=0.5, beta=0.4, gamma=0.1)
    # 0.5*1.0 + 0.4*0.5 + 0.1*0.8 = 0.5 + 0.2 + 0.08 = 0.78
    score = eng.compute_bid_score(preliminary_score=1.0, trust_score=0.5, mm_confidence=0.8)
    assert score == pytest.approx(0.78)


# ── Phase 1: invitation ────────────────────────────────────────────────────────


async def test_invite_filters_by_floor(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    # Contract embedding points along axis 0.
    await _seed_contract(db, run_id=run_id, contract_id=contract_id, embedding=[1.0, 0.0])

    aligned = str(uuid.uuid4())
    orthogonal = str(uuid.uuid4())
    await _seed_agent(db, agent_id=aligned, name="Aligned", embedding=[1.0, 0.0])
    await _seed_agent(db, agent_id=orthogonal, name="Orthogonal", embedding=[0.0, 1.0])

    eng = AuctionEngine(db, invite_floor=0.3)
    invited = await eng.invite(run_id=run_id, contract_id=contract_id)

    ids = {i.agent_id for i in invited}
    assert aligned in ids  # cosine 1.0 >= 0.3
    assert orthogonal not in ids  # cosine 0.0 < 0.3


async def test_invite_falls_back_to_all_when_floor_excludes_everyone(
    db: AsyncConnection,
) -> None:
    """The cosine floor must never abort a runnable swarm.

    When no agent clears the floor (e.g. a short contract prompt scores low
    against every role description), every agent is invited instead — with real
    cosine scores preserved — so LLM self-selection decides participation.
    """
    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_contract(db, run_id=run_id, contract_id=contract_id, embedding=[1.0, 0.0])

    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    # Both agents score well below the floor (cosine ~0.1 and 0.0).
    await _seed_agent(db, agent_id=a, name="A", embedding=[0.1, 1.0])
    await _seed_agent(db, agent_id=b, name="B", embedding=[0.0, 1.0])

    eng = AuctionEngine(db, invite_floor=0.9)
    invited = await eng.invite(run_id=run_id, contract_id=contract_id)

    assert {i.agent_id for i in invited} == {a, b}
    # Real cosine scores are preserved for downstream ranking, not zeroed out.
    by_id = {i.agent_id: i.preliminary_score for i in invited}
    assert by_id[a] > by_id[b]


async def test_invite_includes_trust_score(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_contract(
        db, run_id=run_id, contract_id=contract_id, task_type="law", embedding=[1.0, 0.0]
    )
    agent_id = str(uuid.uuid4())
    await _seed_agent(db, agent_id=agent_id, embedding=[1.0, 0.0])
    await _seed_trust(db, agent_id=agent_id, domain="law", score=0.9)

    eng = AuctionEngine(db)
    invited = await eng.invite(run_id=run_id, contract_id=contract_id)

    assert len(invited) == 1
    assert invited[0].trust_score == pytest.approx(0.9)
    assert invited[0].preliminary_score == pytest.approx(1.0)


async def test_invite_is_inclusive_without_contract_embedding(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_contract(db, run_id=run_id, contract_id=contract_id, embedding=None)
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_agent(db, agent_id=a, embedding=[1.0, 0.0])
    await _seed_agent(db, agent_id=b, embedding=None)

    eng = AuctionEngine(db)
    invited = await eng.invite(run_id=run_id, contract_id=contract_id)

    assert {i.agent_id for i in invited} == {a, b}


# ── Phase 2: thread_id resolution (defense-in-depth against FK-violating LLM output) ──


async def test_resolve_thread_id_passes_through_valid_id(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_contract(db, run_id=run_id, contract_id=contract_id)
    await _seed_thread(db, run_id=run_id, contract_id=contract_id, thread_id=thread_id)

    eng = AuctionEngine(db)
    resolved = await eng.resolve_thread_id(contract_id=contract_id, thread_id=thread_id)

    assert resolved == thread_id


async def test_resolve_thread_id_degrades_hallucinated_id_to_none(db: AsyncConnection) -> None:
    """An LLM that echoes a thread's title (or invents an id) instead of copying
    the real id must not FK-violate the bids insert — it degrades to a
    contract-level bid instead of crashing the turn."""
    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_contract(db, run_id=run_id, contract_id=contract_id)
    await _seed_thread(
        db,
        run_id=run_id,
        contract_id=contract_id,
        thread_id=str(uuid.uuid4()),
        title="Legal and Contractual Risk Analysis",
    )

    eng = AuctionEngine(db)
    resolved = await eng.resolve_thread_id(
        contract_id=contract_id, thread_id="Legal and Contractual Risk Analysis"
    )

    assert resolved is None


async def test_resolve_thread_id_passes_through_none(db: AsyncConnection) -> None:
    eng = AuctionEngine(db)
    assert await eng.resolve_thread_id(contract_id=str(uuid.uuid4()), thread_id=None) is None


# ── Phase 3: taker selection ────────────────────────────────────────────────────


async def test_select_takers_caps_at_max_by_bid_score(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_contract(db, run_id=run_id, contract_id=contract_id, confidence=0.5)

    # Three bidders with descending preliminary scores; max_takers=2.
    high, mid, low = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    for aid in (high, mid, low):
        await _seed_agent(db, agent_id=aid)

    eng = AuctionEngine(db, min_takers=1, max_takers=2)
    await eng.record_bid(
        run_id=run_id, agent_id=high, contract_id=contract_id, preliminary_score=0.9
    )
    await eng.record_bid(
        run_id=run_id, agent_id=mid, contract_id=contract_id, preliminary_score=0.6
    )
    await eng.record_bid(
        run_id=run_id, agent_id=low, contract_id=contract_id, preliminary_score=0.1
    )

    result = await eng.select_takers(run_id=run_id, contract_id=contract_id)

    assert not result.aborted
    assert set(result.takers) == {high, mid}
    assert result.observers == [low]


async def test_select_takers_aborts_with_no_bidders(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_contract(db, run_id=run_id, contract_id=contract_id)

    eng = AuctionEngine(db)
    result = await eng.select_takers(run_id=run_id, contract_id=contract_id)

    assert result.aborted is True
    assert result.takers == []


async def test_abstainers_are_not_observers(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_contract(db, run_id=run_id, contract_id=contract_id)
    bidder, abstainer = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_agent(db, agent_id=bidder)
    await _seed_agent(db, agent_id=abstainer)

    eng = AuctionEngine(db, max_takers=5)
    await eng.record_bid(
        run_id=run_id, agent_id=bidder, contract_id=contract_id, preliminary_score=0.5
    )
    await eng.record_abstention(
        run_id=run_id, agent_id=abstainer, contract_id=contract_id, reason="not my domain"
    )

    result = await eng.select_takers(run_id=run_id, contract_id=contract_id)

    assert result.takers == [bidder]
    assert abstainer not in result.observers
    assert await eng.get_observers(run_id=run_id) == []


async def test_get_takers_and_observers(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_contract(db, run_id=run_id, contract_id=contract_id)
    winner, loser = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_agent(db, agent_id=winner)
    await _seed_agent(db, agent_id=loser)

    eng = AuctionEngine(db, max_takers=1)
    await eng.record_bid(
        run_id=run_id, agent_id=winner, contract_id=contract_id, preliminary_score=0.9
    )
    await eng.record_bid(
        run_id=run_id, agent_id=loser, contract_id=contract_id, preliminary_score=0.2
    )
    await eng.select_takers(run_id=run_id, contract_id=contract_id)

    assert await eng.get_takers(run_id=run_id) == [winner]
    assert await eng.get_observers(run_id=run_id) == [loser]


# ── Phase 4: thread coverage (multi-step) ────────────────────────────────────────


async def test_uncovered_threads_detects_unbid_thread(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    thread_a, thread_b = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_contract(db, run_id=run_id, contract_id=contract_id)
    await _seed_thread(db, run_id=run_id, contract_id=contract_id, thread_id=thread_a, title="A")
    await _seed_thread(db, run_id=run_id, contract_id=contract_id, thread_id=thread_b, title="B")
    agent_id = str(uuid.uuid4())
    await _seed_agent(db, agent_id=agent_id)

    eng = AuctionEngine(db, min_takers=1, max_takers=5)
    # Agent bids only on thread A.
    await eng.record_bid(
        run_id=run_id,
        agent_id=agent_id,
        contract_id=contract_id,
        thread_id=thread_a,
        preliminary_score=0.8,
    )
    await eng.select_takers(run_id=run_id, contract_id=contract_id, thread_id=thread_a)

    uncovered = await eng.uncovered_threads(run_id=run_id, contract_id=contract_id)

    assert uncovered == [thread_b]
