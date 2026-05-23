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

_MIG_02_ALTER_AGENTS = [
    "ALTER TABLE agents ADD COLUMN capability_embedding TEXT DEFAULT NULL",
    "ALTER TABLE agents ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
]

_CREATE_ECSAS_TABLES = """
CREATE TABLE IF NOT EXISTS swarm_runs (
    id                  TEXT PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'running'
                        CHECK(status IN ('running','completed','failed','aborted')),
    mode                TEXT NOT NULL DEFAULT 'swarm'
                        CHECK(mode IN ('swarm','topology')),
    termination_reason  TEXT,
    termination_round   INTEGER,
    amendment_count     INTEGER NOT NULL DEFAULT 0,
    token_usage         TEXT NOT NULL DEFAULT '{}',
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at        TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contracts (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES swarm_runs(id),
    original_prompt     TEXT NOT NULL,
    task_type           TEXT NOT NULL,
    task_nature         TEXT NOT NULL DEFAULT 'single'
                        CHECK(task_nature IN ('single','multi')),
    required_expertise  TEXT NOT NULL DEFAULT '[]',
    complexity          TEXT NOT NULL DEFAULT 'medium'
                        CHECK(complexity IN ('low','medium','high')),
    confidence          REAL NOT NULL DEFAULT 0.0
                        CHECK(confidence >= 0.0 AND confidence <= 1.0),
    contract_embedding  TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS threads (
    id                  TEXT PRIMARY KEY,
    contract_id         TEXT NOT NULL REFERENCES contracts(id),
    run_id              TEXT NOT NULL REFERENCES swarm_runs(id),
    title               TEXT NOT NULL,
    description         TEXT NOT NULL,
    required_expertise  TEXT NOT NULL DEFAULT '[]',
    complexity          TEXT NOT NULL DEFAULT 'medium',
    thread_embedding    TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bids (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES swarm_runs(id),
    contract_id         TEXT REFERENCES contracts(id),
    thread_id           TEXT REFERENCES threads(id),
    agent_id            TEXT NOT NULL REFERENCES agents(id),
    justification       TEXT NOT NULL DEFAULT '',
    preliminary_score   REAL NOT NULL DEFAULT 0.0,
    is_taker            BOOLEAN NOT NULL DEFAULT 0,
    is_observer         BOOLEAN NOT NULL DEFAULT 0,
    abstained           BOOLEAN NOT NULL DEFAULT 0,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS draft_entries (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES swarm_runs(id),
    thread_id           TEXT NOT NULL REFERENCES threads(id),
    round               INTEGER NOT NULL,
    author_id           TEXT NOT NULL REFERENCES agents(id),
    entry_type          TEXT NOT NULL
                        CHECK(entry_type IN ('proposal','reply','vote','system')),
    content             TEXT NOT NULL,
    content_embedding   TEXT,
    reply_to            TEXT REFERENCES draft_entries(id),
    mention_agents      TEXT NOT NULL DEFAULT '[]',
    is_visible          BOOLEAN NOT NULL DEFAULT 1,
    deleted_at          TIMESTAMP,
    last_cited_round    INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS citations (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES swarm_runs(id),
    citing_agent_id     TEXT NOT NULL REFERENCES agents(id),
    cited_entry_id      TEXT NOT NULL REFERENCES draft_entries(id),
    citing_entry_id     TEXT REFERENCES draft_entries(id),
    round               INTEGER NOT NULL,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(citing_agent_id, cited_entry_id, round)
);

CREATE TABLE IF NOT EXISTS votes (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES swarm_runs(id),
    voter_agent_id      TEXT NOT NULL REFERENCES agents(id),
    voted_entry_id      TEXT NOT NULL REFERENCES draft_entries(id),
    thread_id           TEXT NOT NULL REFERENCES threads(id),
    round               INTEGER NOT NULL DEFAULT 1,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(voter_agent_id, voted_entry_id)
);

CREATE TABLE IF NOT EXISTS confirmed_entries (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES swarm_runs(id),
    thread_id           TEXT NOT NULL REFERENCES threads(id),
    source_draft_id     TEXT REFERENCES draft_entries(id),
    content             TEXT NOT NULL,
    content_embedding   TEXT,
    entry_type          TEXT NOT NULL DEFAULT 'finding'
                        CHECK(entry_type IN ('anchor','finding','system')),
    citation_count      INTEGER NOT NULL DEFAULT 0,
    round_confirmed     INTEGER NOT NULL,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reputation (
    run_id              TEXT NOT NULL REFERENCES swarm_runs(id),
    agent_id            TEXT NOT NULL REFERENCES agents(id),
    domain              TEXT NOT NULL,
    score               REAL NOT NULL DEFAULT 0.5
                        CHECK(score >= 0.0 AND score <= 1.0),
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, agent_id, domain)
);

CREATE TABLE IF NOT EXISTS agent_trust (
    agent_id            TEXT NOT NULL REFERENCES agents(id),
    domain              TEXT NOT NULL,
    trust_score         REAL NOT NULL DEFAULT 0.5
                        CHECK(trust_score >= 0.0 AND trust_score <= 1.0),
    runs_participated   INTEGER NOT NULL DEFAULT 0,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (agent_id, domain)
);

CREATE TABLE IF NOT EXISTS amendments (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES swarm_runs(id),
    proposing_agent_id  TEXT NOT NULL REFERENCES agents(id),
    thread_id           TEXT REFERENCES threads(id),
    requested_domain    TEXT NOT NULL,
    reason              TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','approved','rejected')),
    approve_votes       INTEGER NOT NULL DEFAULT 0,
    total_voters        INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_draft_run_thread_round
    ON draft_entries(run_id, thread_id, round);
CREATE INDEX IF NOT EXISTS idx_draft_visible
    ON draft_entries(run_id, is_visible);
CREATE INDEX IF NOT EXISTS idx_draft_reply_to
    ON draft_entries(reply_to);
CREATE INDEX IF NOT EXISTS idx_citations_cited
    ON citations(cited_entry_id, run_id);
CREATE INDEX IF NOT EXISTS idx_citations_agent
    ON citations(citing_agent_id, run_id);
CREATE INDEX IF NOT EXISTS idx_confirmed_run_thread
    ON confirmed_entries(run_id, thread_id);
CREATE INDEX IF NOT EXISTS idx_confirmed_citations
    ON confirmed_entries(citation_count DESC);
CREATE INDEX IF NOT EXISTS idx_bids_run
    ON bids(run_id, is_taker);
CREATE INDEX IF NOT EXISTS idx_trust_agent_domain
    ON agent_trust(agent_id, domain)
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

    # MIG-02: extend agents table (idempotent)
    async with _db.execute("PRAGMA table_info(agents)") as cur:
        rows = await cur.fetchall()
    existing_cols = {row["name"] for row in rows}
    for stmt in _MIG_02_ALTER_AGENTS:
        col_name = stmt.split("ADD COLUMN")[1].strip().split()[0]
        if col_name not in existing_cols:
            await _db.execute(stmt)

    # MIG-03: ECSAS tables (idempotent via CREATE IF NOT EXISTS)
    for statement in _CREATE_ECSAS_TABLES.strip().split(";"):
        statement = statement.strip()
        if statement:
            await _db.execute(statement)

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
