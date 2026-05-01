"""In-memory SQLite session database.

A single :class:`aiosqlite.Connection` is shared across all requests because
SQLite ``:memory:`` databases are private to the connection that created them.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import aiosqlite

_CREATE_AGENTS_TABLE = """
CREATE TABLE IF NOT EXISTS agents (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    provider      TEXT NOT NULL CHECK(provider IN ('openai', 'anthropic')),
    model         TEXT NOT NULL,
    tools         TEXT NOT NULL DEFAULT '[]',
    connections   TEXT NOT NULL DEFAULT '[]'
);
"""

_db: aiosqlite.Connection | None = None


async def init_db() -> None:
    """Open the shared in-memory database and create all tables."""
    global _db
    _db = await aiosqlite.connect(":memory:")
    _db.row_factory = aiosqlite.Row
    await _db.execute(_CREATE_AGENTS_TABLE)
    await _db.commit()


async def close_db() -> None:
    """Close the shared database connection."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Yield the shared database connection as a FastAPI dependency.

    Raises:
        RuntimeError: If called before :func:`init_db`.
    """
    if _db is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")
    yield _db


def deserialise_agent_row(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert an agents table row to a dict with decoded JSON list columns."""
    data = dict(row)
    data["tools"] = json.loads(data["tools"])
    data["connections"] = json.loads(data["connections"])
    return data
