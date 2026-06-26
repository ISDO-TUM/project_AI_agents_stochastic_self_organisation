"""Unit tests for the ConvergenceEngine (PRD §6.4)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import metadata
from server.market_hive.blackboard import Blackboard
from server.market_hive.convergence import ConvergenceEngine


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


async def _seed(conn: AsyncConnection, run_id: str, thread_id: str, *agent_ids: str) -> None:
    contract_id = str(uuid.uuid4())
    await conn.execute(text("INSERT INTO swarm_runs (id) VALUES (:id)"), {"id": run_id})
    await conn.execute(
        text(
            "INSERT INTO contracts (id, run_id, original_prompt, task_type) "
            "VALUES (:id, :run_id, :p, :t)"
        ),
        {"id": contract_id, "run_id": run_id, "p": "p", "t": "analysis"},
    )
    await conn.execute(
        text(
            "INSERT INTO threads (id, contract_id, run_id, title, description) "
            "VALUES (:id, :cid, :run_id, :title, :desc)"
        ),
        {"id": thread_id, "cid": contract_id, "run_id": run_id, "title": "T", "desc": "d"},
    )
    for i, aid in enumerate(agent_ids):
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


# ── conceding temperature (pure maths) ─────────────────────────────────────────


def test_temperature_floor_rises_with_round(db: AsyncConnection) -> None:
    eng = ConvergenceEngine(db, t_initial=0.0, delta_t=0.1)
    assert eng.temperature_floor(1) == pytest.approx(0.0)
    assert eng.temperature_floor(3) == pytest.approx(0.2)


def test_conceding_temperature_uses_floor_when_confident(db: AsyncConnection) -> None:
    eng = ConvergenceEngine(db, t_initial=0.0, delta_t=0.1)
    # High confidence → 1 - 0.9 = 0.1; floor at round 5 = 0.4 → floor wins.
    assert eng.conceding_temperature(confidence=0.9, round=5) == pytest.approx(0.4)
    # Low confidence → 1 - 0.1 = 0.9 dominates the floor.
    assert eng.conceding_temperature(confidence=0.1, round=2) == pytest.approx(0.9)


def test_conceding_temperature_clamped_to_t_max(db: AsyncConnection) -> None:
    eng = ConvergenceEngine(db, t_initial=0.0, delta_t=0.5, t_max=1.0)
    # Floor at round 5 = 2.0, clamped to 1.0.
    assert eng.conceding_temperature(confidence=1.0, round=5) == pytest.approx(1.0)


def test_temperature_instruction_bands(db: AsyncConnection) -> None:
    eng = ConvergenceEngine(db)
    assert "Defend your analysis firmly" in eng.temperature_instruction(0.1)
    assert "Acknowledge valid points" in eng.temperature_instruction(0.3)
    assert "Actively seek common ground" in eng.temperature_instruction(0.6)
    assert "Prioritize consensus" in eng.temperature_instruction(0.9)
    assert "Prioritize consensus" in eng.temperature_instruction(1.0)


# ── cold-start confidence ───────────────────────────────────────────────────────


async def test_cold_start_confidence_from_votes(db: AsyncConnection) -> None:
    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    a, b, c = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await _seed(db, run_id, thread_id, a, b, c)

    bb = Blackboard(db)
    post_a = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=a, content="A", entry_type="proposal", round=1
    )
    await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=b, content="B", entry_type="proposal", round=1
    )
    await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=c, content="C", entry_type="proposal", round=1
    )
    # Both B and C vote for A's proposal. N_participants = 3 → denom = 2.
    await bb.vote(run_id=run_id, voter_id=b, entry_id=post_a, thread_id=thread_id)
    await bb.vote(run_id=run_id, voter_id=c, entry_id=post_a, thread_id=thread_id)

    eng = ConvergenceEngine(db)
    conf = await eng.compute_cold_start_confidence(run_id=run_id, thread_id=thread_id)

    assert conf[a] == pytest.approx(1.0)  # 2 / 2
    assert conf[b] == pytest.approx(0.0)
    assert conf[c] == pytest.approx(0.0)


# ── per-round confidence ─────────────────────────────────────────────────────────


async def test_confidence_from_citation_share(db: AsyncConnection) -> None:
    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    a, b, c = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await _seed(db, run_id, thread_id, a, b, c)

    bb = Blackboard(db)
    post_a = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=a, content="A", entry_type="proposal", round=1
    )
    post_b = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=b, content="B", entry_type="proposal", round=1
    )
    # C participates (posts) but earns no citations.
    await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=c, content="C", entry_type="proposal", round=1
    )
    # Round 2: B and C cite A; A cites B. Total = 3 → A=2/3, B=1/3, C=0.
    await bb.cite(run_id=run_id, citing_agent_id=b, entry_ids=[post_a], round=2)
    await bb.cite(run_id=run_id, citing_agent_id=c, entry_ids=[post_a], round=2)
    await bb.cite(run_id=run_id, citing_agent_id=a, entry_ids=[post_b], round=2)

    eng = ConvergenceEngine(db)
    conf = await eng.compute_confidence(run_id=run_id, thread_id=thread_id, round=2)

    assert conf[a] == pytest.approx(2 / 3)
    assert conf[b] == pytest.approx(1 / 3)
    assert conf[c] == pytest.approx(0.0)


async def test_confidence_zero_when_no_citations(db: AsyncConnection) -> None:
    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed(db, run_id, thread_id, a, b)

    bb = Blackboard(db)
    await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=a, content="A", entry_type="proposal", round=1
    )
    eng = ConvergenceEngine(db)
    conf = await eng.compute_confidence(run_id=run_id, thread_id=thread_id, round=2)

    assert conf[a] == pytest.approx(0.0)


# ── reputation ───────────────────────────────────────────────────────────────────


async def test_update_reputation_rewards_promotion(db: AsyncConnection) -> None:
    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed(db, run_id, thread_id, a, b)

    bb = Blackboard(db)
    entry = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=a, content="A", entry_type="proposal", round=1
    )
    await bb.cite(run_id=run_id, citing_agent_id=b, entry_ids=[entry], round=2)
    await bb.check_promotions(run_id=run_id, current_round=2)

    eng = ConvergenceEngine(db, delta_confirm=0.05)
    updated = await eng.update_reputation(run_id=run_id, current_round=2, domain="analysis")

    # Author A starts at default 0.5, +0.05 for the promotion.
    assert updated[a] == pytest.approx(0.55)


async def test_update_reputation_penalises_deletion(db: AsyncConnection) -> None:
    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed(db, run_id, thread_id, a, b)

    bb = Blackboard(db)
    entry = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=a, content="A", entry_type="reply", round=2
    )

    eng = ConvergenceEngine(db, delta_reject=0.03)
    updated = await eng.update_reputation(
        run_id=run_id,
        current_round=5,
        domain="analysis",
        promoted_draft_ids=set(),
        deleted_draft_ids={entry},
    )

    assert updated[a] == pytest.approx(0.47)  # 0.5 - 0.03


async def test_update_reputation_clamps_to_unit_interval(db: AsyncConnection) -> None:
    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed(db, run_id, thread_id, a, b)

    bb = Blackboard(db)
    entry = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=a, content="A", entry_type="reply", round=2
    )
    # Seed A's reputation near the ceiling.
    await db.execute(
        text("INSERT INTO reputation (run_id, agent_id, domain, score) VALUES (:r, :a, :d, :s)"),
        {"r": run_id, "a": a, "d": "analysis", "s": 0.98},
    )
    await db.commit()

    eng = ConvergenceEngine(db, delta_confirm=0.05)
    updated = await eng.update_reputation(
        run_id=run_id, current_round=2, domain="analysis", promoted_draft_ids={entry}
    )

    assert updated[a] == pytest.approx(1.0)  # 0.98 + 0.05 clamped to 1.0
