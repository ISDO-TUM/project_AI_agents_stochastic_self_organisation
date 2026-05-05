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

_CREATE_KNOWLEDGE_FILES_TABLE = """
CREATE TABLE IF NOT EXISTS knowledge_files (
    id      TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    content TEXT NOT NULL
);
"""

_CREATE_AGENT_FILES_TABLE = """
CREATE TABLE IF NOT EXISTS agent_files (
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    file_id  TEXT NOT NULL REFERENCES knowledge_files(id) ON DELETE CASCADE,
    PRIMARY KEY (agent_id, file_id)
);
"""

_CREATE_TRIALS_TABLE = """
CREATE TABLE IF NOT EXISTS trials (
    id              TEXT PRIMARY KEY,
    description     TEXT NOT NULL DEFAULT '',
    task_prompt     TEXT NOT NULL,
    protocol_name   TEXT NOT NULL,
    final_answer    TEXT,
    stopped_reason  TEXT,
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT
);
"""

_CREATE_ROUNDS_TABLE = """
CREATE TABLE IF NOT EXISTS rounds (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    trial_id     TEXT NOT NULL REFERENCES trials(id) ON DELETE CASCADE,
    round_index  INTEGER NOT NULL,
    aggregate    TEXT NOT NULL DEFAULT '',
    agreement    REAL NOT NULL DEFAULT 0.0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (trial_id, round_index)
);
"""

_CREATE_PROPOSALS_TABLE = """
CREATE TABLE IF NOT EXISTS proposals (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id  INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    agent_id  TEXT NOT NULL REFERENCES agents(id),
    content   TEXT NOT NULL,
    score     REAL NOT NULL DEFAULT 0.0,
    UNIQUE (round_id, agent_id)
);
"""

_CREATE_ROUND_EDGES_TABLE = """
CREATE TABLE IF NOT EXISTS round_edges (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id       INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    from_agent_id  TEXT NOT NULL REFERENCES agents(id),
    to_agent_id    TEXT NOT NULL REFERENCES agents(id),
    weight         REAL NOT NULL DEFAULT 1.0,
    UNIQUE (round_id, from_agent_id, to_agent_id)
);
"""

_db: aiosqlite.Connection | None = None


async def init_db() -> None:
    """Open the shared in-memory database and create all tables."""
    global _db
    _db = await aiosqlite.connect(":memory:")
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA foreign_keys = ON;")
    await _db.execute(_CREATE_AGENTS_TABLE)
    await _db.execute(_CREATE_KNOWLEDGE_FILES_TABLE)
    await _db.execute(_CREATE_AGENT_FILES_TABLE)
    await _db.execute(_CREATE_TRIALS_TABLE)
    await _db.execute(_CREATE_ROUNDS_TABLE)
    await _db.execute(_CREATE_PROPOSALS_TABLE)
    await _db.execute(_CREATE_ROUND_EDGES_TABLE)
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


def deserialise_knowledge_file_row(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert a knowledge_files table row to a plain dict."""
    return dict(row)
