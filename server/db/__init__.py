"""Async database access via SQLAlchemy Core.

The engine is built from ``DATABASE_URL`` at application startup. PostgreSQL is
used in production (and via docker-compose locally); the test suite points the
same code at an in-memory SQLite database, so no external service is required to
run ``pytest``. Connection-string schemes handed out by Railway/Heroku
(``postgresql://`` / ``postgres://``) are normalised to the asyncpg driver.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import RowMapping, delete, event, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import (
    agent_files,
    agents,
    connections,
    knowledge_files,
    messages,
    metadata,
    rounds,
    trials,
)

logger = logging.getLogger(__name__)

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


async def cleanup_stale_data(engine: AsyncEngine, max_age_hours: int = 24) -> int:
    """Delete agents and knowledge files older than *max_age_hours*.

    Deletion respects every FK constraint by following the same order as the
    DELETE ALL route: messages → connections → orphaned rounds → orphaned
    trials → agents (cascades agent_files) → orphaned knowledge_files.

    Returns:
        Number of agents deleted.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)

    async with engine.connect() as conn:
        stale_result = await conn.execute(select(agents.c.id).where(agents.c.created_at < cutoff))
        stale_agent_ids = [row.id for row in stale_result]

        if not stale_agent_ids:
            return 0

        # 1. Messages whose connection touches a stale agent
        stale_conn_result = await conn.execute(
            select(connections.c.id).where(
                connections.c.from_agent_id.in_(stale_agent_ids)
                | connections.c.to_agent_id.in_(stale_agent_ids)
            )
        )
        stale_conn_ids = [row.id for row in stale_conn_result]

        if stale_conn_ids:
            await conn.execute(delete(messages).where(messages.c.connection_id.in_(stale_conn_ids)))
            await conn.execute(delete(connections).where(connections.c.id.in_(stale_conn_ids)))

        # 2. Rounds and trials that are now orphaned (no remaining connections)
        await conn.execute(delete(rounds).where(rounds.c.id.not_in(select(connections.c.round_id))))
        await conn.execute(delete(trials).where(trials.c.id.not_in(select(rounds.c.trial_id))))

        # 3. Stale agents — CASCADE removes agent_files rows
        await conn.execute(delete(agents).where(agents.c.id.in_(stale_agent_ids)))

        # 4. Knowledge files no longer attached to any agent
        await conn.execute(
            delete(knowledge_files).where(
                knowledge_files.c.id.not_in(select(agent_files.c.file_id))
            )
        )

        await conn.commit()

    logger.info(
        "Cleanup removed %d stale agent(s) (older than %dh)", len(stale_agent_ids), max_age_hours
    )
    return len(stale_agent_ids)


async def _apply_column_migrations(conn: AsyncConnection) -> None:
    """Add columns introduced after the initial schema creation.

    Uses IF NOT EXISTS / PRAGMA guards so it is safe to run on every startup
    against both fresh and already-migrated databases.
    """
    dialect = conn.dialect.name
    if dialect == "postgresql":
        for stmt in (
            "ALTER TABLE knowledge_files ADD COLUMN IF NOT EXISTS"
            " created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL",
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS"
            " created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL",
        ):
            await conn.execute(text(stmt))
    elif dialect == "sqlite":
        for table, col in (
            ("knowledge_files", "created_at"),
            ("agents", "created_at"),
        ):
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            if col not in {row[1] for row in result.fetchall()}:
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {col} DATETIME DEFAULT (datetime('now'))")
                )


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
        await _apply_column_migrations(conn)


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
