"""Async database access via SQLAlchemy Core.

The engine is built from ``DATABASE_URL`` at application startup. PostgreSQL is
used in production (and via docker-compose locally); the test suite points the
same code at an in-memory SQLite database, so no external service is required to
run ``pytest``. Connection-string schemes handed out by Railway/Heroku
(``postgresql://`` / ``postgres://``) are normalised to the asyncpg driver.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import RowMapping, event, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import agent_files, knowledge_files, metadata

_engine: AsyncEngine | None = None


def _normalise_url(url: str) -> str:
    """Force the asyncpg driver for PostgreSQL URLs handed out by hosts."""
    if url.startswith("postgresql+") or url.startswith("sqlite+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


def _build_engine(url: str) -> AsyncEngine:
    norm = _normalise_url(url)
    if norm.startswith("sqlite"):
        # A single shared connection so an in-memory database survives across
        # requests within a test (each connection otherwise gets its own DB).
        engine = create_async_engine(
            norm,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_async_engine(norm, pool_pre_ping=True)

    if engine.dialect.name == "sqlite":
        # SQLite ignores foreign keys unless asked per connection; PostgreSQL
        # enforces them by default.
        @event.listens_for(engine.sync_engine, "connect")
        def _enable_sqlite_fks(dbapi_conn: Any, _record: Any) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


async def init_db() -> None:
    """Build the engine from ``DATABASE_URL`` and create all tables.

    Must be called once at application startup before any request is served.

    Raises:
        RuntimeError: If ``DATABASE_URL`` is not set.
    """
    global _engine
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set.")
    _engine = _build_engine(url)
    async with _engine.begin() as conn:
        await conn.run_sync(metadata.create_all)


async def close_db() -> None:
    """Dispose the engine and its connection pool.

    Safe to call even if the engine was never initialised.
    """
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def get_engine() -> AsyncEngine:
    """Return the initialised engine.

    Raises:
        RuntimeError: If called before :func:`init_db`.
    """
    if _engine is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")
    return _engine


async def get_db() -> AsyncGenerator[AsyncConnection, None]:
    """Yield a pooled connection for use as a FastAPI dependency.

    Yields:
        An open :class:`AsyncConnection`. Writes must be committed explicitly
        via ``await conn.commit()``.

    Raises:
        RuntimeError: If called before :func:`init_db`.
    """
    if _engine is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")
    async with _engine.connect() as conn:
        yield conn


def deserialise_agent_row(row: RowMapping) -> dict[str, Any]:
    """Convert an agents row to a dict, decoding JSON list columns.

    Args:
        row: A mapping row from the ``agents`` table.

    Returns:
        A dict with ``tools`` and ``connections`` decoded from their JSON
        string representations.
    """
    data = dict(row)
    data["tools"] = json.loads(data["tools"])
    data["connections"] = json.loads(data["connections"])
    return data


def deserialise_knowledge_file_row(row: RowMapping) -> dict[str, Any]:
    """Convert a knowledge_files row to a plain dict.

    Args:
        row: A mapping row from the ``knowledge_files`` table.

    Returns:
        A plain dict representation of the row.
    """
    return dict(row)


async def load_agent_files(conn: AsyncConnection, agent_id: str) -> dict[str, str]:
    """Return ``{file_name: content}`` for every file attached to an agent."""
    stmt = (
        select(knowledge_files.c.name, knowledge_files.c.content)
        .select_from(
            knowledge_files.join(agent_files, agent_files.c.file_id == knowledge_files.c.id)
        )
        .where(agent_files.c.agent_id == agent_id)
    )
    result = await conn.execute(stmt)
    return {row.name: row.content for row in result}


async def load_files_by_agent(conn: AsyncConnection) -> dict[str, dict[str, str]]:
    """Return ``{agent_id: {file_name: content}}`` for all attachments at once.

    Used by the simulation engine to pre-load every agent's files before the
    concurrent LLM phase, so no database access happens inside ``asyncio.gather``.
    """
    stmt = select(
        agent_files.c.agent_id,
        knowledge_files.c.name,
        knowledge_files.c.content,
    ).select_from(agent_files.join(knowledge_files, knowledge_files.c.id == agent_files.c.file_id))
    result = await conn.execute(stmt)
    out: dict[str, dict[str, str]] = {}
    for row in result:
        out.setdefault(row.agent_id, {})[row.name] = row.content
    return out


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
