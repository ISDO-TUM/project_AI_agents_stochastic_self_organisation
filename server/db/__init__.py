"""Async database access via SQLAlchemy Core.

The engine is built from ``DATABASE_URL`` at application startup. PostgreSQL is
used in production (and via docker-compose locally); the test suite points the
same code at an in-memory SQLite database, so no external service is required to
run ``pytest``. Connection-string schemes handed out by Railway/Heroku
(``postgresql://`` / ``postgres://``) are normalised to the asyncpg driver.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import RowMapping, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import (
    agent_files,
    agents,
    connections,
    experiments,
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


# NOTE: the periodic retention sweep (``cleanup_stale_data`` for stale agents and
# ``prune_trials`` for old run history) was removed on purpose: all data now
# persists until the user deletes it via the explicit delete endpoints.


async def _apply_column_migrations(conn: AsyncConnection) -> None:
    """Add columns introduced after the initial schema creation.

    Uses IF NOT EXISTS / PRAGMA guards so it is safe to run on every startup
    against both fresh and already-migrated databases.
    """
    dialect = conn.dialect.name
    if dialect == "postgresql":
        for stmt in (
            # Pre-existing migrations
            "ALTER TABLE knowledge_files ADD COLUMN IF NOT EXISTS"
            " created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL",
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS"
            " created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL",
            # ECSAS: agent expertise vector consumed by the auction engine
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS capability_embedding TEXT DEFAULT NULL",
            # trials: simulation tracking columns
            "ALTER TABLE trials ADD COLUMN IF NOT EXISTS mode TEXT",
            "ALTER TABLE trials ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'running'",
            "ALTER TABLE trials ADD COLUMN IF NOT EXISTS created_at TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE trials ADD COLUMN IF NOT EXISTS completed_at TEXT",
            # rounds: index, phase and timestamp
            "ALTER TABLE rounds ADD COLUMN IF NOT EXISTS round_index INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE rounds ADD COLUMN IF NOT EXISTS phase TEXT NOT NULL DEFAULT 'unknown'",
            "ALTER TABLE rounds ADD COLUMN IF NOT EXISTS created_at TEXT NOT NULL DEFAULT ''",
            # connections: make agent ids nullable for SYSTEM messages
            "ALTER TABLE connections ALTER COLUMN from_agent_id DROP NOT NULL",
            "ALTER TABLE connections ALTER COLUMN to_agent_id DROP NOT NULL",
            # messages: routing metadata and timestamp
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS round_id INTEGER",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS from_agent_id TEXT",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS to_agent_id TEXT",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS"
            " message_type TEXT NOT NULL DEFAULT 'unknown'",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS created_at TEXT NOT NULL DEFAULT ''",
            # experiments → trials FK
            "ALTER TABLE trials ADD COLUMN IF NOT EXISTS experiment_id TEXT"
            " REFERENCES experiments(id)",
            # connections/messages: snapshot agent names so history survives the
            # agents being deleted when the canvas is cleared.
            "ALTER TABLE connections ADD COLUMN IF NOT EXISTS from_agent_name TEXT",
            "ALTER TABLE connections ADD COLUMN IF NOT EXISTS to_agent_name TEXT",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS from_agent_name TEXT",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS to_agent_name TEXT",
            # Drop the agent foreign keys on the history tables so deleting agents
            # (clearing the canvas) no longer cascades away the run history /
            # statistics. The id columns stay as denormalised snapshots. The
            # constraint names are PostgreSQL's defaults (<table>_<column>_fkey).
            "ALTER TABLE connections DROP CONSTRAINT IF EXISTS connections_from_agent_id_fkey",
            "ALTER TABLE connections DROP CONSTRAINT IF EXISTS connections_to_agent_id_fkey",
            "ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_from_agent_id_fkey",
            "ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_to_agent_id_fkey",
            # ECSAS: synthesised final answer persisted at run completion
            "ALTER TABLE swarm_runs ADD COLUMN IF NOT EXISTS final_answer TEXT",
            # Swarm ↔ history linkage: every swarm run gets a trials row.
            "ALTER TABLE swarm_runs ADD COLUMN IF NOT EXISTS trial_id TEXT",
            "CREATE INDEX IF NOT EXISTS idx_swarm_runs_trial ON swarm_runs (trial_id)",
            # Snapshot the author's display name so the board survives agent deletion.
            "ALTER TABLE draft_entries ADD COLUMN IF NOT EXISTS author_name TEXT",
            # Drop the agent foreign keys on the ECSAS run tables: like the topology
            # history above, a swarm run is an immutable audit trail that must
            # survive agents being deleted (clearing the canvas). The id columns
            # stay as denormalised snapshots. Constraint names are PostgreSQL's
            # defaults (<table>_<column>_fkey).
            "ALTER TABLE draft_entries DROP CONSTRAINT IF EXISTS draft_entries_author_id_fkey",
            "ALTER TABLE citations DROP CONSTRAINT IF EXISTS citations_citing_agent_id_fkey",
            "ALTER TABLE votes DROP CONSTRAINT IF EXISTS votes_voter_agent_id_fkey",
            "ALTER TABLE bids DROP CONSTRAINT IF EXISTS bids_agent_id_fkey",
            "ALTER TABLE reputation DROP CONSTRAINT IF EXISTS reputation_agent_id_fkey",
            "ALTER TABLE amendments DROP CONSTRAINT IF EXISTS amendments_proposing_agent_id_fkey",
            "ALTER TABLE agent_trust DROP CONSTRAINT IF EXISTS agent_trust_agent_id_fkey",
            # Anonymous per-browser ownership (no auth): NULL = legacy/shared rows.
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS user_id TEXT",
            "ALTER TABLE knowledge_files ADD COLUMN IF NOT EXISTS user_id TEXT",
            "ALTER TABLE experiments ADD COLUMN IF NOT EXISTS user_id TEXT",
            "ALTER TABLE trials ADD COLUMN IF NOT EXISTS user_id TEXT",
            "ALTER TABLE swarm_runs ADD COLUMN IF NOT EXISTS user_id TEXT",
            "CREATE INDEX IF NOT EXISTS idx_agents_user ON agents (user_id)",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_files_user ON knowledge_files (user_id)",
            "CREATE INDEX IF NOT EXISTS idx_experiments_user ON experiments (user_id)",
            "CREATE INDEX IF NOT EXISTS idx_trials_user ON trials (user_id)",
            "CREATE INDEX IF NOT EXISTS idx_swarm_runs_user ON swarm_runs (user_id)",
            # Rebuild the history-chain cascades. Databases created before the
            # ON DELETE CASCADE declarations in tables.py carry plain FKs (and
            # messages.round_id has none at all), so deleting a trial raised an
            # FK violation — the clear-history endpoints were broken on
            # PostgreSQL while passing on SQLite's freshly-created schema.
            # DROP + ADD is the PostgreSQL idiom for "ensure constraint shape"
            # (there is no ADD CONSTRAINT IF NOT EXISTS); dangling rows that
            # would fail validation are removed first — they are invisible to
            # every reader anyway (all queries join through the chain).
            "DELETE FROM rounds WHERE trial_id NOT IN (SELECT id FROM trials)",
            "DELETE FROM connections WHERE round_id NOT IN (SELECT id FROM rounds)",
            "DELETE FROM messages WHERE connection_id NOT IN (SELECT id FROM connections)",
            "DELETE FROM messages WHERE round_id IS NOT NULL"
            " AND round_id NOT IN (SELECT id FROM rounds)",
            "ALTER TABLE rounds DROP CONSTRAINT IF EXISTS rounds_trial_id_fkey",
            "ALTER TABLE rounds ADD CONSTRAINT rounds_trial_id_fkey"
            " FOREIGN KEY (trial_id) REFERENCES trials(id) ON DELETE CASCADE",
            "ALTER TABLE connections DROP CONSTRAINT IF EXISTS connections_round_id_fkey",
            "ALTER TABLE connections ADD CONSTRAINT connections_round_id_fkey"
            " FOREIGN KEY (round_id) REFERENCES rounds(id) ON DELETE CASCADE",
            "ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_connection_id_fkey",
            "ALTER TABLE messages ADD CONSTRAINT messages_connection_id_fkey"
            " FOREIGN KEY (connection_id) REFERENCES connections(id) ON DELETE CASCADE",
            "ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_round_id_fkey",
            "ALTER TABLE messages ADD CONSTRAINT messages_round_id_fkey"
            " FOREIGN KEY (round_id) REFERENCES rounds(id) ON DELETE CASCADE",
            # ECSAS: documents an agent consulted (via files()) while producing a post
            "ALTER TABLE draft_entries ADD COLUMN IF NOT EXISTS"
            " documents_used TEXT NOT NULL DEFAULT '[]'",
            # Structured contributions: claim/stance/evidence on draft_entries
            "ALTER TABLE draft_entries ADD COLUMN IF NOT EXISTS claim TEXT",
            "ALTER TABLE draft_entries ADD COLUMN IF NOT EXISTS stance TEXT",
            "ALTER TABLE draft_entries ADD COLUMN IF NOT EXISTS stance_target TEXT",
            "ALTER TABLE draft_entries ADD COLUMN IF NOT EXISTS"
            " evidence TEXT NOT NULL DEFAULT '[]'",
            # Contestable consensus: citation reasons, confirmed status, dedup merge
            "ALTER TABLE citations ADD COLUMN IF NOT EXISTS reason TEXT",
            "ALTER TABLE confirmed_entries ADD COLUMN IF NOT EXISTS"
            " status TEXT NOT NULL DEFAULT 'confirmed'",
            "ALTER TABLE draft_entries ADD COLUMN IF NOT EXISTS merged_into TEXT",
            # Resilient runs: phase/heartbeat/config columns on swarm_runs
            "ALTER TABLE swarm_runs ADD COLUMN IF NOT EXISTS phase TEXT",
            "ALTER TABLE swarm_runs ADD COLUMN IF NOT EXISTS current_round INTEGER",
            "ALTER TABLE swarm_runs ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE swarm_runs ADD COLUMN IF NOT EXISTS config TEXT",
            # Ratified synthesis: the takers' vote on the synthesised answer
            "ALTER TABLE swarm_runs ADD COLUMN IF NOT EXISTS ratification TEXT",
            # Multi-turn contract sessions
            "ALTER TABLE swarm_runs ADD COLUMN IF NOT EXISTS session_id TEXT",
            "ALTER TABLE swarm_runs ADD COLUMN IF NOT EXISTS parent_run_id TEXT",
            "ALTER TABLE confirmed_entries ADD COLUMN IF NOT EXISTS origin_run_id TEXT",
        ):
            await conn.execute(text(stmt))
    elif dialect == "sqlite":
        # SQLite: fresh test databases are created with the full schema via
        # metadata.create_all, so migrations only cover the pre-existing
        # knowledge_files/agents columns that may be missing on older DBs.
        for table, col, definition in (
            ("knowledge_files", "created_at", "DATETIME DEFAULT (datetime('now'))"),
            ("agents", "created_at", "DATETIME DEFAULT (datetime('now'))"),
            ("agents", "capability_embedding", "TEXT DEFAULT NULL"),
            ("trials", "mode", "TEXT"),
            ("trials", "status", "TEXT NOT NULL DEFAULT 'running'"),
            ("trials", "created_at", "TEXT NOT NULL DEFAULT ''"),
            ("trials", "completed_at", "TEXT"),
            ("rounds", "round_index", "INTEGER NOT NULL DEFAULT 0"),
            ("rounds", "phase", "TEXT NOT NULL DEFAULT 'unknown'"),
            ("rounds", "created_at", "TEXT NOT NULL DEFAULT ''"),
            ("messages", "round_id", "INTEGER"),
            ("messages", "from_agent_id", "TEXT"),
            ("messages", "to_agent_id", "TEXT"),
            ("messages", "message_type", "TEXT NOT NULL DEFAULT 'unknown'"),
            ("messages", "created_at", "TEXT NOT NULL DEFAULT ''"),
            ("trials", "experiment_id", "TEXT"),
            # Agent-name snapshots (see PostgreSQL branch). SQLite cannot rewrite
            # the agent FK to SET NULL in place, but fresh test databases get the
            # full SET NULL schema via metadata.create_all.
            ("connections", "from_agent_name", "TEXT"),
            ("connections", "to_agent_name", "TEXT"),
            ("messages", "from_agent_name", "TEXT"),
            ("messages", "to_agent_name", "TEXT"),
            ("swarm_runs", "final_answer", "TEXT"),
            ("swarm_runs", "trial_id", "TEXT"),
            ("draft_entries", "author_name", "TEXT"),
            ("agents", "user_id", "TEXT"),
            ("knowledge_files", "user_id", "TEXT"),
            ("experiments", "user_id", "TEXT"),
            ("trials", "user_id", "TEXT"),
            ("swarm_runs", "user_id", "TEXT"),
            ("draft_entries", "documents_used", "TEXT NOT NULL DEFAULT '[]'"),
            # Structured contributions
            ("draft_entries", "claim", "TEXT"),
            ("draft_entries", "stance", "TEXT"),
            ("draft_entries", "stance_target", "TEXT"),
            ("draft_entries", "evidence", "TEXT NOT NULL DEFAULT '[]'"),
            # Contestable consensus
            ("citations", "reason", "TEXT"),
            ("confirmed_entries", "status", "TEXT NOT NULL DEFAULT 'confirmed'"),
            ("draft_entries", "merged_into", "TEXT"),
            # Resilient runs
            ("swarm_runs", "phase", "TEXT"),
            ("swarm_runs", "current_round", "INTEGER"),
            ("swarm_runs", "heartbeat_at", "DATETIME"),
            ("swarm_runs", "config", "TEXT"),
            # Ratified synthesis
            ("swarm_runs", "ratification", "TEXT"),
            # Multi-turn contract sessions
            ("swarm_runs", "session_id", "TEXT"),
            ("swarm_runs", "parent_run_id", "TEXT"),
            ("confirmed_entries", "origin_run_id", "TEXT"),
        ):
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            if col not in {row[1] for row in result.fetchall()}:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {definition}"))


# Orphaned "running" runs (crash / redeploy mid-flight) are flipped to
# 'interrupted' once their heartbeat goes stale, so no run is immortal.
STALE_RUN_MINUTES = 10


async def reap_stale_runs(conn: AsyncConnection) -> int:
    """Flip orphaned 'running' runs (stale heartbeat or none at all) to
    'interrupted' so no run is immortal after a crash/deploy. Returns count.

    At boot no legitimate run can be mid-flight in *this* process, but another
    replica could still be running one — the heartbeat cutoff, not boot itself,
    is the guard, so this is safe to call unconditionally from ``init_db``.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=STALE_RUN_MINUTES)
    result = await conn.execute(
        text(
            "UPDATE swarm_runs SET status = 'interrupted' "
            "WHERE status = 'running' "
            "AND (heartbeat_at IS NULL OR heartbeat_at < :cutoff)"
        ),
        {"cutoff": cutoff},
    )
    return result.rowcount or 0


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
        await reap_stale_runs(conn)
        # Lazy import: server.market_hive imports server.db at module load time
        # (tool registration), so importing it eagerly here would cycle.
        from server.market_hive.trust import migrate_agent_trust_to_ledger

        await migrate_agent_trust_to_ledger(conn)


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
    tool_names: list[str] | None = None,
) -> str | None:
    """Append an instruction telling the agent how to reach its attached files.

    Files are partitioned by extension: tabular files (``.csv``/``.tsv``) are
    steered toward the ``table_query``/``table_mutate`` tools and everything
    else toward the ``files`` tool — whichever of those the agent actually has.
    This closes the "raw string" leak path where a CSV could be handed to the
    ``files`` tool and pasted into the prompt as undifferentiated text instead
    of being loaded into a structured, queryable table. When ``tool_names`` is
    not supplied, the files-oriented hint is used for everything
    (backwards-compatible default).

    File names are sanitised before interpolation: newlines, quotes and
    angle-brackets are stripped so that a maliciously named file cannot inject
    new instructions into the system prompt.
    """
    if not file_names:
        return system_prompt or None
    # Strip characters that could break prompt structure
    _safe = [
        n.replace("\n", " ").replace("\r", " ").replace('"', "'").replace("<", "").replace(">", "")
        for n in file_names
    ]

    tools = set(tool_names) if tool_names is not None else None
    # Default (no tool info) keeps the files-oriented hint for back-compat.
    use_files = tools is None or "files" in tools
    use_table = tools is not None and ("table_query" in tools or "table_mutate" in tools)

    tabular_exts = (".csv", ".tsv")
    tabular = [n for n in _safe if n.lower().endswith(tabular_exts)]
    other = [n for n in _safe if not n.lower().endswith(tabular_exts)]

    parts: list[str] = []
    if other:
        names = ", ".join(f'"{n}"' for n in other)
        parts.append(f"You have knowledge files attached: {names}.")
        if use_files:
            parts.append(
                "Use the 'files' tool to read them before answering — always check "
                "file contents first, then base your answer on what you find."
            )
    if tabular:
        names = ", ".join(f'"{n}"' for n in tabular)
        parts.append(f"You have tabular data files attached: {names}.")
        if use_table:
            parts.append(
                "Load them with the 'table_query' tool (action='load' with the "
                "file_name), then inspect with 'table_query' (describe/read/export) "
                "or modify with 'table_mutate' (insert/update/delete/add_column) — "
                "do not treat them as raw text."
            )
        elif use_files:
            parts.append("Use the 'files' tool to read them before answering.")

    if not parts:
        return system_prompt or None
    return (system_prompt or "") + "\n\n" + " ".join(parts)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def deserialise_trial_row(row: RowMapping) -> dict[str, Any]:
    data = dict(row)
    for col in ("created_at", "completed_at"):
        if isinstance(data.get(col), datetime):
            data[col] = data[col].isoformat(timespec="seconds")
    return data


def deserialise_round_row(row: RowMapping) -> dict[str, Any]:
    data = dict(row)
    if isinstance(data.get("created_at"), datetime):
        data["created_at"] = data["created_at"].isoformat(timespec="seconds")
    return data


def deserialise_connection_row(row: RowMapping) -> dict[str, Any]:
    return dict(row)


def deserialise_message_row(row: RowMapping) -> dict[str, Any]:
    data = dict(row)
    if isinstance(data.get("created_at"), datetime):
        data["created_at"] = data["created_at"].isoformat(timespec="seconds")
    return data


async def resolve_experiment(
    conn: AsyncConnection,
    prompt: str,
    rounds_count: int,
    mode: str,
    ruleset: str | None,
    topology: str,
    fanout: int,
    agent_context: dict[str, str] | None,
    reuse_existing: bool = True,
    user_id: str | None = None,
) -> str:
    """Return an experiment id for the given run setup.

    When ``reuse_existing`` is true, matching setup hashes are grouped into the
    same experiment. Normal user-triggered runs pass ``reuse_existing=False`` so
    each click creates a fresh experiment while that run's iterations share it.
    The agent snapshot only covers agents visible to *user_id* (plus shared
    rows), matching the pool the run itself will use.
    """
    agent_stmt = select(
        agents.c.id,
        agents.c.name,
        agents.c.system_prompt,
        agents.c.provider,
        agents.c.model,
        agents.c.tools,
        agents.c.connections,
    ).order_by(agents.c.id)
    if user_id is not None:
        agent_stmt = agent_stmt.where((agents.c.user_id == user_id) | (agents.c.user_id.is_(None)))
    agent_rows = (await conn.execute(agent_stmt)).all()

    file_rows = (
        await conn.execute(
            select(agent_files.c.agent_id, agent_files.c.file_id).order_by(
                agent_files.c.agent_id, agent_files.c.file_id
            )
        )
    ).all()
    files_by_agent: dict[str, list[str]] = {}
    for row in file_rows:
        files_by_agent.setdefault(row.agent_id, []).append(row.file_id)

    agent_snapshot = [
        {
            "id": row.id,
            "name": row.name,
            "system_prompt": row.system_prompt,
            "provider": row.provider,
            "model": row.model,
            "tools": sorted(json.loads(row.tools)),
            "connections": sorted(json.loads(row.connections)),
            "file_ids": sorted(files_by_agent.get(row.id, [])),
        }
        for row in agent_rows
    ]

    canonical = {
        "agents": agent_snapshot,
        "params": {
            "prompt": prompt,
            "rounds": rounds_count,
            "mode": mode,
            "ruleset": ruleset,
            "topology": topology,
            "fanout": fanout,
            "agent_context": dict(sorted(agent_context.items())) if agent_context else None,
        },
    }
    exp_id = str(uuid.uuid4())
    hash_payload = canonical if reuse_existing else {**canonical, "run_id": exp_id}
    setup_hash = hashlib.sha256(
        json.dumps(hash_payload, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()

    if reuse_existing:
        existing = await conn.scalar(
            select(experiments.c.id).where(experiments.c.setup_hash == setup_hash)
        )
        if existing is not None:
            return str(existing)

    first_agent = agent_snapshot[0]["name"] if agent_snapshot else "unknown"
    description = f"{mode} · {first_agent} +{len(agent_snapshot) - 1} more"
    await conn.execute(
        experiments.insert().values(
            id=exp_id,
            setup_hash=setup_hash,
            description=description,
            agent_snapshot=json.dumps(agent_snapshot),
            simulation_params=json.dumps(canonical["params"]),
            created_at=_now_iso(),
            user_id=user_id,
        )
    )
    await conn.commit()
    return exp_id


async def create_trial(
    conn: AsyncConnection,
    user_prompt: str,
    description: str,
    mode: str,
    experiment_id: str | None = None,
    user_id: str | None = None,
) -> str:
    """Create a trial row for one simulation run and return its id."""
    trial_id = str(uuid.uuid4())
    await conn.execute(
        trials.insert().values(
            id=trial_id,
            experiment_id=experiment_id,
            user_prompt=user_prompt,
            description=description,
            mode=mode,
            status="running",
            created_at=_now_iso(),
            user_id=user_id,
        )
    )
    await conn.commit()
    return trial_id


async def update_trial_status(
    conn: AsyncConnection,
    trial_id: str,
    status: str,
) -> None:
    """Update a trial's execution status."""
    completed_at = _now_iso() if status in {"completed", "failed", "aborted"} else None
    await conn.execute(
        trials.update()
        .where(trials.c.id == trial_id)
        .values(status=status, completed_at=completed_at)
    )
    await conn.commit()


async def create_round(
    conn: AsyncConnection,
    trial_id: str,
    round_index: int,
    phase: str,
) -> int:
    """Create a round row scoped to a trial and return its id."""
    result = await conn.execute(
        rounds.insert().values(
            trial_id=trial_id,
            round_index=round_index,
            phase=phase,
            created_at=_now_iso(),
        )
    )
    await conn.commit()
    pk = result.inserted_primary_key
    if pk is None:
        raise RuntimeError("Failed to create simulation round.")
    return int(pk[0])


def _col_eq(col: Any, val: Any) -> Any:
    """Return col IS NULL or col == val depending on whether val is None."""
    return col.is_(None) if val is None else col == val


async def create_connection(
    conn: AsyncConnection,
    round_id: int,
    from_agent_id: str | None,
    to_agent_id: str | None,
    from_agent_name: str | None = None,
    to_agent_name: str | None = None,
) -> int:
    """Create a directed connection row and return its id.

    Agent ids are nullable so synthetic SYSTEM messages can be represented
    without requiring a real agent row. ``from_agent_name``/``to_agent_name`` are
    snapshotted so the edge stays readable after the agents are deleted.
    """
    row = await conn.execute(
        select(connections.c.id).where(
            connections.c.round_id == round_id,
            _col_eq(connections.c.from_agent_id, from_agent_id),
            _col_eq(connections.c.to_agent_id, to_agent_id),
        )
    )
    existing_pk = row.scalar_one_or_none()
    if existing_pk is not None:
        return int(existing_pk)

    try:
        result = await conn.execute(
            connections.insert().values(
                round_id=round_id,
                from_agent_id=from_agent_id,
                to_agent_id=to_agent_id,
                from_agent_name=from_agent_name,
                to_agent_name=to_agent_name,
            )
        )
        await conn.commit()
        pk = result.inserted_primary_key
        if pk is None:
            raise RuntimeError("Failed to create simulation connection.")
        return int(pk[0])
    except IntegrityError:
        await conn.rollback()

    row = await conn.execute(
        select(connections.c.id).where(
            connections.c.round_id == round_id,
            _col_eq(connections.c.from_agent_id, from_agent_id),
            _col_eq(connections.c.to_agent_id, to_agent_id),
        )
    )
    pk = row.scalar_one_or_none()
    if pk is None:
        raise RuntimeError("Failed to create or load simulation connection.")
    return int(pk)


async def create_message(
    conn: AsyncConnection,
    connection_id: int,
    round_id: int,
    from_agent_id: str | None,
    to_agent_id: str | None,
    message_type: str,
    message: str | None,
    from_agent_name: str | None = None,
    to_agent_name: str | None = None,
) -> int:
    """Create a message row with duplicated routing metadata for easy queries."""
    result = await conn.execute(
        messages.insert().values(
            connection_id=connection_id,
            round_id=round_id,
            from_agent_id=from_agent_id,
            to_agent_id=to_agent_id,
            from_agent_name=from_agent_name,
            to_agent_name=to_agent_name,
            message_type=message_type,
            message=message,
            created_at=_now_iso(),
        )
    )
    await conn.commit()
    pk = result.inserted_primary_key
    if pk is None:
        raise RuntimeError("Failed to create simulation message.")
    return int(pk[0])


async def _resolve_agent_names(conn: AsyncConnection, *agent_ids: str | None) -> dict[str, str]:
    """Look up names for the given agent ids (skipping ``None``)."""
    ids = {aid for aid in agent_ids if aid is not None}
    if not ids:
        return {}
    rows = await conn.execute(select(agents.c.id, agents.c.name).where(agents.c.id.in_(ids)))
    return {row.id: row.name for row in rows}


async def record_message(
    conn: AsyncConnection,
    round_id: int,
    from_agent_id: str | None,
    to_agent_id: str | None,
    message_type: str,
    message: str | None,
) -> int:
    """Create the directed connection if needed, then store a message on it.

    The agents' current names are snapshotted onto both the connection and the
    message so that the history survives the agents being deleted (e.g. when the
    canvas is cleared). Names are resolved while the agents still exist.
    """
    names = await _resolve_agent_names(conn, from_agent_id, to_agent_id)
    from_agent_name = names.get(from_agent_id) if from_agent_id is not None else None
    to_agent_name = names.get(to_agent_id) if to_agent_id is not None else None
    connection_id = await create_connection(
        conn, round_id, from_agent_id, to_agent_id, from_agent_name, to_agent_name
    )
    return await create_message(
        conn,
        connection_id,
        round_id,
        from_agent_id,
        to_agent_id,
        message_type,
        message,
        from_agent_name,
        to_agent_name,
    )
