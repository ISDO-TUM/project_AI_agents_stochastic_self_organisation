"""Tests that all ECSAS database tables are created by init_db()."""

import os

import aiosqlite
import pytest

os.environ.setdefault("DB_PATH", ":memory:")

from api.db import init_db, close_db


async def _get_tables(db: aiosqlite.Connection) -> set[str]:
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ) as cur:
        rows = await cur.fetchall()
    return {row[0] for row in rows}


async def test_v0_tables_exist() -> None:
    await init_db()
    from api.db import _db
    tables = await _get_tables(_db)
    assert "agents" in tables
    assert "knowledge_files" in tables
    assert "agent_files" in tables
    await close_db()


_ECSAS_TABLES = {
    "swarm_runs",
    "contracts",
    "threads",
    "bids",
    "draft_entries",
    "citations",
    "votes",
    "confirmed_entries",
    "reputation",
    "agent_trust",
    "amendments",
}


async def test_ecsas_tables_exist() -> None:
    await init_db()
    from api.db import _db
    tables = await _get_tables(_db)
    missing = _ECSAS_TABLES - tables
    assert not missing, f"Missing tables: {missing}"
    await close_db()


async def test_agents_table_has_new_columns() -> None:
    await init_db()
    from api.db import _db
    async with _db.execute("PRAGMA table_info(agents)") as cur:
        rows = await cur.fetchall()
    cols = {row["name"] for row in rows}
    assert "capability_embedding" in cols
    assert "created_at" in cols
    await close_db()


async def test_init_db_is_idempotent() -> None:
    """Calling init_db() twice must not raise (all CREATE IF NOT EXISTS, ALTER guards)."""
    await init_db()
    await init_db()  # second call must succeed
    from api.db import _db
    tables = await _get_tables(_db)
    assert "swarm_runs" in tables
    await close_db()
