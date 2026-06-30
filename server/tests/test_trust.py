"""Unit tests for the cross-run TrustRegistry (PRD §6.7)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import metadata
from server.market_hive.trust import (
    DEFAULT_DELTA_OBSERVER_LOSS,
    DEFAULT_DELTA_WINNER_GAIN,
    DEFAULT_TRUST,
    NoopTrustRegistry,
    TrustRegistry,
)


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
    await conn.commit()


async def _seed_contract(
    conn: AsyncConnection, *, run_id: str, task_type: str = "analysis"
) -> None:
    await conn.execute(
        text(
            "INSERT INTO contracts (id, run_id, original_prompt, task_type) "
            "VALUES (:id, :run_id, :p, :t)"
        ),
        {"id": str(uuid.uuid4()), "run_id": run_id, "p": "prompt", "t": task_type},
    )
    await conn.commit()


async def _seed_thread(conn: AsyncConnection, *, run_id: str, thread_id: str) -> None:
    cid = str(uuid.uuid4())
    await conn.execute(
        text(
            "INSERT INTO contracts (id, run_id, original_prompt, task_type) "
            "VALUES (:id, :run_id, 'p', 'analysis')"
        ),
        {"id": cid, "run_id": run_id},
    )
    await conn.execute(
        text(
            "INSERT INTO threads (id, contract_id, run_id, title, description) "
            "VALUES (:id, :cid, :run_id, 'T', 'd')"
        ),
        {"id": thread_id, "cid": cid, "run_id": run_id},
    )
    await conn.commit()


async def _seed_agent(conn: AsyncConnection, *, agent_id: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
            "VALUES (:id, :id, 'd', 's', 'openai', 'gpt-4o')"
        ),
        {"id": agent_id},
    )
    await conn.commit()


async def _seed_confirmed_finding(
    conn: AsyncConnection,
    *,
    run_id: str,
    thread_id: str,
    author_id: str,
    citation_count: int,
) -> None:
    """A confirmed finding traced to ``author_id`` via its source draft entry."""
    draft_id = str(uuid.uuid4())
    await conn.execute(
        text(
            "INSERT INTO draft_entries "
            "(id, run_id, thread_id, round, author_id, entry_type, content) "
            "VALUES (:id, :run_id, :tid, 1, :author, 'proposal', 'c')"
        ),
        {"id": draft_id, "run_id": run_id, "tid": thread_id, "author": author_id},
    )
    await conn.execute(
        text(
            "INSERT INTO confirmed_entries "
            "(id, run_id, thread_id, source_draft_id, content, entry_type, "
            " citation_count, round_confirmed) "
            "VALUES (:id, :run_id, :tid, :src, 'c', 'finding', :cites, 2)"
        ),
        {
            "id": str(uuid.uuid4()),
            "run_id": run_id,
            "tid": thread_id,
            "src": draft_id,
            "cites": citation_count,
        },
    )
    await conn.commit()


async def _trust_row(
    conn: AsyncConnection, *, agent_id: str, domain: str
) -> tuple[float, int] | None:
    row = (
        await conn.execute(
            text(
                "SELECT trust_score, runs_participated FROM agent_trust "
                "WHERE agent_id = :aid AND domain = :domain"
            ),
            {"aid": agent_id, "domain": domain},
        )
    ).fetchone()
    return (float(row[0]), int(row[1])) if row is not None else None


# ── winner gain ────────────────────────────────────────────────────────────────


async def test_winner_gain_proportional_to_citation_share(db: AsyncConnection) -> None:
    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_thread(db, run_id=run_id, thread_id=thread_id)
    for aid in ("alpha", "beta"):
        await _seed_agent(db, agent_id=aid)
    # Alpha holds 3 of 4 confirmed citations (75%), Beta 1 of 4 (25%).
    await _seed_confirmed_finding(
        db, run_id=run_id, thread_id=thread_id, author_id="alpha", citation_count=3
    )
    await _seed_confirmed_finding(
        db, run_id=run_id, thread_id=thread_id, author_id="beta", citation_count=1
    )

    await TrustRegistry().update(run_id=run_id, takers=["alpha", "beta"], observers=[], db=db)

    alpha = await _trust_row(db, agent_id="alpha", domain="analysis")
    beta = await _trust_row(db, agent_id="beta", domain="analysis")
    assert alpha == pytest.approx((DEFAULT_TRUST + DEFAULT_DELTA_WINNER_GAIN * 0.75, 1))
    assert beta == pytest.approx((DEFAULT_TRUST + DEFAULT_DELTA_WINNER_GAIN * 0.25, 1))


async def test_taker_without_confirmed_citations_gets_participation_only(
    db: AsyncConnection,
) -> None:
    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_thread(db, run_id=run_id, thread_id=thread_id)
    await _seed_agent(db, agent_id="alpha")
    await _seed_confirmed_finding(
        db, run_id=run_id, thread_id=thread_id, author_id="alpha", citation_count=5
    )
    await _seed_agent(db, agent_id="ghost")  # taker, but no confirmed findings

    await TrustRegistry().update(run_id=run_id, takers=["alpha", "ghost"], observers=[], db=db)

    # Score unchanged (delta 0) but a row exists and participation is recorded.
    assert await _trust_row(db, agent_id="ghost", domain="analysis") == (DEFAULT_TRUST, 1)


# ── observer loss ──────────────────────────────────────────────────────────────


async def test_observer_takes_flat_penalty_without_participation_tick(
    db: AsyncConnection,
) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_contract(db, run_id=run_id)
    await _seed_agent(db, agent_id="obs")

    await TrustRegistry().update(run_id=run_id, takers=[], observers=["obs"], db=db)

    score, runs = await _trust_row(db, agent_id="obs", domain="analysis")  # type: ignore[misc]
    assert score == pytest.approx(DEFAULT_TRUST - DEFAULT_DELTA_OBSERVER_LOSS)
    assert runs == 0  # observers did not participate


# ── clamping & read-modify-write ───────────────────────────────────────────────


async def test_observer_loss_clamps_at_zero(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_contract(db, run_id=run_id)
    await _seed_agent(db, agent_id="obs")
    await db.execute(
        text(
            "INSERT INTO agent_trust (agent_id, domain, trust_score) "
            "VALUES ('obs', 'analysis', 0.01)"
        )
    )
    await db.commit()

    await TrustRegistry().update(run_id=run_id, takers=[], observers=["obs"], db=db)

    score, _ = await _trust_row(db, agent_id="obs", domain="analysis")  # type: ignore[misc]
    assert score == pytest.approx(0.0)


async def test_existing_row_updated_in_place(db: AsyncConnection) -> None:
    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_thread(db, run_id=run_id, thread_id=thread_id)
    await _seed_agent(db, agent_id="alpha")
    await _seed_confirmed_finding(
        db, run_id=run_id, thread_id=thread_id, author_id="alpha", citation_count=4
    )
    await db.execute(
        text(
            "INSERT INTO agent_trust (agent_id, domain, trust_score, runs_participated) "
            "VALUES ('alpha', 'analysis', 0.6, 3)"
        )
    )
    await db.commit()

    await TrustRegistry().update(run_id=run_id, takers=["alpha"], observers=[], db=db)

    # One row only; score += full share gain; runs_participated incremented.
    n = (
        await db.execute(text("SELECT COUNT(*) FROM agent_trust WHERE agent_id = 'alpha'"))
    ).scalar_one()
    assert n == 1
    assert await _trust_row(db, agent_id="alpha", domain="analysis") == pytest.approx(
        (0.6 + DEFAULT_DELTA_WINNER_GAIN, 4)
    )


# ── degenerate runs ────────────────────────────────────────────────────────────


async def test_no_contract_is_noop(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)  # no contract → no domain
    await _seed_agent(db, agent_id="alpha")

    await TrustRegistry().update(run_id=run_id, takers=["alpha"], observers=[], db=db)

    rows = (await db.execute(text("SELECT COUNT(*) FROM agent_trust"))).scalar_one()
    assert rows == 0


async def test_noop_registry_records_nothing(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_contract(db, run_id=run_id)
    await _seed_agent(db, agent_id="alpha")

    await NoopTrustRegistry().update(run_id=run_id, takers=["alpha"], observers=["alpha"], db=db)

    rows = (await db.execute(text("SELECT COUNT(*) FROM agent_trust"))).scalar_one()
    assert rows == 0
