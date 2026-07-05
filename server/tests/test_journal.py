"""Unit tests for RunJournal (resilient runs: phase/heartbeat/turn bookkeeping)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import metadata
from server.market_hive.journal import RunJournal


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


async def _seed_run(conn: AsyncConnection, run_id: str) -> None:
    await conn.execute(text("INSERT INTO swarm_runs (id) VALUES (:id)"), {"id": run_id})
    await conn.commit()


async def test_phase_updates_phase_and_round(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    journal = RunJournal(run_id)

    await journal.phase(db, "round_1", 1)
    row = (
        (
            await db.execute(
                text("SELECT phase, current_round FROM swarm_runs WHERE id = :id"), {"id": run_id}
            )
        )
        .mappings()
        .fetchone()
    )
    assert row is not None
    assert row["phase"] == "round_1"
    assert row["current_round"] == 1

    await journal.phase(db, "done")
    row2 = (
        (
            await db.execute(
                text("SELECT phase, current_round FROM swarm_runs WHERE id = :id"), {"id": run_id}
            )
        )
        .mappings()
        .fetchone()
    )
    assert row2 is not None
    assert row2["phase"] == "done"
    assert row2["current_round"] is None  # round defaults to None when omitted


async def test_heartbeat_sets_timestamp(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    journal = RunJournal(run_id)

    before = (
        await db.execute(text("SELECT heartbeat_at FROM swarm_runs WHERE id = :id"), {"id": run_id})
    ).scalar()
    assert before is None

    await journal.heartbeat(db)

    after = (
        await db.execute(text("SELECT heartbeat_at FROM swarm_runs WHERE id = :id"), {"id": run_id})
    ).scalar()
    assert after is not None


async def test_turn_records_status(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    journal = RunJournal(run_id)

    await journal.turn(db, agent_id="a1", phase="round_2", round=2, status="done")

    row = (
        await db.execute(
            text("SELECT status FROM turn_log WHERE run_id = :r AND agent_id = 'a1'"), {"r": run_id}
        )
    ).scalar_one()
    assert row == "done"


async def test_turn_is_idempotent_on_reentry(db: AsyncConnection) -> None:
    """A second turn() call for the same (agent, phase, round) must not raise
    or duplicate the row — the first recorded status wins."""
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    journal = RunJournal(run_id)

    await journal.turn(db, agent_id="a1", phase="round_2", round=2, status="done")
    # Re-entrant call (e.g. resume re-running a turn that actually completed).
    await journal.turn(db, agent_id="a1", phase="round_2", round=2, status="done")

    count = (
        await db.execute(
            text("SELECT COUNT(*) FROM turn_log WHERE run_id = :r AND agent_id = 'a1'"),
            {"r": run_id},
        )
    ).scalar_one()
    assert count == 1


async def test_turn_overwrites_status_on_retry_success(db: AsyncConnection) -> None:
    """A turn that fails once (recorded 'failed') and then succeeds on retry
    must end up 'done' for that same (phase, round) — the latest status wins,
    so a successfully-retried turn is never mistaken for one still pending."""
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    journal = RunJournal(run_id)

    await journal.turn(db, agent_id="a1", phase="round_2", round=2, status="failed")
    await journal.turn(db, agent_id="a1", phase="round_2", round=2, status="done")

    count = (
        await db.execute(
            text("SELECT COUNT(*) FROM turn_log WHERE run_id = :r AND agent_id = 'a1'"),
            {"r": run_id},
        )
    ).scalar_one()
    assert count == 1
    status = (
        await db.execute(
            text("SELECT status FROM turn_log WHERE run_id = :r AND agent_id = 'a1'"), {"r": run_id}
        )
    ).scalar_one()
    assert status == "done"
    # And it now counts as completed for resume purposes.
    assert await journal.completed_turns(db, phase="round_2", round=2) == {"a1"}


async def test_turn_after_failed_does_not_conflict_across_rounds(db: AsyncConnection) -> None:
    """failed/done rows for DIFFERENT rounds are independent — only the exact
    (run, agent, phase, round) tuple is unique."""
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    journal = RunJournal(run_id)

    await journal.turn(db, agent_id="a1", phase="round_2", round=2, status="failed")
    await journal.turn(db, agent_id="a1", phase="round_3", round=3, status="done")

    rows = (
        await db.execute(
            text(
                "SELECT round, status FROM turn_log WHERE run_id = :r AND agent_id = 'a1' "
                "ORDER BY round"
            ),
            {"r": run_id},
        )
    ).fetchall()
    assert [(r, s) for r, s in rows] == [(2, "failed"), (3, "done")]


async def test_completed_turns_includes_done_and_skipped_excludes_failed(
    db: AsyncConnection,
) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    journal = RunJournal(run_id)

    await journal.turn(db, agent_id="a1", phase="round_2", round=2, status="done")
    await journal.turn(db, agent_id="a2", phase="round_2", round=2, status="skipped")
    await journal.turn(db, agent_id="a3", phase="round_2", round=2, status="failed")

    completed = await journal.completed_turns(db, phase="round_2", round=2)

    assert completed == {"a1", "a2"}


async def test_completed_turns_scoped_to_phase_and_round(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    journal = RunJournal(run_id)

    await journal.turn(db, agent_id="a1", phase="round_2", round=2, status="done")
    await journal.turn(db, agent_id="a1", phase="round_3", round=3, status="done")

    assert await journal.completed_turns(db, phase="round_2", round=2) == {"a1"}
    assert await journal.completed_turns(db, phase="round_4", round=4) == set()
