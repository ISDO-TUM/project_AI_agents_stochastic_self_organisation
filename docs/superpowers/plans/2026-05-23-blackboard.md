# Blackboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the V0 repository with a file-backed SQLite database, all ECSAS schemas, the Blackboard class and its five tools, two REST endpoints, and the BlackboardPanel frontend component tree.

**Architecture:** Bottom-up — DB migrations first, then Pydantic schemas, then the Blackboard class, then tools registered in the existing registry, then REST endpoints, then the frontend hook and component tree. The frontend uses a hybrid model: REST-initialized state on mount, with a `dispatch()` function pre-wired to handle SSE events in Phase 2.

**Tech Stack:** Python 3.13, FastAPI, aiosqlite, Pydantic v2, pytest-asyncio, httpx; Next.js App Router, React 18, TypeScript, Tailwind CSS, shadcn/ui.

---

## File Map

**Create:**
- `api/swarm/__init__.py`
- `api/swarm/schemas.py`
- `api/swarm/blackboard.py`
- `api/tools/builtin/blackboard_tools.py`
- `api/routes/simulation.py`
- `api/tests/test_blackboard.py`
- `api/tests/test_simulation.py`
- `app/hooks/useBlackboard.ts`
- `app/components/draft-entry.tsx`
- `app/components/draft-section.tsx`
- `app/components/confirmed-section.tsx`
- `app/components/blackboard-panel.tsx`

**Modify:**
- `api/db/__init__.py` — file-backed SQLite + ECSAS tables + ALTER TABLE guards
- `api/schemas/__init__.py` — extend `SimulationStep.type` with ECSAS event types
- `api/tools/registry.py` — register blackboard + stub auction tools
- `api/routes/__init__.py` — export simulation router
- `api/index.py` — mount simulation router
- `api/tests/conftest.py` — set `DB_PATH=:memory:` for tests
- `app/lib/types.ts` — add swarm types
- `app/components/app.tsx` — add `runId` state, layout split, BlackboardPanel mount

---

## Task 1: MIG-01 — File-backed SQLite

**Files:**
- Modify: `api/db/__init__.py`
- Modify: `api/tests/conftest.py`
- Test: `api/tests/test_schema.py` (new)

- [ ] **Step 1: Create the test file and write a failing test**

Create `api/tests/test_schema.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it passes before your changes (baseline)**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/api
uv run pytest tests/test_schema.py::test_v0_tables_exist -v
```

Expected: PASS (V0 tables already exist).

- [ ] **Step 3: Update conftest.py to pin DB_PATH=:memory: for all tests**

Replace the contents of `api/tests/conftest.py` with:

```python
"""Shared pytest fixtures for the API test suite."""

import os

os.environ.setdefault("DB_PATH", ":memory:")  # Must be before app import

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from api.index import app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Yield an async HTTP client wired directly to the ASGI app.

    The app's lifespan runs for each test, giving every test a clean
    in-memory database.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
```

- [ ] **Step 4: Update api/db/__init__.py to use file-backed SQLite**

Replace the `_db` declaration and `init_db()` function (lines 44–56) with:

```python
import os

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
```

Also add `import os` at the top of the file (after `from __future__ import annotations`).

- [ ] **Step 5: Run the full existing test suite to verify nothing broke**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/api
uv run pytest tests/ -v
```

Expected: all existing tests PASS.

- [ ] **Step 6: Commit**

```bash
git add api/db/__init__.py api/tests/conftest.py api/tests/test_schema.py
git commit -m "feat(db): switch SQLite to file-backed via DB_PATH env var"
```

---

## Task 2: MIG-02 + MIG-03 — ECSAS Tables

**Files:**
- Modify: `api/db/__init__.py`
- Test: `api/tests/test_schema.py`

- [ ] **Step 1: Write failing tests for all ECSAS tables**

Append to `api/tests/test_schema.py`:

```python
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
```

- [ ] **Step 2: Run to confirm both tests fail**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/api
uv run pytest tests/test_schema.py::test_ecsas_tables_exist tests/test_schema.py::test_agents_table_has_new_columns -v
```

Expected: both FAIL.

- [ ] **Step 3: Add MIG-02 and MIG-03 SQL constants to api/db/__init__.py**

Add after the `_CREATE_AGENT_FILES_TABLE` constant (before `_db: ...`):

```python
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
    ON agent_trust(agent_id, domain);
"""
```

- [ ] **Step 4: Call MIG-02 and MIG-03 inside init_db()**

Update the `init_db()` body — after the three V0 `await _db.execute(...)` calls and before `await _db.commit()`:

```python
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
```

Remove the old `await _db.commit()` that was already there (replace it, don't add a second one).

- [ ] **Step 5: Run the new tests**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/api
uv run pytest tests/test_schema.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 6: Run the full suite to confirm no regressions**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add api/db/__init__.py api/tests/test_schema.py
git commit -m "feat(db): add MIG-02 and MIG-03 ECSAS tables and agent columns"
```

---

## Task 3: Pydantic Schemas

**Files:**
- Create: `api/swarm/__init__.py`
- Create: `api/swarm/schemas.py`
- Modify: `api/schemas/__init__.py`

- [ ] **Step 1: Create the swarm package**

Create `api/swarm/__init__.py` (empty file):
```python
```

- [ ] **Step 2: Create api/swarm/schemas.py**

```python
"""Pydantic schemas for the ECSAS swarm system."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SwarmRunConfig(BaseModel):
    prompt: str
    mode: Literal["swarm", "topology"] = "swarm"
    min_takers: int = Field(default=2, ge=1, le=10)
    max_takers: int = Field(default=5, ge=1, le=20)
    min_rounds: int = Field(default=2, ge=1, le=5)
    max_rounds: int = Field(default=10, ge=2, le=20)
    token_budget: int = Field(default=50_000, ge=5_000, le=500_000)
    max_amendments: int = Field(default=2, ge=0, le=5)
    decay_rounds: int = Field(default=3, ge=1, le=10)
    invite_floor: float = Field(default=0.3, ge=0.0, le=1.0)
    alpha: float = Field(default=0.5)
    beta: float = Field(default=0.4)
    gamma: float = Field(default=0.1)
    k_attention: int = Field(default=10, ge=3, le=30)
    k_consecutive: int = Field(default=2, ge=1, le=5)
    epsilon_entropy: int = Field(default=0, ge=0)
    t_initial: float = Field(default=0.0)
    delta_t: float = Field(default=0.1)


class ThreadSchema(BaseModel):
    id: str
    contract_id: str
    run_id: str
    title: str
    description: str
    required_expertise: list[str] = []
    complexity: Literal["low", "medium", "high"] = "medium"
    thread_embedding: list[float] | None = None
    created_at: datetime


class ContractSchema(BaseModel):
    id: str
    run_id: str
    original_prompt: str
    task_type: str
    task_nature: Literal["single", "multi"] = "single"
    required_expertise: list[str] = []
    complexity: Literal["low", "medium", "high"] = "medium"
    confidence: float = 0.0
    contract_embedding: list[float] | None = None
    threads: list[ThreadSchema] = []
    created_at: datetime


class DraftEntrySchema(BaseModel):
    id: str
    run_id: str
    thread_id: str
    round: int
    author_id: str
    author_name: str
    entry_type: Literal["proposal", "reply", "vote", "system"]
    content: str
    reply_to: str | None = None
    mention_agents: list[str] = []
    is_visible: bool = True
    deleted_at: datetime | None = None
    last_cited_round: int = 0
    citation_count: int = 0
    created_at: datetime
    children: list[DraftEntrySchema] = []


DraftEntrySchema.model_rebuild()


class ConfirmedEntrySchema(BaseModel):
    id: str
    run_id: str
    thread_id: str
    source_draft_id: str | None = None
    content: str
    entry_type: Literal["anchor", "finding", "system"] = "finding"
    citation_count: int = 0
    round_confirmed: int
    created_at: datetime


class SwarmFinalOutput(BaseModel):
    run_id: str
    answers: dict[str, ConfirmedEntrySchema]
    confirmed_layer: list[ConfirmedEntrySchema]
    termination_round: int
    termination_reason: Literal["equilibrium", "max_rounds", "budget"]
    metadata: dict[str, Any] = {}


class BlackboardResponse(BaseModel):
    threads: list[ThreadSchema]
    confirmed: list[ConfirmedEntrySchema]
    draft: list[DraftEntrySchema]


class SeedRequest(BaseModel):
    prompt: str = "Test prompt for blackboard seeding"
    agent_ids: list[str] = []


class SeedResponse(BaseModel):
    run_id: str
    thread_id: str
```

- [ ] **Step 3: Extend SimulationStep type in api/schemas/__init__.py**

Find the line:
```python
_SimStepType = Literal["system", "agent-to-agent", "tool", "agent-to-source"]
```

Replace it with:
```python
_SimStepType = Literal[
    # V0 (unchanged)
    "system", "agent-to-agent", "tool", "agent-to-source",
    # ECSAS
    "bid", "abstain", "bb-post", "bb-cite", "bb-vote",
    "bb-promote", "bb-delete", "bb-mention",
    "amendment", "amendment-approved", "amendment-rejected",
    "convergence",
]
```

- [ ] **Step 4: Verify schemas import cleanly**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/api
uv run python -c "from api.swarm.schemas import DraftEntrySchema, ConfirmedEntrySchema, ThreadSchema, SwarmRunConfig; print('OK')"
```

Expected output: `OK`

- [ ] **Step 5: Commit**

```bash
git add api/swarm/__init__.py api/swarm/schemas.py api/schemas/__init__.py
git commit -m "feat(swarm): add ECSAS Pydantic schemas and extend SimulationStep types"
```

---

## Task 4: Blackboard.post + Blackboard.read

**Files:**
- Create: `api/swarm/blackboard.py`
- Create: `api/tests/test_blackboard.py`

- [ ] **Step 1: Write failing tests for post and read**

Create `api/tests/test_blackboard.py`:

```python
"""Unit tests for the Blackboard class."""

from __future__ import annotations

import json
import os
import uuid

import pytest

os.environ.setdefault("DB_PATH", ":memory:")

from api.db import init_db, close_db
from api.swarm.blackboard import Blackboard


@pytest.fixture
async def db():
    await init_db()
    from api.db import _db
    yield _db
    await close_db()


async def _seed_run(db, run_id: str, thread_id: str, agent_id: str) -> None:
    """Insert minimal swarm_runs + threads + agents rows for FK constraints."""
    await db.execute(
        "INSERT OR IGNORE INTO swarm_runs (id) VALUES (?)", (run_id,)
    )
    # Insert a contract first (threads FK to contracts)
    contract_id = str(uuid.uuid4())
    await db.execute(
        "INSERT OR IGNORE INTO contracts (id, run_id, original_prompt, task_type) "
        "VALUES (?, ?, ?, ?)",
        (contract_id, run_id, "test prompt", "analysis"),
    )
    await db.execute(
        "INSERT OR IGNORE INTO threads (id, contract_id, run_id, title, description) "
        "VALUES (?, ?, ?, ?, ?)",
        (thread_id, contract_id, run_id, "Test Thread", "A test thread"),
    )
    await db.execute(
        "INSERT OR IGNORE INTO agents "
        "(id, name, description, system_prompt, provider, model) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (agent_id, "TestAgent", "desc", "system", "openai", "gpt-4o"),
    )
    await db.commit()


async def test_post_returns_entry_id(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_id,
        content="My proposal",
        entry_type="proposal",
        round=1,
    )

    assert isinstance(entry_id, str)
    assert len(entry_id) > 0


async def test_post_then_read_returns_entry(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_id,
        content="My proposal",
        entry_type="proposal",
        round=1,
    )
    results = await bb.read(run_id=run_id, query="proposal", thread_id=thread_id)

    assert len(results) == 1
    assert results[0].id == entry_id
    assert results[0].content == "My proposal"
    assert results[0].author_name == "TestAgent"
    assert results[0].citation_count == 0


async def test_read_respects_thread_filter(db) -> None:
    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    thread_a = str(uuid.uuid4())
    thread_b = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())

    await db.execute("INSERT INTO swarm_runs (id) VALUES (?)", (run_id,))
    await db.execute(
        "INSERT INTO contracts (id, run_id, original_prompt, task_type) VALUES (?,?,?,?)",
        (contract_id, run_id, "p", "t"),
    )
    await db.execute(
        "INSERT INTO threads (id, contract_id, run_id, title, description) VALUES (?,?,?,?,?)",
        (thread_a, contract_id, run_id, "A", "desc"),
    )
    await db.execute(
        "INSERT INTO threads (id, contract_id, run_id, title, description) VALUES (?,?,?,?,?)",
        (thread_b, contract_id, run_id, "B", "desc"),
    )
    await db.execute(
        "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
        "VALUES (?,?,?,?,?,?)",
        (agent_id, "Bot", "d", "s", "openai", "gpt-4o"),
    )
    await db.commit()

    bb = Blackboard(db)
    await bb.post(run_id=run_id, thread_id=thread_a, author_id=agent_id,
                  content="Entry in A", entry_type="proposal", round=1)
    await bb.post(run_id=run_id, thread_id=thread_b, author_id=agent_id,
                  content="Entry in B", entry_type="proposal", round=1)

    results_a = await bb.read(run_id=run_id, query="entry", thread_id=thread_a)
    results_b = await bb.read(run_id=run_id, query="entry", thread_id=thread_b)
    results_all = await bb.read(run_id=run_id, query="entry", thread_id=None)

    assert len(results_a) == 1
    assert results_a[0].content == "Entry in A"
    assert len(results_b) == 1
    assert results_b[0].content == "Entry in B"
    assert len(results_all) == 2


async def test_read_does_not_return_invisible_entries(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=agent_id,
        content="Hidden", entry_type="proposal", round=1,
    )
    # Manually soft-delete
    await db.execute(
        "UPDATE draft_entries SET is_visible=0 WHERE id=?", (entry_id,)
    )
    await db.commit()

    results = await bb.read(run_id=run_id, query="hidden", thread_id=thread_id)
    assert len(results) == 0
```

- [ ] **Step 2: Run to verify all four tests fail**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/api
uv run pytest tests/test_blackboard.py -v
```

Expected: 4 errors (ImportError — `api.swarm.blackboard` doesn't exist yet).

- [ ] **Step 3: Create api/swarm/blackboard.py with post() and read()**

```python
"""Blackboard — shared append-only coordination substrate for the ECSAS swarm."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from api.swarm.schemas import (
    ConfirmedEntrySchema,
    DraftEntrySchema,
)

_ZERO_EMBEDDING = json.dumps([0.0] * 1536)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Blackboard:
    """Encapsulates all blackboard read/write operations for one DB connection."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ── write ─────────────────────────────────────────────────────────────

    async def post(
        self,
        *,
        run_id: str,
        thread_id: str,
        author_id: str,
        content: str,
        entry_type: str,
        round: int,
        reply_to: str | None = None,
        mention_agents: list[str] | None = None,
    ) -> str:
        """Insert a draft entry. Returns the new entry_id."""
        entry_id = str(uuid.uuid4())
        await self._db.execute(
            """
            INSERT INTO draft_entries
                (id, run_id, thread_id, round, author_id, entry_type,
                 content, content_embedding, reply_to, mention_agents,
                 is_visible, last_cited_round)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
            """,
            (
                entry_id, run_id, thread_id, round, author_id, entry_type,
                content, _ZERO_EMBEDDING, reply_to,
                json.dumps(mention_agents or []),
            ),
        )
        await self._db.commit()
        return entry_id

    # ── read ──────────────────────────────────────────────────────────────

    async def read(
        self,
        *,
        run_id: str,
        query: str,
        thread_id: str | None,
        k: int = 10,
        agent_id: str | None = None,
    ) -> list[DraftEntrySchema]:
        """Return top-k visible entries, sorted by citation_count DESC.

        Entries that mention agent_id are pinned to position 0.
        When all embeddings are zero (stub mode), ranking is by
        citation_count DESC, created_at ASC.
        """
        thread_clause = "AND de.thread_id = ?" if thread_id is not None else ""
        base_params: list[Any] = [run_id, run_id]
        if thread_id is not None:
            base_params.append(thread_id)

        async with self._db.execute(
            f"""
            SELECT de.id, de.run_id, de.thread_id, de.round, de.author_id,
                   COALESCE(a.name, de.author_id) AS author_name,
                   de.entry_type, de.content,
                   de.reply_to, de.mention_agents, de.is_visible,
                   de.deleted_at, de.last_cited_round, de.created_at,
                   COALESCE(cc.cnt, 0) AS citation_count
            FROM draft_entries de
            LEFT JOIN agents a ON a.id = de.author_id
            LEFT JOIN (
                SELECT cited_entry_id, COUNT(*) AS cnt
                FROM   citations
                WHERE  run_id = ?
                GROUP  BY cited_entry_id
            ) cc ON cc.cited_entry_id = de.id
            WHERE de.run_id = ? AND de.is_visible = 1
            {thread_clause}
            ORDER BY citation_count DESC, de.created_at ASC
            """,
            base_params,
        ) as cur:
            rows = await cur.fetchall()

        entries: list[DraftEntrySchema] = []
        pinned: list[DraftEntrySchema] = []
        for row in rows:
            d = dict(row)
            d["mention_agents"] = json.loads(d["mention_agents"] or "[]")
            d["children"] = []
            entry = DraftEntrySchema(**d)
            if agent_id and agent_id in entry.mention_agents:
                pinned.append(entry)
            else:
                entries.append(entry)

        return (pinned + entries)[:k]
```

- [ ] **Step 4: Run the tests**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/api
uv run pytest tests/test_blackboard.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add api/swarm/blackboard.py api/tests/test_blackboard.py
git commit -m "feat(blackboard): implement Blackboard.post and Blackboard.read"
```

---

## Task 5: Blackboard.cite + Blackboard.vote + Blackboard.get_confirmed

**Files:**
- Modify: `api/swarm/blackboard.py`
- Modify: `api/tests/test_blackboard.py`

- [ ] **Step 1: Write failing tests**

Append to `api/tests/test_blackboard.py`:

```python
async def test_cite_increments_citation_count(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a = str(uuid.uuid4())
    agent_b = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_a)
    await db.execute(
        "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
        "VALUES (?,?,?,?,?,?)",
        (agent_b, "AgentB", "d", "s", "openai", "gpt-4o"),
    )
    await db.commit()

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=agent_a,
        content="Proposal", entry_type="proposal", round=1,
    )
    result = await bb.cite(
        run_id=run_id, citing_agent_id=agent_b, entry_ids=[entry_id], round=2
    )

    assert result["cited"] == 1
    assert result["skipped_self"] == 0

    entries = await bb.read(run_id=run_id, query="", thread_id=thread_id)
    assert entries[0].citation_count == 1


async def test_cite_skips_self_citation(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=agent_id,
        content="Mine", entry_type="proposal", round=1,
    )
    result = await bb.cite(
        run_id=run_id, citing_agent_id=agent_id, entry_ids=[entry_id], round=2
    )

    assert result["cited"] == 0
    assert result["skipped_self"] == 1


async def test_vote_inserts_record(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a = str(uuid.uuid4())
    agent_b = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_a)
    await db.execute(
        "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
        "VALUES (?,?,?,?,?,?)",
        (agent_b, "B", "d", "s", "openai", "gpt-4o"),
    )
    await db.commit()

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=agent_a,
        content="Proposal", entry_type="proposal", round=1,
    )
    result = await bb.vote(
        run_id=run_id, voter_id=agent_b, entry_id=entry_id, thread_id=thread_id
    )

    assert result["ok"] is True
    async with db.execute("SELECT COUNT(*) FROM votes WHERE run_id=?", (run_id,)) as cur:
        row = await cur.fetchone()
    assert row[0] == 1


async def test_get_confirmed_returns_entries(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    await db.execute(
        """
        INSERT INTO confirmed_entries
            (id, run_id, thread_id, content, entry_type, round_confirmed)
        VALUES (?, ?, ?, ?, 'anchor', 1)
        """,
        (str(uuid.uuid4()), run_id, thread_id, "Contract anchor"),
    )
    await db.commit()

    bb = Blackboard(db)
    confirmed = await bb.get_confirmed(run_id=run_id, thread_id=thread_id)

    assert len(confirmed) == 1
    assert confirmed[0].content == "Contract anchor"
    assert confirmed[0].entry_type == "anchor"
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/api
uv run pytest tests/test_blackboard.py::test_cite_increments_citation_count tests/test_blackboard.py::test_cite_skips_self_citation tests/test_blackboard.py::test_vote_inserts_record tests/test_blackboard.py::test_get_confirmed_returns_entries -v
```

Expected: 4 errors (AttributeError — methods don't exist yet).

- [ ] **Step 3: Add cite(), vote(), get_confirmed() to api/swarm/blackboard.py**

Append inside the `Blackboard` class, after the `read()` method:

```python
    async def cite(
        self,
        *,
        run_id: str,
        citing_agent_id: str,
        entry_ids: list[str],
        round: int,
        citing_entry_id: str | None = None,
    ) -> dict[str, int]:
        """Record citation endorsements. Skips self-citations server-side."""
        cited = 0
        skipped_self = 0
        for entry_id in entry_ids:
            # Resolve author of cited entry
            async with self._db.execute(
                "SELECT author_id FROM draft_entries WHERE id=?", (entry_id,)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                continue
            if row["author_id"] == citing_agent_id:
                skipped_self += 1
                continue
            try:
                await self._db.execute(
                    """
                    INSERT INTO citations
                        (id, run_id, citing_agent_id, cited_entry_id,
                         citing_entry_id, round)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), run_id, citing_agent_id,
                     entry_id, citing_entry_id, round),
                )
                await self._db.execute(
                    "UPDATE draft_entries SET last_cited_round=? WHERE id=?",
                    (round, entry_id),
                )
                cited += 1
            except Exception:
                # UNIQUE constraint: agent already cited this entry this round
                pass
        await self._db.commit()
        return {"cited": cited, "skipped_self": skipped_self}

    async def vote(
        self,
        *,
        run_id: str,
        voter_id: str,
        entry_id: str,
        thread_id: str,
    ) -> dict[str, bool]:
        """Record a cold-start vote. One vote per agent per entry (UNIQUE)."""
        try:
            await self._db.execute(
                """
                INSERT INTO votes
                    (id, run_id, voter_agent_id, voted_entry_id, thread_id, round)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (str(uuid.uuid4()), run_id, voter_id, entry_id, thread_id),
            )
            await self._db.commit()
            return {"ok": True}
        except Exception:
            return {"ok": False}

    async def get_confirmed(
        self,
        *,
        run_id: str,
        thread_id: str | None = None,
    ) -> list[ConfirmedEntrySchema]:
        """Return confirmed entries (anchors + promoted findings)."""
        thread_clause = "AND thread_id = ?" if thread_id is not None else ""
        params: list[Any] = [run_id]
        if thread_id is not None:
            params.append(thread_id)

        async with self._db.execute(
            f"""
            SELECT id, run_id, thread_id, source_draft_id, content,
                   entry_type, citation_count, round_confirmed, created_at
            FROM confirmed_entries
            WHERE run_id = ? {thread_clause}
            ORDER BY round_confirmed ASC, created_at ASC
            """,
            params,
        ) as cur:
            rows = await cur.fetchall()

        return [ConfirmedEntrySchema(**dict(row)) for row in rows]
```

- [ ] **Step 4: Run the tests**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/api
uv run pytest tests/test_blackboard.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add api/swarm/blackboard.py api/tests/test_blackboard.py
git commit -m "feat(blackboard): add cite, vote, and get_confirmed methods"
```

---

## Task 6: Blackboard.check_promotions + Blackboard.soft_delete_stale

**Files:**
- Modify: `api/swarm/blackboard.py`
- Modify: `api/tests/test_blackboard.py`

- [ ] **Step 1: Write failing tests**

Append to `api/tests/test_blackboard.py`:

```python
async def _seed_two_agents(db, run_id: str, thread_id: str) -> tuple[str, str]:
    """Seed a run + thread + two agents. Returns (agent_a_id, agent_b_id)."""
    contract_id = str(uuid.uuid4())
    agent_a = str(uuid.uuid4())
    agent_b = str(uuid.uuid4())
    await db.execute("INSERT INTO swarm_runs (id) VALUES (?)", (run_id,))
    await db.execute(
        "INSERT INTO contracts (id, run_id, original_prompt, task_type) VALUES (?,?,?,?)",
        (contract_id, run_id, "p", "t"),
    )
    await db.execute(
        "INSERT INTO threads (id, contract_id, run_id, title, description) VALUES (?,?,?,?,?)",
        (thread_id, contract_id, run_id, "T", "desc"),
    )
    for aid, name in [(agent_a, "A"), (agent_b, "B")]:
        await db.execute(
            "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
            "VALUES (?,?,?,?,?,?)",
            (aid, name, "d", "s", "openai", "gpt-4o"),
        )
    await db.commit()
    return agent_a, agent_b


async def test_check_promotions_promotes_entry_with_enough_citations(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=agent_a,
        content="Promotion candidate", entry_type="proposal", round=1,
    )
    # M = max(1, 2 // 3 + 1) = 1 — one distinct non-self citation is enough
    await bb.cite(run_id=run_id, citing_agent_id=agent_b,
                  entry_ids=[entry_id], round=2)

    promoted = await bb.check_promotions(run_id=run_id, current_round=2)

    assert len(promoted) == 1
    assert promoted[0].source_draft_id == entry_id

    confirmed = await bb.get_confirmed(run_id=run_id)
    assert len(confirmed) == 1


async def test_check_promotions_does_not_double_promote(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=agent_a,
        content="Already promoted", entry_type="proposal", round=1,
    )
    await bb.cite(run_id=run_id, citing_agent_id=agent_b,
                  entry_ids=[entry_id], round=2)
    await bb.check_promotions(run_id=run_id, current_round=2)
    promoted_again = await bb.check_promotions(run_id=run_id, current_round=3)

    assert len(promoted_again) == 0


async def test_soft_delete_stale_entries(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, _ = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    # Post in round 2 (not round 1, so not exempt from deletion)
    entry_id = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=agent_a,
        content="Stale entry", entry_type="reply", round=2,
    )
    # decay_rounds=3, current_round=5: rounds_since_citation = 5-0 = 5 >= 3
    deleted = await bb.soft_delete_stale(
        run_id=run_id, current_round=5, decay_rounds=3
    )

    assert deleted == 1
    entries = await bb.read(run_id=run_id, query="stale", thread_id=thread_id)
    assert len(entries) == 0


async def test_soft_delete_exempts_round_1_entries(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, _ = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=agent_a,
        content="Round 1 entry", entry_type="proposal", round=1,
    )
    # current_round=1: round-1 entries are exempt
    deleted = await bb.soft_delete_stale(
        run_id=run_id, current_round=1, decay_rounds=3
    )

    assert deleted == 0
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/api
uv run pytest tests/test_blackboard.py::test_check_promotions_promotes_entry_with_enough_citations tests/test_blackboard.py::test_check_promotions_does_not_double_promote tests/test_blackboard.py::test_soft_delete_stale_entries tests/test_blackboard.py::test_soft_delete_exempts_round_1_entries -v
```

Expected: 4 errors (AttributeError — methods don't exist yet).

- [ ] **Step 3: Add check_promotions() and soft_delete_stale() to api/swarm/blackboard.py**

Append inside the `Blackboard` class, after `get_confirmed()`:

```python
    async def check_promotions(
        self,
        *,
        run_id: str,
        current_round: int,
    ) -> list[ConfirmedEntrySchema]:
        """Promote draft entries that have reached the citation threshold M.

        M = max(1, n_distinct_posting_agents // 3 + 1) per thread.
        Already-promoted entries are skipped.
        Returns the list of newly promoted ConfirmedEntry objects.
        """
        # Find entries already promoted (to avoid double-promotion)
        async with self._db.execute(
            "SELECT source_draft_id FROM confirmed_entries "
            "WHERE run_id=? AND source_draft_id IS NOT NULL",
            (run_id,),
        ) as cur:
            rows = await cur.fetchall()
        already_promoted = {row[0] for row in rows}

        # Count distinct posting agents per thread (proxy for n_participants)
        async with self._db.execute(
            "SELECT thread_id, COUNT(DISTINCT author_id) AS n "
            "FROM draft_entries WHERE run_id=? GROUP BY thread_id",
            (run_id,),
        ) as cur:
            rows = await cur.fetchall()
        participants_by_thread: dict[str, int] = {row[0]: row[1] for row in rows}

        # Find visible draft entries with their distinct non-self citation counts
        async with self._db.execute(
            """
            SELECT de.id, de.thread_id, de.author_id, de.content,
                   de.entry_type, de.round, de.created_at,
                   COUNT(DISTINCT c.citing_agent_id) AS distinct_citers
            FROM draft_entries de
            JOIN citations c
                ON c.cited_entry_id = de.id
               AND c.citing_agent_id != de.author_id
               AND c.run_id = de.run_id
            WHERE de.run_id = ? AND de.is_visible = 1
            GROUP BY de.id
            """,
            (run_id,),
        ) as cur:
            rows = await cur.fetchall()

        newly_promoted: list[ConfirmedEntrySchema] = []
        for row in rows:
            entry_id = row["id"]
            if entry_id in already_promoted:
                continue
            n = participants_by_thread.get(row["thread_id"], 1)
            threshold = max(1, n // 3 + 1)
            if row["distinct_citers"] >= threshold:
                confirmed_id = str(uuid.uuid4())
                await self._db.execute(
                    """
                    INSERT INTO confirmed_entries
                        (id, run_id, thread_id, source_draft_id, content,
                         entry_type, citation_count, round_confirmed)
                    VALUES (?, ?, ?, ?, ?, 'finding', ?, ?)
                    """,
                    (
                        confirmed_id, run_id, row["thread_id"], entry_id,
                        row["content"], row["distinct_citers"], current_round,
                    ),
                )
                async with self._db.execute(
                    "SELECT * FROM confirmed_entries WHERE id=?", (confirmed_id,)
                ) as cur2:
                    confirmed_row = await cur2.fetchone()
                newly_promoted.append(ConfirmedEntrySchema(**dict(confirmed_row)))

        if newly_promoted:
            await self._db.commit()
        return newly_promoted

    async def soft_delete_stale(
        self,
        *,
        run_id: str,
        current_round: int,
        decay_rounds: int = 3,
    ) -> int:
        """Soft-delete entries not cited for decay_rounds consecutive rounds.

        Round-1 entries are exempt when current_round < 2.
        Returns the count of entries deleted.
        """
        exempt_round1 = current_round < 2

        async with self._db.execute(
            """
            UPDATE draft_entries
            SET is_visible = 0, deleted_at = CURRENT_TIMESTAMP
            WHERE run_id = ?
              AND is_visible = 1
              AND NOT (round = 1 AND ?)
              AND (? - COALESCE(last_cited_round, 0)) >= ?
            RETURNING id
            """,
            (run_id, 1 if exempt_round1 else 0, current_round, decay_rounds),
        ) as cur:
            rows = await cur.fetchall()
        await self._db.commit()
        return len(rows)
```

**Note:** SQLite's `RETURNING` clause requires SQLite ≥ 3.35 (Python 3.10+ ships this). If your SQLite is older, replace the `RETURNING` form with:
```python
        await self._db.execute(
            """
            UPDATE draft_entries
            SET is_visible = 0, deleted_at = CURRENT_TIMESTAMP
            WHERE run_id = ?
              AND is_visible = 1
              AND NOT (round = 1 AND ?)
              AND (? - COALESCE(last_cited_round, 0)) >= ?
            """,
            (run_id, 1 if exempt_round1 else 0, current_round, decay_rounds),
        )
        await self._db.commit()
        async with self._db.execute(
            "SELECT changes()"
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0
```

- [ ] **Step 4: Run all blackboard tests**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/api
uv run pytest tests/test_blackboard.py -v
```

Expected: all 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add api/swarm/blackboard.py api/tests/test_blackboard.py
git commit -m "feat(blackboard): add check_promotions and soft_delete_stale"
```

---

## Task 7: Blackboard Tools + Stub Auction Tools

**Files:**
- Create: `api/tools/builtin/blackboard_tools.py`
- Modify: `api/tools/registry.py`

- [ ] **Step 1: Create api/tools/builtin/blackboard_tools.py**

```python
"""ECSAS blackboard tools — registered alongside existing tools in the registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from api.swarm.blackboard import Blackboard
from api.tools.base import Tool

if TYPE_CHECKING:
    pass


# ── Input models ─────────────────────────────────────────────────────────────


class ReadBlackboardInput(BaseModel):
    query: str = Field(description="Natural language search query.")
    thread_id: str | None = Field(
        default=None,
        description="Thread to search. None searches across all threads.",
    )
    k: int = Field(default=10, ge=1, le=30, description="Max entries to return.")


class PostToBlackboardInput(BaseModel):
    content: str = Field(description="Full text of the post.")
    entry_type: Literal["proposal", "reply"] = Field(
        description="'proposal' for round-1 initial answers; 'reply' for later rounds."
    )
    thread_id: str = Field(description="Thread this post belongs to.")
    reply_to: str | None = Field(
        default=None, description="entry_id of parent post (null for top-level)."
    )
    mention_agents: list[str] = Field(
        default_factory=list,
        description="Agent IDs to notify. They see this entry pinned at position 0.",
    )


class CiteInput(BaseModel):
    entry_ids: list[str] = Field(
        description="IDs of entries you are building on or agreeing with."
    )


class VoteInput(BaseModel):
    entry_id: str = Field(description="ID of a round-1 proposal to endorse.")


class GetConfirmedInput(BaseModel):
    thread_id: str | None = Field(
        default=None,
        description="Filter confirmed entries by thread. None returns all threads.",
    )


# ── Tool classes ──────────────────────────────────────────────────────────────


class ReadBlackboardTool(Tool):
    name = "read_blackboard"
    description = (
        "Query the blackboard for relevant entries. "
        "Returns top-k entries sorted by relevance and citation count. "
        "Entries mentioning you are always at position 0."
    )
    input_model = ReadBlackboardInput

    async def execute(
        self, validated_input: ReadBlackboardInput, context: dict[str, Any] | None = None
    ) -> str:
        ctx = context or {}
        db = ctx["db"]
        run_id: str = ctx["run_id"]
        agent_id: str | None = ctx.get("agent_id")

        bb = Blackboard(db)
        entries = await bb.read(
            run_id=run_id,
            query=validated_input.query,
            thread_id=validated_input.thread_id,
            k=validated_input.k,
            agent_id=agent_id,
        )
        if not entries:
            return "No visible entries found."

        lines = []
        for e in entries:
            lines.append(
                f"[{e.id[:8]}] {e.author_name} · Round {e.round} · {e.entry_type}"
                f" · ♡{e.citation_count}\n{e.content[:300]}"
            )
        return "\n\n---\n\n".join(lines)


class PostToBlackboardTool(Tool):
    name = "post_to_blackboard"
    description = (
        "Write a proposal (round 1) or reply (rounds 2+) to the blackboard. "
        "Returns the new entry ID."
    )
    input_model = PostToBlackboardInput

    async def execute(
        self, validated_input: PostToBlackboardInput, context: dict[str, Any] | None = None
    ) -> str:
        ctx = context or {}
        db = ctx["db"]
        run_id: str = ctx["run_id"]
        author_id: str = ctx["agent_id"]
        round_: int = ctx.get("round", 1)

        bb = Blackboard(db)
        entry_id = await bb.post(
            run_id=run_id,
            thread_id=validated_input.thread_id,
            author_id=author_id,
            content=validated_input.content,
            entry_type=validated_input.entry_type,
            round=round_,
            reply_to=validated_input.reply_to,
            mention_agents=validated_input.mention_agents,
        )
        return f'{{"entry_id": "{entry_id}"}}'


class CiteTool(Tool):
    name = "cite"
    description = (
        "Endorse entries you are building on or agree with. "
        "ONLY call for entries you genuinely support — "
        "express disagreement through reply content, not citation."
    )
    input_model = CiteInput

    async def execute(
        self, validated_input: CiteInput, context: dict[str, Any] | None = None
    ) -> str:
        ctx = context or {}
        db = ctx["db"]
        run_id: str = ctx["run_id"]
        citing_agent_id: str = ctx["agent_id"]
        round_: int = ctx.get("round", 2)
        citing_entry_id: str | None = ctx.get("citing_entry_id")

        bb = Blackboard(db)
        result = await bb.cite(
            run_id=run_id,
            citing_agent_id=citing_agent_id,
            entry_ids=validated_input.entry_ids,
            round=round_,
            citing_entry_id=citing_entry_id,
        )
        return f'{{"cited": {result["cited"]}, "skipped_self": {result["skipped_self"]}}}'


class VoteTool(Tool):
    name = "vote"
    description = (
        "Endorse a round-1 proposal during the cold-start vote sub-round. "
        "Use only between rounds 1 and 2. "
        "Votes initialize confidence scores — they are NOT promotion signals."
    )
    input_model = VoteInput

    async def execute(
        self, validated_input: VoteInput, context: dict[str, Any] | None = None
    ) -> str:
        ctx = context or {}
        db = ctx["db"]
        run_id: str = ctx["run_id"]
        voter_id: str = ctx["agent_id"]
        thread_id: str = ctx["thread_id"]

        bb = Blackboard(db)
        result = await bb.vote(
            run_id=run_id,
            voter_id=voter_id,
            entry_id=validated_input.entry_id,
            thread_id=thread_id,
        )
        return f'{{"ok": {str(result["ok"]).lower()}}}'


class GetConfirmedTool(Tool):
    name = "get_confirmed"
    description = (
        "Retrieve the Confirmed layer: permanent anchors and promoted findings. "
        "Use at the start of each round to orient yourself on ratified knowledge."
    )
    input_model = GetConfirmedInput

    async def execute(
        self, validated_input: GetConfirmedInput, context: dict[str, Any] | None = None
    ) -> str:
        ctx = context or {}
        db = ctx["db"]
        run_id: str = ctx["run_id"]

        bb = Blackboard(db)
        entries = await bb.get_confirmed(
            run_id=run_id, thread_id=validated_input.thread_id
        )
        if not entries:
            return "No confirmed entries yet."

        lines = []
        for e in entries:
            badge = "📌" if e.entry_type == "anchor" else "✅"
            lines.append(f"{badge} [{e.id[:8]}] Round {e.round_confirmed} · ♡{e.citation_count}\n{e.content[:300]}")
        return "\n\n---\n\n".join(lines)


# ── Stub auction tools (schema-complete; execute deferred to Phase 2) ────────


class SubmitBidInput(BaseModel):
    justification: str = Field(description="Your reasoning for participating.")
    thread_id: str | None = Field(
        default=None,
        description="Thread to bid on. None for contract-level bid.",
    )


class AbstainInput(BaseModel):
    reason: str = Field(description="Why you are opting out.")
    thread_id: str | None = Field(
        default=None,
        description="Thread to abstain from. None for full contract abstention.",
    )


class SubmitBidTool(Tool):
    name = "submit_bid"
    description = "Commit to taking a contract or thread. Call during the auction phase."
    input_model = SubmitBidInput

    async def execute(
        self, validated_input: SubmitBidInput, context: dict[str, Any] | None = None
    ) -> str:
        return '{"ok": true, "preliminary_score": 0.0}'


class AbstainTool(Tool):
    name = "abstain"
    description = "Opt out of a contract or thread. Call during the auction phase."
    input_model = AbstainInput

    async def execute(
        self, validated_input: AbstainInput, context: dict[str, Any] | None = None
    ) -> str:
        return '{"ok": true}'
```

- [ ] **Step 2: Register all tools in api/tools/registry.py**

Add after the `register(FilesTool())` line:

```python
from api.tools.builtin.blackboard_tools import (
    AbstainTool,
    CiteTool,
    GetConfirmedTool,
    PostToBlackboardTool,
    ReadBlackboardTool,
    SubmitBidTool,
    VoteTool,
)

register(ReadBlackboardTool())
register(PostToBlackboardTool())
register(CiteTool())
register(VoteTool())
register(GetConfirmedTool())
register(SubmitBidTool())
register(AbstainTool())
```

- [ ] **Step 3: Verify tools import and register**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/api
uv run python -c "
from api.tools.registry import list_tools
tools = list_tools()
names = [t['name'] for t in tools]
expected = ['files', 'read_blackboard', 'post_to_blackboard', 'cite', 'vote', 'get_confirmed', 'submit_bid', 'abstain']
missing = [n for n in expected if n not in names]
print('Missing:', missing if missing else 'none')
print('All tools:', names)
"
```

Expected: `Missing: none` and all 8 tools listed.

- [ ] **Step 4: Run full test suite**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/api
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add api/tools/builtin/blackboard_tools.py api/tools/registry.py
git commit -m "feat(tools): add blackboard tools and stub auction tools to registry"
```

---

## Task 8: Simulation REST Endpoints

**Files:**
- Create: `api/routes/simulation.py`
- Modify: `api/routes/__init__.py`
- Modify: `api/index.py`
- Create: `api/tests/test_simulation.py`

- [ ] **Step 1: Write failing tests**

Create `api/tests/test_simulation.py`:

```python
"""Tests for the simulation REST endpoints."""

from __future__ import annotations

import os

import pytest
from httpx import AsyncClient

os.environ.setdefault("DB_PATH", ":memory:")
os.environ.setdefault("DEBUG", "true")


async def _create_agent(client: AsyncClient, name: str = "Alpha") -> str:
    resp = await client.post(
        "/api/agents/",
        json={
            "name": name,
            "description": "Test agent",
            "system_prompt": "You are a test agent.",
            "provider": "openai",
            "model": "gpt-4o",
            "tools": [],
            "connections": [],
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_get_blackboard_unknown_run_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/api/simulation/nonexistent-run-id/blackboard")
    assert resp.status_code == 404


async def test_seed_creates_run_and_returns_ids(client: AsyncClient) -> None:
    agent_id = await _create_agent(client)
    resp = await client.post(
        "/api/simulation/seed",
        json={"prompt": "Test prompt", "agent_ids": [agent_id]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert "thread_id" in data


async def test_get_blackboard_after_seed_returns_entries(client: AsyncClient) -> None:
    agent_id = await _create_agent(client)
    seed_resp = await client.post(
        "/api/simulation/seed",
        json={"prompt": "Analyze this contract", "agent_ids": [agent_id]},
    )
    run_id = seed_resp.json()["run_id"]
    thread_id = seed_resp.json()["thread_id"]

    resp = await client.get(f"/api/simulation/{run_id}/blackboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "confirmed" in data
    assert "draft" in data
    assert "threads" in data
    assert len(data["confirmed"]) >= 1  # anchor entry
    assert len(data["threads"]) == 1
    assert data["threads"][0]["id"] == thread_id


async def test_get_blackboard_thread_filter(client: AsyncClient) -> None:
    agent_id = await _create_agent(client)
    seed_resp = await client.post(
        "/api/simulation/seed",
        json={"prompt": "Test", "agent_ids": [agent_id]},
    )
    run_id = seed_resp.json()["run_id"]
    thread_id = seed_resp.json()["thread_id"]

    resp = await client.get(
        f"/api/simulation/{run_id}/blackboard",
        params={"thread_id": thread_id, "layer": "confirmed"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert all(e["thread_id"] == thread_id for e in data["confirmed"])
    assert data["draft"] == []


async def test_seed_disabled_without_debug_flag(client: AsyncClient, monkeypatch) -> None:
    monkeypatch.delenv("DEBUG", raising=False)
    resp = await client.post(
        "/api/simulation/seed",
        json={"prompt": "Test", "agent_ids": []},
    )
    assert resp.status_code == 403
```

- [ ] **Step 2: Run to confirm all tests fail**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/api
uv run pytest tests/test_simulation.py -v
```

Expected: 5 failures (404 on all — router not mounted yet).

- [ ] **Step 3: Create api/routes/simulation.py**

```python
"""Simulation routes — blackboard read endpoint and dev seed endpoint."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.db import get_db
from api.swarm.blackboard import Blackboard
from api.swarm.schemas import (
    BlackboardResponse,
    ConfirmedEntrySchema,
    DraftEntrySchema,
    SeedRequest,
    SeedResponse,
    ThreadSchema,
)

router = APIRouter(prefix="/api/simulation", tags=["Simulation"])

DBDep = Annotated[aiosqlite.Connection, Depends(get_db)]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_draft_tree(entries: list[DraftEntrySchema]) -> list[DraftEntrySchema]:
    """Nest draft entries: populate children lists, return root entries only."""
    by_id = {e.id: e for e in entries}
    roots: list[DraftEntrySchema] = []
    for entry in entries:
        if entry.reply_to is None or entry.reply_to not in by_id:
            roots.append(entry)
        else:
            by_id[entry.reply_to].children.append(entry)
    return roots


@router.get(
    "/{run_id}/blackboard",
    response_model=BlackboardResponse,
    summary="Get blackboard state for a run",
)
async def get_blackboard(
    run_id: str,
    db: DBDep,
    thread_id: str | None = Query(default=None),
    layer: Literal["draft", "confirmed", "both"] = Query(default="both"),
    include_deleted: bool = Query(default=False),
) -> BlackboardResponse:
    # Verify run exists
    async with db.execute(
        "SELECT id FROM swarm_runs WHERE id=?", (run_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")

    # Fetch threads
    thread_clause = "AND id=?" if thread_id else ""
    thread_params = [run_id] + ([thread_id] if thread_id else [])
    async with db.execute(
        f"SELECT * FROM threads WHERE run_id=? {thread_clause} ORDER BY created_at ASC",
        thread_params,
    ) as cur:
        thread_rows = await cur.fetchall()
    threads = [ThreadSchema(**dict(r)) for r in thread_rows]

    # Fetch confirmed entries
    confirmed: list[ConfirmedEntrySchema] = []
    if layer in ("confirmed", "both"):
        bb = Blackboard(db)
        confirmed = await bb.get_confirmed(run_id=run_id, thread_id=thread_id)

    # Fetch draft entries
    draft: list[DraftEntrySchema] = []
    if layer in ("draft", "both"):
        vis_clause = "" if include_deleted else "AND de.is_visible=1"
        t_clause = "AND de.thread_id=?" if thread_id else ""
        params: list = [run_id, run_id]
        if thread_id:
            params.append(thread_id)

        async with db.execute(
            f"""
            SELECT de.id, de.run_id, de.thread_id, de.round, de.author_id,
                   COALESCE(a.name, de.author_id) AS author_name,
                   de.entry_type, de.content,
                   de.reply_to, de.mention_agents, de.is_visible,
                   de.deleted_at, de.last_cited_round, de.created_at,
                   COALESCE(cc.cnt, 0) AS citation_count
            FROM draft_entries de
            LEFT JOIN agents a ON a.id = de.author_id
            LEFT JOIN (
                SELECT cited_entry_id, COUNT(*) AS cnt
                FROM citations WHERE run_id=?
                GROUP BY cited_entry_id
            ) cc ON cc.cited_entry_id = de.id
            WHERE de.run_id=? {vis_clause} {t_clause}
            ORDER BY de.round ASC, de.created_at ASC
            """,
            params,
        ) as cur:
            rows = await cur.fetchall()

        flat: list[DraftEntrySchema] = []
        for row in rows:
            d = dict(row)
            d["mention_agents"] = json.loads(d["mention_agents"] or "[]")
            d["children"] = []
            flat.append(DraftEntrySchema(**d))

        draft = _build_draft_tree(flat)

    return BlackboardResponse(threads=threads, confirmed=confirmed, draft=draft)


@router.post(
    "/seed",
    response_model=SeedResponse,
    summary="Seed test blackboard data (DEBUG only)",
)
async def seed_blackboard(body: SeedRequest, db: DBDep) -> SeedResponse:
    if os.getenv("DEBUG", "").lower() not in ("true", "1", "yes"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="seed endpoint disabled in production",
        )

    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    now = _now_iso()

    await db.execute(
        "INSERT INTO swarm_runs (id, status, mode, created_at) VALUES (?,?,?,?)",
        (run_id, "running", "swarm", now),
    )
    await db.execute(
        "INSERT INTO contracts "
        "(id, run_id, original_prompt, task_type, task_nature, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (contract_id, run_id, body.prompt, "analysis", "single", now),
    )
    await db.execute(
        "INSERT INTO threads "
        "(id, contract_id, run_id, title, description, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (thread_id, contract_id, run_id, "Main Thread", body.prompt, now),
    )

    # Confirmed anchor
    await db.execute(
        "INSERT INTO confirmed_entries "
        "(id, run_id, thread_id, content, entry_type, round_confirmed, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            str(uuid.uuid4()), run_id, thread_id,
            f"[ANCHOR] Contract: {body.prompt}", "anchor", 0, now,
        ),
    )

    # Draft proposals from each agent
    bb = Blackboard(db)
    for agent_id in body.agent_ids[:5]:  # cap at 5 agents
        async with db.execute(
            "SELECT id FROM agents WHERE id=?", (agent_id,)
        ) as cur:
            if await cur.fetchone() is None:
                continue
        await bb.post(
            run_id=run_id,
            thread_id=thread_id,
            author_id=agent_id,
            content=f"Seed proposal from agent {agent_id[:8]}. "
                    f"Analyzing: {body.prompt}",
            entry_type="proposal",
            round=1,
        )

    await db.commit()
    return SeedResponse(run_id=run_id, thread_id=thread_id)
```

- [ ] **Step 4: Register the router in api/routes/__init__.py**

Replace the file contents with:

```python
"""Route registry — import all sub-routers here and expose them for ``index.py``."""

from api.routes.agents import router as agents_router
from api.routes.files import router as knowledge_files_router
from api.routes.simulation import router as simulation_router
from api.routes.test import router as test_router

__all__ = ["agents_router", "knowledge_files_router", "simulation_router", "test_router"]
```

- [ ] **Step 5: Mount the simulation router in api/index.py**

Add after the existing `app.include_router(test_router)` line:

```python
from api.routes import simulation_router

app.include_router(simulation_router)
```

- [ ] **Step 6: Run the simulation tests**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/api
uv run pytest tests/test_simulation.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 7: Run the full suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add api/routes/simulation.py api/routes/__init__.py api/index.py api/tests/test_simulation.py
git commit -m "feat(routes): add GET /blackboard and POST /seed simulation endpoints"
```

---

## Task 9: Frontend Types

**Files:**
- Modify: `app/lib/types.ts`

- [ ] **Step 1: Extend app/lib/types.ts with swarm types**

Append to the end of `app/lib/types.ts`:

```typescript
// ── ECSAS swarm types ─────────────────────────────────────────────────────

export type SwarmSimStepType =
  | SimStepType
  | "bid"
  | "abstain"
  | "bb-post"
  | "bb-cite"
  | "bb-vote"
  | "bb-promote"
  | "bb-delete"
  | "bb-mention"
  | "amendment"
  | "amendment-approved"
  | "amendment-rejected"
  | "convergence";

export interface ThreadInfo {
  id: string;
  contract_id: string;
  run_id: string;
  title: string;
  description: string;
  required_expertise: string[];
  complexity: "low" | "medium" | "high";
  created_at: string;
}

export interface ConfirmedEntry {
  id: string;
  run_id: string;
  thread_id: string;
  source_draft_id: string | null;
  content: string;
  entry_type: "anchor" | "finding" | "system";
  citation_count: number;
  round_confirmed: number;
  created_at: string;
}

export interface DraftEntry {
  id: string;
  run_id: string;
  thread_id: string;
  round: number;
  author_id: string;
  author_name: string;
  entry_type: "proposal" | "reply" | "vote" | "system";
  content: string;
  reply_to: string | null;
  mention_agents: string[];
  is_visible: boolean;
  deleted_at: string | null;
  last_cited_round: number;
  citation_count: number;
  created_at: string;
  children: DraftEntry[];
}

export interface BlackboardState {
  threads: ThreadInfo[];
  confirmed: ConfirmedEntry[];
  draft: DraftEntry[];
  loading: boolean;
  error: string | null;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/app
pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add app/lib/types.ts
git commit -m "feat(types): add ECSAS swarm types to frontend type definitions"
```

---

## Task 10: useBlackboard Hook

**Files:**
- Create: `app/hooks/useBlackboard.ts`

- [ ] **Step 1: Create app/hooks/useBlackboard.ts**

```typescript
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  BlackboardState,
  ConfirmedEntry,
  DraftEntry,
  SimStep,
  ThreadInfo,
} from "@/lib/types";

const EMPTY_STATE: BlackboardState = {
  threads: [],
  confirmed: [],
  draft: [],
  loading: false,
  error: null,
};

function applyBbPost(draft: DraftEntry[], event: SimStep): DraftEntry[] {
  // Parse the new entry from event.msg if possible; otherwise skip
  let newEntry: DraftEntry | null = null;
  try {
    newEntry = JSON.parse(event.msg) as DraftEntry;
  } catch {
    return draft;
  }
  if (newEntry.reply_to) {
    // Nest under parent
    return draft.map((root) => nestEntry(root, newEntry!));
  }
  return [newEntry, ...draft];
}

function nestEntry(root: DraftEntry, newEntry: DraftEntry): DraftEntry {
  if (root.id === newEntry.reply_to) {
    return { ...root, children: [...root.children, newEntry] };
  }
  return { ...root, children: root.children.map((c) => nestEntry(c, newEntry)) };
}

function applyBbPromote(
  draft: DraftEntry[],
  confirmed: ConfirmedEntry[],
  event: SimStep
): { draft: DraftEntry[]; confirmed: ConfirmedEntry[] } {
  let promoted: ConfirmedEntry | null = null;
  try {
    promoted = JSON.parse(event.msg) as ConfirmedEntry;
  } catch {
    return { draft, confirmed };
  }
  return {
    draft,
    confirmed: [...confirmed, promoted],
  };
}

function applyBbDelete(draft: DraftEntry[], event: SimStep): DraftEntry[] {
  const entryId: string = event.nodeId ?? "";
  if (!entryId) return draft;
  return markInvisible(draft, entryId);
}

function markInvisible(entries: DraftEntry[], id: string): DraftEntry[] {
  return entries.map((e) => {
    if (e.id === id) return { ...e, is_visible: false };
    return { ...e, children: markInvisible(e.children, id) };
  });
}

function applyBbCiteOrVote(draft: DraftEntry[], event: SimStep): DraftEntry[] {
  const entryId: string = event.nodeId ?? "";
  if (!entryId) return draft;
  return incrementCitation(draft, entryId);
}

function incrementCitation(entries: DraftEntry[], id: string): DraftEntry[] {
  return entries.map((e) => {
    if (e.id === id) return { ...e, citation_count: e.citation_count + 1 };
    return { ...e, children: incrementCitation(e.children, id) };
  });
}

export function useBlackboard(runId: string | null): {
  state: BlackboardState;
  dispatch: (event: SimStep) => void;
} {
  const [state, setState] = useState<BlackboardState>(EMPTY_STATE);

  useEffect(() => {
    if (!runId) {
      setState(EMPTY_STATE);
      return;
    }

    setState((s) => ({ ...s, loading: true, error: null }));

    fetch(`/api/simulation/${runId}/blackboard`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<{
          threads: ThreadInfo[];
          confirmed: ConfirmedEntry[];
          draft: DraftEntry[];
        }>;
      })
      .then((data) => {
        setState({
          threads: data.threads,
          confirmed: data.confirmed,
          draft: data.draft,
          loading: false,
          error: null,
        });
      })
      .catch((err: Error) => {
        setState((s) => ({ ...s, loading: false, error: err.message }));
      });
  }, [runId]);

  const dispatch = useCallback((event: SimStep) => {
    setState((prev) => {
      switch (event.type) {
        case "bb-post":
          return { ...prev, draft: applyBbPost(prev.draft, event) };
        case "bb-promote": {
          const result = applyBbPromote(prev.draft, prev.confirmed, event);
          return { ...prev, ...result };
        }
        case "bb-delete":
          return { ...prev, draft: applyBbDelete(prev.draft, event) };
        case "bb-cite":
        case "bb-vote":
          return { ...prev, draft: applyBbCiteOrVote(prev.draft, event) };
        default:
          return prev;
      }
    });
  }, []);

  return { state, dispatch };
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/app
pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add app/hooks/useBlackboard.ts
git commit -m "feat(hooks): add useBlackboard hook with REST-init and SSE-ready dispatch"
```

---

## Task 11: DraftEntry Component

**Files:**
- Create: `app/components/draft-entry.tsx`

- [ ] **Step 1: Create app/components/draft-entry.tsx**

```tsx
"use client";

import { DraftEntry } from "@/lib/types";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";

interface DraftEntryProps {
  entry: DraftEntry;
  depth?: number;
}

const MAX_DEPTH = 4;
const INDENT_PX = 16;

const ENTRY_TYPE_BADGE: Record<DraftEntry["entry_type"], string> = {
  proposal: "P",
  reply: "R",
  vote: "V",
  system: "⚙",
};

export function DraftEntryComponent({ entry, depth = 0 }: DraftEntryProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const indent = Math.min(depth, MAX_DEPTH) * INDENT_PX;
  const opacity = entry.is_visible ? 1 : 0.3;

  return (
    <div style={{ marginLeft: indent, opacity }}>
      <div
        style={{
          padding: "10px 12px",
          marginBottom: 4,
          borderRadius: 6,
          background: dark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.03)",
          borderLeft: depth > 0 ? `2px solid ${t.border ?? "rgba(139,26,47,0.3)"}` : "none",
        }}
      >
        {/* Header row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginBottom: 6,
            fontSize: 11,
            color: dark ? "rgba(255,255,255,0.5)" : "rgba(0,0,0,0.45)",
          }}
        >
          <span
            style={{
              background: "rgba(139,26,47,0.15)",
              color: "#8B1A2F",
              borderRadius: 3,
              padding: "1px 5px",
              fontWeight: 700,
              fontSize: 10,
            }}
          >
            {ENTRY_TYPE_BADGE[entry.entry_type]}
          </span>
          <span style={{ fontWeight: 600 }}>{entry.author_name}</span>
          <span>R{entry.round}</span>
          <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <span title="Citations">♡ {entry.citation_count}</span>
            {entry.children.length > 0 && (
              <span title="Replies">💬 {entry.children.length}</span>
            )}
          </span>
        </div>

        {/* Content */}
        <div style={{ fontSize: 13 }}>
          <MarkdownRenderer content={entry.content} />
        </div>

        {/* Entry ID (small, for debugging) */}
        <div
          style={{
            fontSize: 9,
            color: dark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.2)",
            marginTop: 4,
            fontFamily: "monospace",
          }}
        >
          {entry.id.slice(0, 8)}
        </div>
      </div>

      {/* Recursive children */}
      {entry.children.map((child) => (
        <DraftEntryComponent key={child.id} entry={child} depth={depth + 1} />
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/app
pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add app/components/draft-entry.tsx
git commit -m "feat(ui): add recursive DraftEntry component"
```

---

## Task 12: DraftSection + ConfirmedSection

**Files:**
- Create: `app/components/draft-section.tsx`
- Create: `app/components/confirmed-section.tsx`

- [ ] **Step 1: Create app/components/confirmed-section.tsx**

```tsx
"use client";

import { ConfirmedEntry } from "@/lib/types";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";

interface ConfirmedSectionProps {
  entries: ConfirmedEntry[];
}

const ENTRY_BADGE: Record<ConfirmedEntry["entry_type"], string> = {
  anchor: "📌",
  finding: "✅",
  system: "⚙",
};

export function ConfirmedSection({ entries }: ConfirmedSectionProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  if (entries.length === 0) return null;

  return (
    <div
      style={{
        borderBottom: `1px solid ${t.border ?? "rgba(139,26,47,0.2)"}`,
        paddingBottom: 12,
        marginBottom: 12,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.08em",
          color: dark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.4)",
          textTransform: "uppercase",
          marginBottom: 8,
        }}
      >
        Confirmed
      </div>

      {entries.map((entry) => (
        <div
          key={entry.id}
          style={{
            padding: "8px 10px",
            marginBottom: 4,
            borderRadius: 6,
            background: dark ? "rgba(255,215,0,0.06)" : "rgba(255,215,0,0.08)",
            borderLeft: "3px solid rgba(255,215,0,0.5)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              marginBottom: 4,
              fontSize: 11,
              color: dark ? "rgba(255,255,255,0.5)" : "rgba(0,0,0,0.45)",
            }}
          >
            <span>{ENTRY_BADGE[entry.entry_type]}</span>
            <span style={{ fontWeight: 600 }}>
              {entry.entry_type === "anchor" ? "ANCHOR" : `R${entry.round_confirmed}`}
            </span>
            {entry.citation_count > 0 && <span>♡ {entry.citation_count}</span>}
          </div>
          <div style={{ fontSize: 13 }}>
            <MarkdownRenderer content={entry.content} />
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create app/components/draft-section.tsx**

```tsx
"use client";

import { DraftEntry } from "@/lib/types";
import { DraftEntryComponent } from "@/components/draft-entry";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";

interface DraftSectionProps {
  entries: DraftEntry[];
}

export function DraftSection({ entries }: DraftSectionProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  if (entries.length === 0) {
    return (
      <div
        style={{
          fontSize: 13,
          color: dark ? "rgba(255,255,255,0.3)" : "rgba(0,0,0,0.3)",
          padding: "16px 0",
          textAlign: "center",
        }}
      >
        No draft entries yet.
      </div>
    );
  }

  return (
    <div>
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.08em",
          color: dark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.4)",
          textTransform: "uppercase",
          marginBottom: 8,
        }}
      >
        Draft
      </div>
      {entries.map((entry) => (
        <DraftEntryComponent key={entry.id} entry={entry} depth={0} />
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/app
pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add app/components/confirmed-section.tsx app/components/draft-section.tsx
git commit -m "feat(ui): add ConfirmedSection and DraftSection components"
```

---

## Task 13: BlackboardPanel

**Files:**
- Create: `app/components/blackboard-panel.tsx`

- [ ] **Step 1: Create app/components/blackboard-panel.tsx**

```tsx
"use client";

import { useState } from "react";
import { useBlackboard } from "@/hooks/useBlackboard";
import { ConfirmedSection } from "@/components/confirmed-section";
import { DraftSection } from "@/components/draft-section";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";

interface BlackboardPanelProps {
  runId: string | null;
  onRunIdChange: (id: string | null) => void;
}

export function BlackboardPanel({ runId, onRunIdChange }: BlackboardPanelProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const { state } = useBlackboard(runId);
  const [activeThreadIdx, setActiveThreadIdx] = useState(0);
  const [seeding, setSeeding] = useState(false);

  const activeThread = state.threads[activeThreadIdx] ?? null;
  const filteredConfirmed = activeThread
    ? state.confirmed.filter((e) => e.thread_id === activeThread.id)
    : state.confirmed;
  const filteredDraft = activeThread
    ? state.draft.filter((e) => e.thread_id === activeThread.id)
    : state.draft;

  const handleSeed = async () => {
    setSeeding(true);
    try {
      const res = await fetch("/api/simulation/seed", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: "Test blackboard seeding", agent_ids: [] }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { run_id: string; thread_id: string };
      onRunIdChange(data.run_id);
    } catch (err) {
      console.error("Seed failed:", err);
    } finally {
      setSeeding(false);
    }
  };

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        background: t.bg,
        borderLeft: `1px solid ${t.border ?? "rgba(139,26,47,0.2)"}`,
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "12px 16px",
          borderBottom: `1px solid ${t.border ?? "rgba(139,26,47,0.2)"}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexShrink: 0,
        }}
      >
        <span
          style={{
            fontWeight: 700,
            fontSize: 13,
            letterSpacing: "0.05em",
            color: "#8B1A2F",
          }}
        >
          BLACKBOARD
        </span>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {runId && (
            <span
              style={{
                fontFamily: "monospace",
                fontSize: 10,
                color: dark ? "rgba(255,255,255,0.35)" : "rgba(0,0,0,0.35)",
              }}
            >
              {runId.slice(0, 8)}
            </span>
          )}
          <button
            onClick={() => onRunIdChange(null)}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: dark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.4)",
              fontSize: 16,
              lineHeight: 1,
              padding: "2px 4px",
            }}
            title="Close blackboard"
          >
            ×
          </button>
        </div>
      </div>

      {/* No run — seed prompt */}
      {!runId && (
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 12,
            padding: 24,
          }}
        >
          <div
            style={{
              fontSize: 13,
              color: dark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.4)",
              textAlign: "center",
            }}
          >
            No active run. Seed test data to preview the blackboard.
          </div>
          <button
            onClick={handleSeed}
            disabled={seeding}
            style={{
              padding: "8px 20px",
              background: "#8B1A2F",
              color: "#fff",
              border: "none",
              borderRadius: 6,
              cursor: seeding ? "not-allowed" : "pointer",
              fontSize: 13,
              fontWeight: 600,
              opacity: seeding ? 0.6 : 1,
            }}
          >
            {seeding ? "Seeding…" : "Seed test data"}
          </button>
        </div>
      )}

      {/* Loading state */}
      {runId && state.loading && (
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: dark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.4)",
            fontSize: 13,
          }}
        >
          Loading…
        </div>
      )}

      {/* Error state */}
      {runId && state.error && !state.loading && (
        <div
          style={{
            padding: 16,
            color: "#c0392b",
            fontSize: 13,
          }}
        >
          Error: {state.error}
        </div>
      )}

      {/* Thread tabs */}
      {runId && !state.loading && !state.error && state.threads.length > 0 && (
        <div
          style={{
            display: "flex",
            gap: 4,
            padding: "8px 12px 0",
            borderBottom: `1px solid ${t.border ?? "rgba(139,26,47,0.2)"}`,
            flexShrink: 0,
            overflowX: "auto",
          }}
        >
          {state.threads.map((thread, idx) => (
            <button
              key={thread.id}
              onClick={() => setActiveThreadIdx(idx)}
              style={{
                padding: "5px 12px",
                borderRadius: "4px 4px 0 0",
                border: "none",
                background:
                  idx === activeThreadIdx
                    ? dark
                      ? "rgba(139,26,47,0.3)"
                      : "rgba(139,26,47,0.1)"
                    : "none",
                color:
                  idx === activeThreadIdx
                    ? "#8B1A2F"
                    : dark
                    ? "rgba(255,255,255,0.5)"
                    : "rgba(0,0,0,0.5)",
                cursor: "pointer",
                fontSize: 12,
                fontWeight: idx === activeThreadIdx ? 700 : 400,
                whiteSpace: "nowrap",
              }}
            >
              §{idx + 1} {thread.title}
            </button>
          ))}
        </div>
      )}

      {/* Blackboard content */}
      {runId && !state.loading && !state.error && (
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "12px 16px",
          }}
          className="pscroll"
        >
          <ConfirmedSection entries={filteredConfirmed} />
          <DraftSection entries={filteredDraft} />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/app
pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add app/components/blackboard-panel.tsx
git commit -m "feat(ui): add BlackboardPanel with thread tabs and seed button"
```

---

## Task 14: Wire BlackboardPanel into App

**Files:**
- Modify: `app/components/app.tsx`

- [ ] **Step 1: Add runId state and BlackboardPanel import to app.tsx**

At the top of the file, after the existing imports, add:

```typescript
import { BlackboardPanel } from "@/components/blackboard-panel";
```

Inside the `App` function, after the `useUIState()` call, add:

```typescript
  const [runId, setRunId] = useState<string | null>(null);
```

- [ ] **Step 2: Split the layout when runId is set**

Find the outer container `<div style={{ display: "flex", height: "100vh", ... }}>` and replace the inner layout div (the one whose width is `simMode ? calc(100vw - ...) : "100%"`) to account for the blackboard panel:

Replace:
```tsx
      <div
        style={{
          width: simMode ? `calc(100vw - ${logSidebarWidth}px)` : "100%",
          height: "100%",
          display: "flex",
          position: "relative",
        }}
```

With:
```tsx
      <div
        style={{
          width: runId
            ? "30%"
            : simMode
            ? `calc(100vw - ${logSidebarWidth}px)`
            : "100%",
          height: "100%",
          display: "flex",
          position: "relative",
          flexShrink: 0,
        }}
```

- [ ] **Step 3: Mount BlackboardPanel after the LogWall block**

Find the block:
```tsx
      {simMode && (
        <LogWall
          ...
        />
      )}
```

After that block add:

```tsx
      {runId && (
        <div style={{ flex: 1, height: "100%", overflow: "hidden" }}>
          <BlackboardPanel runId={runId} onRunIdChange={setRunId} />
        </div>
      )}
```

- [ ] **Step 4: Add a "Show Blackboard" button to the Toolbar area (dev only)**

Inside the `App` JSX, just before the closing `</div>` of the outer flex container, add a small floating dev button (only visible when `runId` is null and not in simMode):

```tsx
      {!runId && !simMode && (
        <button
          onClick={() => setRunId("__open__")}
          style={{
            position: "fixed",
            bottom: 24,
            right: 24,
            padding: "8px 16px",
            background: "#8B1A2F",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            cursor: "pointer",
            fontSize: 12,
            fontWeight: 700,
            zIndex: 1000,
            opacity: 0.85,
          }}
          title="Open Blackboard panel (dev)"
        >
          Blackboard
        </button>
      )}
```

Note: passing `"__open__"` as runId will cause the hook to try fetching that run ID, fail with 404, and display the error state + seed button. This is intentional — the panel handles the no-data state gracefully with the seed button.

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation/app
pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 6: Start the dev server and verify the panel renders**

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation
pnpm dev
```

1. Open `http://localhost:3000`
2. Click the "Blackboard" button in the bottom-right — the layout should split: canvas at 30%, BlackboardPanel at 70%
3. The panel should show "Error: HTTP 404" and a "Seed test data" button
4. Set `DEBUG=true` in `api/.env` (or export it) and restart the API
5. Click "Seed test data" — the panel should load with one thread, one confirmed anchor entry, and no draft entries
6. Close the panel (×) — layout returns to full canvas

- [ ] **Step 7: Commit**

```bash
git add app/components/app.tsx
git commit -m "feat(ui): wire BlackboardPanel into App with 30/70 layout split"
```

---

## Self-Review Checklist

After writing this plan, checking coverage against the spec:

**Spec § 1 Data Layer:**
- ✅ MIG-01 (file-backed SQLite) — Task 1
- ✅ MIG-02 (agents table ALTER) — Task 2
- ✅ MIG-03 (all 11 ECSAS tables + indexes) — Task 2

**Spec § 2 Backend:**
- ✅ Pydantic schemas (`api/swarm/schemas.py`) — Task 3
- ✅ Extend SimulationStep types — Task 3
- ✅ `Blackboard.post` + `Blackboard.read` — Task 4
- ✅ `Blackboard.cite` + `Blackboard.vote` + `Blackboard.get_confirmed` — Task 5
- ✅ `Blackboard.check_promotions` + `Blackboard.soft_delete_stale` — Task 6
- ✅ Zero-vector stub + fallback ranking — Task 4 (`_ZERO_EMBEDDING`)
- ✅ Mention pinning in `read()` — Task 4
- ✅ Self-citation filtering in `cite()` — Task 5
- ✅ Double-promotion guard — Task 6

**Spec § 3 Tools:**
- ✅ `read_blackboard`, `post_to_blackboard`, `cite`, `vote`, `get_confirmed` — Task 7
- ✅ Stub `submit_bid`, `abstain` — Task 7
- ✅ All tools registered in registry — Task 7

**Spec § 4 API:**
- ✅ `GET /api/simulation/{run_id}/blackboard` with thread/layer/include_deleted params — Task 8
- ✅ Draft tree construction (`_build_draft_tree`) — Task 8
- ✅ 404 for unknown run_id — Task 8
- ✅ `POST /api/simulation/seed` gated on `DEBUG=true` — Task 8
- ✅ 403 when DEBUG not set — Task 8

**Spec § 5 Frontend:**
- ✅ Swarm types in `app/lib/types.ts` — Task 9
- ✅ `useBlackboard` with REST fetch on runId change — Task 10
- ✅ `dispatch()` handles bb-post, bb-promote, bb-delete, bb-cite, bb-vote — Task 10
- ✅ `DraftEntryComponent` recursive — Task 11
- ✅ `ConfirmedSection` with anchor/finding/system badges — Task 12
- ✅ `DraftSection` — Task 12
- ✅ `BlackboardPanel` with thread tabs, seed button, close — Task 13
- ✅ 30/70 layout split in `app.tsx` — Task 14
- ✅ Dev "Blackboard" button — Task 14

**Out-of-scope items (correctly absent):**
- Real embeddings (Phase 2)
- Market Maker, Auction Engine, Orchestrator (Phase 2)
- Canvas swarm nodes, animations (Phase 2)
- Swarm Config Modal (Phase 2)
