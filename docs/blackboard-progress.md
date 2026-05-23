# feat-79-blackboard — Implementation Progress

**Branch:** `feat-79-blackboard`
**Plan:** `docs/superpowers/plans/2026-05-23-blackboard.md`
**Design spec:** `docs/superpowers/specs/2026-05-23-blackboard-design.md`
**PRD:** `docs/PRD-ECSAS-v3.md`
**Approach:** Bottom-up — DB → Logic → API → Frontend

---

## How to Continue

1. Read the design spec and plan files above (the plan has complete code for every step)
2. Run the test suite to confirm current state: `cd api && uv run pytest tests/ -v`
3. Pick up from the first pending task below
4. Use TDD: write the failing test first, then implement, then commit

```bash
cd /Users/simsim/project_AI_agents_stochastic_self_organisation
git checkout feat-79-blackboard
cd api && uv run pytest tests/ -v   # should be 38 tests, all green
```

---

## Task Status

| # | Task | Status | Commit(s) |
|---|------|--------|-----------|
| 1 | MIG-01 — File-backed SQLite | ✅ Done | `38ee252`, `0874c58` |
| 2 | MIG-02 + MIG-03 — ECSAS DB tables | ✅ Done | `8d7cc04`, `8890c20` |
| 3 | Pydantic Schemas | ✅ Done | `3a77e91`, `9467b85` |
| 4 | Blackboard.post + Blackboard.read | ⬜ Pending | — |
| 5 | Blackboard.cite + vote + get_confirmed | ⬜ Pending | — |
| 6 | Blackboard.check_promotions + soft_delete_stale | ⬜ Pending | — |
| 7 | Blackboard Tools + Stub Auction Tools | ⬜ Pending | — |
| 8 | Simulation REST Endpoints | ⬜ Pending | — |
| 9 | Frontend Types | ⬜ Pending | — |
| 10 | useBlackboard Hook | ⬜ Pending | — |
| 11 | DraftEntry Component | ⬜ Pending | — |
| 12 | DraftSection + ConfirmedSection | ⬜ Pending | — |
| 13 | BlackboardPanel | ⬜ Pending | — |
| 14 | Wire BlackboardPanel into App | ⬜ Pending | — |

---

## What Was Built (Tasks 1–3)

### Task 1 — File-backed SQLite (`38ee252`, `0874c58`)

**`api/db/__init__.py`** — switched from `:memory:` to file-backed SQLite:
- `DB_PATH = os.getenv("DB_PATH", "./data/swarm.db")` — test fixtures set `DB_PATH=":memory:"`
- `os.makedirs(...)` creates `./data/` directory before connecting
- Module docstring updated to reflect configurable storage

**`api/tests/conftest.py`** — pins `DB_PATH=":memory:"` for all tests:
```python
import os
os.environ.setdefault("DB_PATH", ":memory:")  # Must be before app import
```

### Task 2 — ECSAS DB Tables (`8d7cc04`, `8890c20`)

**`api/db/__init__.py`** — added two migration blocks:

**MIG-02** — extends `agents` table (idempotent via `PRAGMA table_info` check):
- `capability_embedding TEXT DEFAULT NULL`
- `created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`

**MIG-03** — 11 new ECSAS tables (all `CREATE TABLE IF NOT EXISTS`):
`swarm_runs`, `contracts`, `threads`, `bids`, `draft_entries`, `citations`, `votes`, `confirmed_entries`, `reputation`, `agent_trust`, `amendments` — plus 9 indexes.

**`api/tests/test_schema.py`** — new test file with 4 tests:
- `test_v0_tables_exist` — agents, knowledge_files, agent_files
- `test_ecsas_tables_exist` — all 11 ECSAS tables
- `test_agents_table_has_new_columns` — capability_embedding, created_at
- `test_init_db_is_idempotent` — calling init_db() twice succeeds

### Task 3 — Pydantic Schemas (`3a77e91`, `9467b85`)

**`api/swarm/__init__.py`** — empty package marker

**`api/swarm/schemas.py`** — 9 schema classes:
- `SwarmRunConfig` — run configuration with bounds-validated fields
- `ThreadSchema`, `ContractSchema` — with JSON field validators for SQLite TEXT columns
- `DraftEntrySchema` — recursive (`children: list[DraftEntrySchema] = []`), requires `model_rebuild()` after definition, `author_name: str = ""`
- `ConfirmedEntrySchema`, `SwarmFinalOutput`
- `BlackboardResponse`, `SeedRequest`, `SeedResponse`

**Key fix in schemas:** `ThreadSchema` and `ContractSchema` have `@field_validator(..., mode="before")` to parse JSON strings from SQLite TEXT columns (e.g., `required_expertise: '["ml"]'` → `["ml"]`).

**`api/schemas/__init__.py`** — `_SimStepType` extended with 12 ECSAS event types:
`"bid"`, `"abstain"`, `"bb-post"`, `"bb-cite"`, `"bb-vote"`, `"bb-promote"`, `"bb-delete"`, `"bb-mention"`, `"amendment"`, `"amendment-approved"`, `"amendment-rejected"`, `"convergence"`

---

## What's Next — Task 4

**Files:** create `api/swarm/blackboard.py` and `api/tests/test_blackboard.py`

Full code is in the plan at `docs/superpowers/plans/2026-05-23-blackboard.md` under **Task 4**.

Summary of what to build:

```python
class Blackboard:
    def __init__(self, db: aiosqlite.Connection): ...

    async def post(self, *, run_id, thread_id, author_id, content,
                   entry_type, round, reply_to=None, mention_agents=None) -> str:
        # INSERT into draft_entries with _ZERO_EMBEDDING = json.dumps([0.0] * 1536)
        # Returns entry_id

    async def read(self, *, run_id, query, thread_id, k=10,
                   agent_id=None) -> list[DraftEntrySchema]:
        # SELECT with LEFT JOIN on agents (for author_name) and citations (for citation_count)
        # Rank: citation_count DESC, created_at ASC
        # Pin entries mentioning agent_id to position 0
```

Tests to write first (TDD):
- `test_post_returns_entry_id`
- `test_post_then_read_returns_entry`
- `test_read_respects_thread_filter`
- `test_read_does_not_return_invisible_entries`

Commit: `feat(blackboard): implement Blackboard.post and Blackboard.read`

---

## Key Decisions (for context)

- **Option B scope**: Phase 1 (DB + schema) + Phase 3 (Blackboard + frontend). Market Maker, Auction Engine, Orchestrator are **out of scope** (Phase 2).
- **Frontend state model (Option C hybrid)**: REST-initialized on mount, `dispatch()` pre-wired for SSE events in Phase 2.
- **Zero-vector embeddings**: `content_embedding` stored as 1536 zeros. When all embeddings are zero, cosine similarity is undefined — ranking falls back to `citation_count DESC, created_at ASC`. Phase 2 replaces with real `text-embedding-3-small` calls.
- **`DB_PATH=":memory:"` for tests**: Set in `conftest.py` BEFORE `from api.index import app` (import order matters).
- **MIG-02 idempotency**: SQLite doesn't support `ALTER TABLE IF NOT EXISTS` — solved by reading `PRAGMA table_info(agents)` and checking existing column names.
- **`DraftEntrySchema.author_name`**: NOT a DB column — populated via `COALESCE(a.name, de.author_id) AS author_name` in the Blackboard.read() SQL query. Default `""` for safety.
- **`citation_count` on drafts**: NOT a DB column on `draft_entries` — computed via `COUNT(*)` JOIN from `citations` table in Blackboard.read(). Default `0`.

---

## File Map

```
api/
├── db/__init__.py              ← Modified: file-backed + MIG-02 + MIG-03
├── schemas/__init__.py         ← Modified: extended _SimStepType
├── swarm/
│   ├── __init__.py             ← Created (empty)
│   └── schemas.py              ← Created: 9 Pydantic schemas
│   # blackboard.py             ← TODO Task 4
├── tools/
│   # builtin/blackboard_tools.py  ← TODO Task 7
│   # registry.py               ← TODO Task 7 (modify)
├── routes/
│   # simulation.py             ← TODO Task 8
│   # __init__.py               ← TODO Task 8 (modify)
├── index.py                    ← TODO Task 8 (modify: mount router)
└── tests/
    ├── conftest.py             ← Modified: DB_PATH=:memory:
    ├── test_schema.py          ← Created: 4 DB migration tests
    # test_blackboard.py        ← TODO Task 4
    # test_simulation.py        ← TODO Task 8

app/
├── lib/types.ts                ← TODO Task 9
├── hooks/
│   # useBlackboard.ts          ← TODO Task 10
└── components/
    # draft-entry.tsx            ← TODO Task 11
    # draft-section.tsx          ← TODO Task 12
    # confirmed-section.tsx      ← TODO Task 12
    # blackboard-panel.tsx       ← TODO Task 13
    app.tsx                     ← TODO Task 14 (modify: add runId state + panel)
```
