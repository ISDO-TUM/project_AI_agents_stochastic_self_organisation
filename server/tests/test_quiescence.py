"""Tests for TerminationEngine.check_quiescence."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# Reuse the in-memory fixtures + minimal schema + seed helpers already written
# for the equilibrium tests.
from test_termination import (  # noqa: F401  (fixtures used by pytest)
    _seed_run,
    db,
    engine,
)

from server.market_hive.termination import TerminationEngine


async def _post(conn: AsyncConnection, run_id: str, thread_id: str, round_: int) -> None:
    await conn.execute(
        text(
            "INSERT INTO draft_entries "
            "(id, run_id, thread_id, round, author_id, entry_type, content, is_visible) "
            "VALUES (:id, :r, :t, :rd, 'a1', 'reply', 'hi', true)"
        ),
        {"id": str(uuid.uuid4()), "r": run_id, "t": thread_id, "rd": round_},
    )


@pytest.mark.asyncio
async def test_quiescence_false_before_min_rounds(db: AsyncConnection) -> None:  # noqa: F811
    run_id, _contract_id, _thread_id = await _seed_run(db)
    eng = TerminationEngine(db, min_rounds=3)
    # Round 2 is below min_rounds=3 → never quiescent even with no activity.
    assert await eng.check_quiescence(run_id=run_id, current_round=2) is False


@pytest.mark.asyncio
async def test_quiescence_true_when_round_has_no_new_activity(db: AsyncConnection) -> None:  # noqa: F811
    run_id, _contract_id, thread_id = await _seed_run(db)
    # Rounds 2 and 3 have posts; round 4 is silent.
    await _post(db, run_id, thread_id, 2)
    await _post(db, run_id, thread_id, 3)
    eng = TerminationEngine(db, min_rounds=3)
    assert await eng.check_quiescence(run_id=run_id, current_round=4) is True


@pytest.mark.asyncio
async def test_quiescence_false_when_round_has_a_new_post(db: AsyncConnection) -> None:  # noqa: F811
    run_id, _contract_id, thread_id = await _seed_run(db)
    await _post(db, run_id, thread_id, 4)
    eng = TerminationEngine(db, min_rounds=3)
    assert await eng.check_quiescence(run_id=run_id, current_round=4) is False
