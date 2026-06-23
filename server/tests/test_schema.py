"""Tests that all database tables are created correctly by metadata.create_all()."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import metadata


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


async def _get_tables(conn: AsyncConnection) -> set[str]:
    from sqlalchemy import text

    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    )
    return {row[0] for row in result.fetchall()}


async def _get_columns(conn: AsyncConnection, table: str) -> set[str]:
    from sqlalchemy import text

    result = await conn.execute(text(f"PRAGMA table_info({table})"))
    return {row[1] for row in result.fetchall()}


_BASE_TABLES = {"agents", "knowledge_files", "agent_files"}

_ECSAS_TABLES = {
    "swarm_runs",
    "contracts",
    "threads",
    "draft_entries",
    "citations",
    "votes",
    "confirmed_entries",
    "bids",
    "reputation",
    "agent_trust",
    "amendments",
}


async def test_base_tables_exist(db: AsyncConnection) -> None:
    tables = await _get_tables(db)
    missing = _BASE_TABLES - tables
    assert not missing, f"Missing base tables: {missing}"


async def test_ecsas_tables_exist(db: AsyncConnection) -> None:
    tables = await _get_tables(db)
    missing = _ECSAS_TABLES - tables
    assert not missing, f"Missing ECSAS tables: {missing}"


async def test_agents_columns(db: AsyncConnection) -> None:
    cols = await _get_columns(db, "agents")
    for expected in (
        "id",
        "name",
        "description",
        "system_prompt",
        "provider",
        "model",
        "created_at",
        "capability_embedding",
    ):
        assert expected in cols, f"agents table missing column: {expected}"


async def test_draft_entries_columns(db: AsyncConnection) -> None:
    cols = await _get_columns(db, "draft_entries")
    for expected in (
        "id",
        "run_id",
        "thread_id",
        "round",
        "author_id",
        "entry_type",
        "content",
        "is_visible",
        "last_cited_round",
    ):
        assert expected in cols, f"draft_entries table missing column: {expected}"


async def test_confirmed_entries_columns(db: AsyncConnection) -> None:
    cols = await _get_columns(db, "confirmed_entries")
    for expected in ("id", "run_id", "thread_id", "content", "entry_type", "round_confirmed"):
        assert expected in cols, f"confirmed_entries table missing column: {expected}"


async def test_bids_columns(db: AsyncConnection) -> None:
    cols = await _get_columns(db, "bids")
    for expected in (
        "id",
        "run_id",
        "contract_id",
        "thread_id",
        "agent_id",
        "justification",
        "preliminary_score",
        "is_taker",
        "is_observer",
        "abstained",
    ):
        assert expected in cols, f"bids table missing column: {expected}"


async def test_reputation_columns(db: AsyncConnection) -> None:
    cols = await _get_columns(db, "reputation")
    for expected in ("run_id", "agent_id", "domain", "score", "updated_at"):
        assert expected in cols, f"reputation table missing column: {expected}"


async def test_agent_trust_columns(db: AsyncConnection) -> None:
    cols = await _get_columns(db, "agent_trust")
    for expected in ("agent_id", "domain", "trust_score", "runs_participated", "updated_at"):
        assert expected in cols, f"agent_trust table missing column: {expected}"


async def test_amendments_columns(db: AsyncConnection) -> None:
    cols = await _get_columns(db, "amendments")
    for expected in (
        "id",
        "run_id",
        "proposing_agent_id",
        "thread_id",
        "requested_domain",
        "reason",
        "status",
        "approve_votes",
        "total_voters",
    ):
        assert expected in cols, f"amendments table missing column: {expected}"


async def test_metadata_create_all_is_idempotent(db: AsyncConnection) -> None:
    await db.run_sync(metadata.create_all)
    tables = await _get_tables(db)
    assert "swarm_runs" in tables
