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
