"""In-memory SQLite session database.

A single :class:`aiosqlite.Connection` is shared across all requests because
SQLite ``:memory:`` databases are private to the connection that created them.
The database is initialised once at application startup via :func:`init_db` and
closed at shutdown via :func:`close_db`.
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
    provider      TEXT NOT NULL CHECK(provider IN ('openai', 'anthropic', 'groq', 'gemini')),
    model         TEXT NOT NULL,
    tools         TEXT NOT NULL DEFAULT '[]',
    connections   TEXT NOT NULL DEFAULT '[]'
);
"""

_CREATE_TRIALS_TABLE = """
CREATE TABLE IF NOT EXISTS trials (
    id          TEXT PRIMARY KEY,
    user_prompt TEXT NOT NULL,
    description TEXT NOT NULL
);
"""

_CREATE_ROUNDS_TABLE = """
CREATE TABLE IF NOT EXISTS rounds (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    trial_id TEXT NOT NULL,

    FOREIGN KEY (trial_id) REFERENCES trials(id)
);
"""

_CREATE_CONNECTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS connections (
    id            INTEGER PRIMARY KEY,
    round_id      INTEGER NOT NULL,
    from_agent_id TEXT NOT NULL,
    to_agent_id   TEXT NOT NULL,

    FOREIGN KEY (round_id)      REFERENCES rounds(id),
    FOREIGN KEY (from_agent_id) REFERENCES agents(id),
    FOREIGN KEY (to_agent_id)   REFERENCES agents(id),

    UNIQUE (round_id, from_agent_id, to_agent_id)
);
"""

_CREATE_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY,
    connection_id INTEGER NOT NULL,
    message       TEXT,

    FOREIGN KEY (connection_id) REFERENCES connections(id)
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


async def init_db() -> None:
    """Open the shared in-memory SQLite database and create all tables.

    Must be called once at application startup before any request is served.
    Subsequent calls are a no-op if the database is already initialised.
    """
    global _db
    _db = await aiosqlite.connect(":memory:")
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA foreign_keys = ON;")
    await _db.execute(_CREATE_AGENTS_TABLE)
    await _db.execute(_CREATE_KNOWLEDGE_FILES_TABLE)
    await _db.execute(_CREATE_AGENT_FILES_TABLE)
    await _db.execute(_CREATE_TRIALS_TABLE)
    await _db.execute(_CREATE_ROUNDS_TABLE)
    await _db.execute(_CREATE_CONNECTIONS_TABLE)
    await _db.execute(_CREATE_MESSAGES_TABLE)
    await _db.commit()


async def close_db() -> None:
    """Close the shared database connection.

    Safe to call even if the database was never initialised.
    """
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Yield the shared database connection for use as a FastAPI dependency.

    Yields:
        The open :class:`aiosqlite.Connection` instance.

    Raises:
        RuntimeError: If called before :func:`init_db`.
    """
    if _db is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")
    yield _db


def deserialise_agent_row(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert an agents table row to a plain dict, decoding JSON list columns.

    Args:
        row: A raw :class:`aiosqlite.Row` from the ``agents`` table.

    Returns:
        A dict with ``tools`` and ``connections`` decoded from their JSON string representations.
    """
    data = dict(row)
    data["tools"] = json.loads(data["tools"])
    data["connections"] = json.loads(data.get("connections") or "[]")
    return data


def deserialise_trial_row(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert a trials table row to a plain dict.

    Args:
        row: A raw :class:`aiosqlite.Row` from the ``trials`` table.

    Returns:
        A plain dict representation of the row.
    """
    return dict(row)


def deserialise_round_row(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert a rounds table row to a plain dict.

    Args:
        row: A raw :class:`aiosqlite.Row` from the ``rounds`` table.

    Returns:
        A plain dict representation of the row.
    """
    return dict(row)


def deserialise_connection_row(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert a connections table row to a plain dict.

    Args:
        row: A raw :class:`aiosqlite.Row` from the ``connections`` table.

    Returns:
        A plain dict representation of the row.
    """
    return dict(row)


def deserialise_message_row(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert a messages table row to a plain dict.

    Args:
        row: A raw :class:`aiosqlite.Row` from the ``messages`` table.

    Returns:
        A plain dict representation of the row.
    """
    return dict(row)


def deserialise_knowledge_file_row(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert a knowledge_files table row to a plain dict.

    Args:
        row: A raw :class:`aiosqlite.Row` from the ``knowledge_files`` table.

    Returns:
        A plain dict representation of the row.
    """
    return dict(row)


async def load_agent_file_names(db: aiosqlite.Connection, agent_id: str) -> list[str]:
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
    """Append an instruction to use the files tool before answering."""
    if not file_names:
        return system_prompt or None
    names = ", ".join(f'"{n}"' for n in file_names)
    hint = (
        f"\n\nYou have knowledge files attached: {names}. "
        "Use the 'files' tool to read relevant files before answering. "
        "Always check file contents first, then base your answer on what you find."
    )
    return (system_prompt or "") + hint
