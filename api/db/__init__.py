"""Configurable SQLite session database.

Supports both file-backed and in-memory databases via the DB_PATH environment
variable. A single :class:`aiosqlite.Connection` is shared across all requests
because SQLite ``:memory:`` databases are private to the connection that created them.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator
from typing import Any

import aiosqlite

_CREATE_AGENTS_TABLE = """
CREATE TABLE IF NOT EXISTS agents (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    provider      TEXT NOT NULL CHECK(provider IN ('openai', 'anthropic', 'groq')),
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

_db: aiosqlite.Connection | None = None

_DB_PATH_DEFAULT = "./data/swarm.db"


async def init_db() -> None:
    """Open the database and create all tables.

    Uses DB_PATH env var; defaults to ./data/swarm.db.
    Pass DB_PATH=:memory: in tests for isolation.
    """
    global _db
    db_path = os.getenv("DB_PATH", _DB_PATH_DEFAULT)
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    _db = await aiosqlite.connect(db_path)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA foreign_keys = ON;")
    await _db.execute(_CREATE_AGENTS_TABLE)
    await _db.execute(_CREATE_KNOWLEDGE_FILES_TABLE)
    await _db.execute(_CREATE_AGENT_FILES_TABLE)
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


async def load_agent_file_names(
    db: aiosqlite.Connection, agent_id: str
) -> list[str]:
    """Return the names of all knowledge files attached to an agent."""
    async with db.execute(
        """
        SELECT kf.name
          FROM knowledge_files kf
          JOIN agent_files af ON af.file_id = kf.id
         WHERE af.agent_id = ?
        """,
        (agent_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [r["name"] for r in rows]


def hint_files_in_prompt(
    system_prompt: str | None,
    file_names: list[str],
) -> str | None:
    """Append a one-line hint listing available file names so the agent can decide to read them."""
    if not file_names:
        return system_prompt or None
    names = ", ".join(f'"{n}"' for n in file_names)
    hint = f"\n\nYou have the following knowledge files available via the 'files' tool: {names}."
    return (system_prompt or "") + hint
