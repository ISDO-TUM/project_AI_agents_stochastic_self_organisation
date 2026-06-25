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

| #   | Task                                            | Status  | Commit(s)            |
| --- | ----------------------------------------------- | ------- | -------------------- |
| 1   | MIG-01 — File-backed SQLite                     | ✅ Done | `38ee252`, `0874c58` |
| 2   | MIG-02 + MIG-03 — ECSAS DB tables               | ✅ Done | `8d7cc04`, `8890c20` |
| 3   | Pydantic Schemas                                | ✅ Done | `3a77e91`, `9467b85` |
| 4   | Blackboard.post + Blackboard.read               | ✅ Done | `1afd8a7`            |
| 5   | Blackboard.cite + vote + get_confirmed          | ✅ Done | `1afd8a7`            |
| 6   | Blackboard.check_promotions + soft_delete_stale | ✅ Done | `1afd8a7`            |
| 7   | Blackboard Tools + Stub Auction Tools           | ✅ Done | `12cae25`            |
| 8   | Simulation REST Endpoints                       | ✅ Done | `1f0d03a`            |
| 9   | Frontend Types                                  | ✅ Done | `cfb074f`            |
| 10  | useBlackboard Hook                              | ✅ Done | `cfb074f`            |
| 11  | DraftEntry Component                            | ✅ Done | `cfb074f`            |
| 12  | DraftSection + ConfirmedSection                 | ✅ Done | `cfb074f`            |
| 13  | BlackboardPanel                                 | ✅ Done | `cfb074f`            |
| 14  | Wire BlackboardPanel into App                   | ✅ Done | `cfb074f`            |

---

## What Was Built (Tasks 1–3)

### Task 1 — Persistent store: PostgreSQL via SQLAlchemy Core

**`server/db/__init__.py`** — the engine is built from `DATABASE_URL`:

- **Production / Docker:** PostgreSQL (asyncpg). Persistence across requests and restarts is provided by Postgres — there is no `DB_PATH`/`./data/swarm.db` file.
- **Tests:** the same SQLAlchemy Core schema is pointed at an in-memory SQLite database (StaticPool) via `conftest.py`, so no external service is needed for `pytest`.
- Schema is defined once as `Table` objects in `server/db/tables.py` and created on startup via `metadata.create_all`; `_apply_column_migrations` adds later columns with `ALTER TABLE … IF NOT EXISTS` (Postgres) / `PRAGMA` guards (SQLite).

### Task 2 — ECSAS DB Tables (`8d7cc04`, `8890c20`)

**`server/db/__init__.py`** — added two migration blocks:

**MIG-02** — extends `agents` table (idempotent via `PRAGMA table_info` check):

- `capability_embedding TEXT DEFAULT NULL`
- `created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`

**MIG-03** — 11 new ECSAS tables (all `CREATE TABLE IF NOT EXISTS`):
`swarm_runs`, `contracts`, `threads`, `bids`, `draft_entries`, `citations`, `votes`, `confirmed_entries`, `reputation`, `agent_trust`, `amendments` — plus 9 indexes.

**`server/tests/test_schema.py`** — new test file with 4 tests:

- `test_v0_tables_exist` — agents, knowledge_files, agent_files
- `test_ecsas_tables_exist` — all 11 ECSAS tables
- `test_agents_table_has_new_columns` — capability_embedding, created_at
- `test_init_db_is_idempotent` — calling init_db() twice succeeds

### Task 3 — Pydantic Schemas (`3a77e91`, `9467b85`)

**`server/market_hive/__init__.py`** — empty package marker

**`server/market_hive/schemas.py`** — 9 schema classes:

- `SwarmRunConfig` — run configuration with bounds-validated fields
- `ThreadSchema`, `ContractSchema` — with JSON field validators for SQLite TEXT columns
- `DraftEntrySchema` — recursive (`children: list[DraftEntrySchema] = []`), requires `model_rebuild()` after definition, `author_name: str = ""`
- `ConfirmedEntrySchema`, `SwarmFinalOutput`
- `BlackboardResponse`, `SeedRequest`, `SeedResponse`

**Key fix in schemas:** `ThreadSchema` and `ContractSchema` have `@field_validator(..., mode="before")` to parse JSON strings from SQLite TEXT columns (e.g., `required_expertise: '["ml"]'` → `["ml"]`).

**`server/schemas/__init__.py`** — `_SimStepType` extended with 12 ECSAS event types:
`"bid"`, `"abstain"`, `"bb-post"`, `"bb-cite"`, `"bb-vote"`, `"bb-promote"`, `"bb-delete"`, `"bb-mention"`, `"amendment"`, `"amendment-approved"`, `"amendment-rejected"`, `"convergence"`

---

## What's Next — Task 4

**Files:** create `server/market_hive/blackboard.py` and `server/tests/test_blackboard.py`

Full code is in the plan at `docs/superpowers/plans/2026-05-23-blackboard.md` under **Task 4**.

Summary of what to build:

```python
class Blackboard:
    def __init__(self, db: AsyncConnection): ...  # SQLAlchemy async connection

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

## What Was Built (Tasks 4–14)

### Task 4–6 — Blackboard class (`1afd8a7`)

**`server/market_hive/blackboard.py`** — full `Blackboard` class with all five read/write methods:

- `post()` — INSERT into `draft_entries`, zero-vector embedding stub, returns `entry_id`
- `read()` — LEFT JOIN with `agents` (author_name) + `citations` (citation_count), mention-pinning, `is_visible` filter, ranked `citation_count DESC, created_at ASC`
- `cite()` — self-citation guard, UNIQUE constraint handling, updates `last_cited_round`
- `vote()` — UNIQUE per agent-entry; returns `{"ok": bool}`
- `get_confirmed()` — SELECT from `confirmed_entries`, optional thread filter
- `check_promotions()` — dynamic threshold M = max(1, n//3+1), double-promotion guard, inserts to `confirmed_entries`
- `soft_delete_stale()` — round-1 exemption, `changes()` for count, portable (no RETURNING)

**`server/tests/test_blackboard.py`** — 12 tests covering all methods (TDD).

### Task 7 — Blackboard Tools (`12cae25`)

**`server/tools/builtin/blackboard_tools.py`** — 7 tool classes:

- `ReadBlackboardTool`, `PostToBlackboardTool`, `CiteTool`, `VoteTool`, `GetConfirmedTool` — fully implemented, delegate to `Blackboard` class
- `SubmitBidTool`, `AbstainTool` — Phase 2 stubs (return static JSON)

**`server/tools/registry.py`** — all 7 tools registered alongside `FilesTool`.

### Task 8 — Simulation REST Endpoints (`1f0d03a`)

**`server/routes/simulation.py`** — two endpoints:

- `GET /api/simulation/{run_id}/blackboard` — returns `BlackboardResponse` with `threads`, `confirmed`, `draft` (tree-nested via `_build_draft_tree`). Query params: `thread_id`, `layer` (draft/confirmed/both), `include_deleted`. 404 for unknown run.
- `POST /api/simulation/seed` — creates run+contract+thread+anchor, seeds draft proposals from given `agent_ids`. Gated on `DEBUG=true` (returns 403 in production).

**`server/routes/__init__.py`** + **`server/index.py`** — router exported and mounted.

**`server/tests/test_simulation.py`** — 5 tests (404, seed, blackboard retrieval, thread filter, DEBUG gate).

### Tasks 9–14 — Frontend (`cfb074f`)

**`client/lib/types.ts`** — added `SwarmSimStepType` (union of all ECSAS event types), `ThreadInfo`, `ConfirmedEntry`, `DraftEntry` (recursive), `BlackboardState`.

**`client/hooks/useBlackboard.ts`** — `useBlackboard(runId)` hook:

- REST-fetches on `runId` change, populates `BlackboardState`
- `dispatch(event)` applies optimistic updates for `bb-post`, `bb-promote`, `bb-delete`, `bb-cite`, `bb-vote`

**`client/components/draft-entry.tsx`** — `DraftEntryComponent` — recursive, depth-indented, shows badge (P/R/V/⚙), author, round, citation count, children.

**`client/components/confirmed-section.tsx`** — `ConfirmedSection` — gold-bordered anchors (📌) and findings (✅).

**`client/components/draft-section.tsx`** — `DraftSection` — wraps `DraftEntryComponent` list with section header.

**`client/components/blackboard-panel.tsx`** — `BlackboardPanel` — full panel with:

- Thread tabs (§1, §2, …)
- Loading / error / empty states
- "Seed test data" button (calls `POST /api/simulation/seed`)
- Close (×) button

**`client/components/app.tsx`** — wired:

- `runId` state added
- Canvas container shrinks to 30% width when `runId` is set
- `BlackboardPanel` renders in remaining 70%
- Floating "Blackboard" dev button (bottom-right, hidden in simMode)

---

## What's Next — Phase 2 (Out of Scope for this branch)

- **Market Maker** (`server/market_hive/market_maker.py`) — LLM-powered contract decomposition
- **Auction Engine** (`server/market_hive/auction.py`) — bid evaluation, taker selection
- **Orchestrator** (`server/market_hive/orchestrator.py`) — round loop, SSE streaming
- **Real embeddings** — replace `_ZERO_EMBEDDING` with `text-embedding-3-small` calls
- **Canvas swarm nodes** — Market Maker node, Blackboard node, swarm animations
- **SSE wiring** — connect `useBlackboard.dispatch` to the `GET /api/simulation/swarm` SSE stream

---

## Key Decisions (for context)

- **Option B scope**: Phase 1 (DB + schema) + Phase 3 (Blackboard + frontend). Market Maker, Auction Engine, Orchestrator are **out of scope** (Phase 2).
- **Frontend state model (Option C hybrid)**: REST-initialized on mount, `dispatch()` pre-wired for SSE events in Phase 2.
- **Zero-vector embeddings**: `content_embedding` stored as 1536 zeros. When all embeddings are zero, cosine similarity is undefined — ranking falls back to `citation_count DESC, created_at ASC`. Phase 2 replaces with real `text-embedding-3-small` calls.
- **In-memory SQLite for tests**: `conftest.py` builds the engine against an in-memory SQLite DB (StaticPool) so the suite runs with no external Postgres.
- **MIG-02 idempotency**: SQLite doesn't support `ALTER TABLE IF NOT EXISTS` — solved by reading `PRAGMA table_info(agents)` and checking existing column names; Postgres uses `ADD COLUMN IF NOT EXISTS`.
- **`DraftEntrySchema.author_name`**: NOT a DB column — populated via `COALESCE(a.name, de.author_id) AS author_name` in the Blackboard.read() SQL query. Default `""` for safety.
- **`citation_count` on drafts**: NOT a DB column on `draft_entries` — computed via `COUNT(*)` JOIN from `citations` table in Blackboard.read(). Default `0`.

---

## File Map

```
server/
├── db/tables.py                ← SQLAlchemy Core schema (MIG-02 + MIG-03)
├── db/__init__.py              ← Modified: column migrations (MIG-02)
├── schemas/__init__.py         ← Modified: extended _SimStepType
├── market_hive/
│   ├── __init__.py             ← Created (empty)
│   ├── schemas.py              ← Created: 9 Pydantic schemas
│   └── blackboard.py           ← Created: Blackboard class (Tasks 4-6)
├── tools/
│   ├── builtin/blackboard_tools.py  ← Created: 7 tool classes (Task 7)
│   └── registry.py             ← Modified: 7 new tools registered (Task 7)
├── routes/
│   ├── simulation.py           ← Created: GET /blackboard + POST /seed (Task 8)
│   └── __init__.py             ← Modified: exports simulation_router (Task 8)
├── index.py                    ← Modified: mounts simulation_router (Task 8)
└── tests/
    ├── conftest.py             ← Modified: in-memory SQLite engine
    ├── test_schema.py          ← Created: 4 DB migration tests
    ├── test_blackboard.py      ← Created: 12 Blackboard tests (Tasks 4-6)
    └── test_simulation.py      ← Created: 5 endpoint tests (Task 8)

client/
├── lib/types.ts                ← Modified: ECSAS swarm types (Task 9)
├── hooks/
│   └── useBlackboard.ts        ← Created: REST-init + SSE-ready dispatch (Task 10)
└── components/
    ├── draft-entry.tsx         ← Created: recursive DraftEntry component (Task 11)
    ├── draft-section.tsx       ← Created: DraftSection wrapper (Task 12)
    ├── confirmed-section.tsx   ← Created: ConfirmedSection (Task 12)
    ├── blackboard-panel.tsx    ← Created: BlackboardPanel with thread tabs (Task 13)
    └── app.tsx                 ← Modified: runId state + 30/70 layout split (Task 14)
```
