"""Tests for stand_down persistence, tool, and table."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool


def test_swarm_stand_downs_table_shape() -> None:
    from server.db.tables import swarm_stand_downs

    cols = {c.name for c in swarm_stand_downs.columns}
    assert {"run_id", "agent_id", "thread_id", "round", "reason", "created_at"} <= cols


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from server.db.tables import swarm_stand_downs

    async with eng.begin() as conn:
        await conn.run_sync(swarm_stand_downs.metadata.create_all, tables=[swarm_stand_downs])
    yield eng
    await eng.dispose()


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncGenerator[AsyncConnection, None]:
    async with engine.connect() as conn:
        yield conn


@pytest.mark.asyncio
async def test_record_and_load_stand_down(db: AsyncConnection) -> None:
    from server.market_hive.stand_down import load_stood_down, record_stand_down

    await record_stand_down(
        db, run_id="r1", agent_id="a1", thread_id="t1", round=3, reason="done"
    )
    await record_stand_down(
        db, run_id="r1", agent_id="a2", thread_id="t1", round=3, reason="nothing to add"
    )
    await record_stand_down(
        db, run_id="r1", agent_id="a1", thread_id="t2", round=3, reason="done"
    )

    loaded = await load_stood_down(db, "r1")
    assert loaded["t1"] == {"a1", "a2"}
    assert loaded["t2"] == {"a1"}


@pytest.mark.asyncio
async def test_record_stand_down_is_idempotent(db: AsyncConnection) -> None:
    from server.market_hive.stand_down import load_stood_down, record_stand_down

    await record_stand_down(db, run_id="r1", agent_id="a1", thread_id="t1", round=3, reason="x")
    # Calling again for the same (run, agent, thread) must not raise or duplicate.
    await record_stand_down(db, run_id="r1", agent_id="a1", thread_id="t1", round=4, reason="y")

    loaded = await load_stood_down(db, "r1")
    assert loaded["t1"] == {"a1"}


@pytest.mark.asyncio
async def test_stand_down_tool_persists(db: AsyncConnection) -> None:
    import json

    from server.market_hive.stand_down import load_stood_down
    from server.market_hive.tools import StandDownTool

    tool = StandDownTool()
    result = await tool.execute(
        tool.input_model(reason="nothing more to add", thread_id="t1"),
        {"db": db, "run_id": "r1", "agent_id": "a1", "thread_id": "t1", "round": 3},
    )
    assert json.loads(result) == {"ok": True}
    loaded = await load_stood_down(db, "r1")
    assert loaded["t1"] == {"a1"}


def test_drop_stood_down_filters_only_that_thread() -> None:
    from server.market_hive.orchestrator import _drop_stood_down

    takers_by_thread = {"t1": ["a1", "a2", "a3"], "t2": ["a1", "a2"]}
    stood_down = {"t1": {"a1", "a3"}}

    result = _drop_stood_down(takers_by_thread, stood_down)

    assert result == {"t1": ["a2"], "t2": ["a1", "a2"]}
    # original is not mutated
    assert takers_by_thread["t1"] == ["a1", "a2", "a3"]
