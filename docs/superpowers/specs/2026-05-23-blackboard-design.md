# feat-79-blackboard Design Spec

**Date:** 2026-05-23
**Branch:** feat-79-blackboard
**Approach:** Bottom-up (DB → Logic → API → Frontend)
**Scope:** PRD-ECSAS-v3 Phase 1 (Foundation) + Phase 3 (Blackboard & Stigmergy)

---

## Scope

This branch delivers the shared blackboard substrate: file-backed persistence, all ECSAS database tables, the `Blackboard` class and its five tools, two REST endpoints, and the `BlackboardPanel` frontend component tree. Market Maker, Auction Engine, and the swarm orchestrator are **out of scope** — those land in Phase 2.

The frontend panel uses **Option C (hybrid)**: state is initialized via a REST fetch on mount and pre-wired to receive SSE-dispatched events in Phase 2 without a refetch.

---

## 1. Data Layer

### 1.1 MIG-01 — File-backed SQLite

**File:** `api/db/__init__.py`

Change `aiosqlite.connect(":memory:")` to `aiosqlite.connect(DB_PATH)` where:

```python
DB_PATH = os.getenv("DB_PATH", "./data/swarm.db")
```

`init_db()` creates `./data/` with `os.makedirs(dirname(DB_PATH), exist_ok=True)` before connecting.
Test fixtures set `DB_PATH=":memory:"` via environment to preserve isolation.

### 1.2 MIG-02 — Agents table additions

```sql
ALTER TABLE agents ADD COLUMN capability_embedding TEXT DEFAULT NULL;
ALTER TABLE agents ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
```

Applied with `IF NOT EXISTS` guard via `PRAGMA table_info(agents)` check. Existing rows unaffected.

### 1.3 MIG-03 — ECSAS tables

Ten new tables (all `CREATE TABLE IF NOT EXISTS`):

| Table | Purpose |
|---|---|
| `swarm_runs` | Run bookkeeping (status, termination, token usage) |
| `contracts` | Market Maker output: task type, nature, expertise, embedding |
| `threads` | Subcontracts: title, description, required expertise |
| `bids` | Auction records: taker/observer/abstained flags |
| `draft_entries` | Append-only blackboard posts (proposal, reply, vote, system) |
| `citations` | `cite()` tool calls: citing agent → cited entry, per round |
| `votes` | Cold-start `vote()` calls: voter → entry |
| `confirmed_entries` | Promoted findings + anchors (permanent) |
| `reputation` | Per-run, per-agent, per-domain score |
| `agent_trust` | Cross-run persistent trust scores |
| `amendments` | `request_expertise` proposals and vote results |

Full DDL: see PRD-ECSAS-v3 §7.1. All indexes included as specified.

---

## 2. Backend Blackboard Module

### 2.1 Pydantic Schemas

**File:** `api/swarm/schemas.py`

Verbatim from PRD §7.2:
- `SwarmRunConfig` — run configuration with all defaults
- `ContractSchema`, `ThreadSchema` — Market Maker output
- `DraftEntrySchema` — includes `children: list[DraftEntrySchema]` for tree rendering
- `ConfirmedEntrySchema`
- `SwarmFinalOutput`
- `SimStepType` — extended literal covering all V0 + ECSAS event types

### 2.2 Blackboard Class

**File:** `api/swarm/blackboard.py`

```python
class Blackboard:
    def __init__(self, db: aiosqlite.Connection): ...

    async def post(
        self, run_id, thread_id, author_id, content,
        entry_type, reply_to=None, mention_agents=None, round=1
    ) -> str:  # returns entry_id
        # Insert draft_entries row
        # content_embedding: zero vector stub (Phase 2 wires real embeddings)
        # If mention_agents: create mention records + emit SSE hint
        ...

    async def read(
        self, run_id, query, thread_id, k=10, agent_id=None
    ) -> list[DraftEntrySchema]:
        # Fetch visible entries for run_id + thread filter
        # Score: cosine(embed(query), entry.content_embedding) * log(1 + citation_count)
        # Pin entries mentioning agent_id to position 0
        # Return top-k
        ...

    async def cite(
        self, run_id, citing_agent_id, entry_ids, round
    ) -> dict:  # {cited: int, skipped_self: int}
        # Insert citations rows (UNIQUE constraint handles dedup)
        # Skip self-citations server-side
        # Update last_cited_round + citation_count on cited entries
        ...

    async def vote(
        self, run_id, voter_id, entry_id, thread_id
    ) -> dict:  # {ok: bool}
        # Insert votes row
        ...

    async def get_confirmed(
        self, run_id, thread_id=None
    ) -> list[ConfirmedEntrySchema]:
        # Return confirmed_entries filtered by run_id (and thread_id if provided)
        ...

    async def check_promotions(self, run_id, round) -> list[ConfirmedEntrySchema]:
        # For each visible draft entry:
        #   M = max(1, n_thread_participants // 3 + 1)
        #   distinct_citers = count distinct non-self citing_agent_id
        #   if distinct_citers >= M: insert confirmed_entries row
        # Returns newly promoted entries
        ...

    async def soft_delete_stale(self, run_id, current_round, decay_rounds=3) -> int:
        # Round-1 entries exempt until round 2 complete
        # For entries where current_round - last_cited_round >= decay_rounds:
        #   SET is_visible=false, deleted_at=now()
        # Returns count of deleted entries
        ...
```

**Embedding stub:** `content_embedding` is stored as a JSON list of 1536 zeros for now. When all embeddings are zero, cosine similarity is undefined — the attention query falls back to ranking by `citation_count DESC, created_at ASC` (most-cited first, earliest first on tie). Phase 2 replaces the zero vector with real `text-embedding-3-small` calls and the fallback becomes unreachable.

### 2.3 Blackboard Tools

**File:** `api/tools/builtin/blackboard_tools.py`

Five tool classes following the existing `Tool` ABC pattern:

| Tool class | Maps to | Input Pydantic model |
|---|---|---|
| `ReadBlackboardTool` | `Blackboard.read()` | `query: str, thread_id: str\|None, k: int=10` |
| `PostToBlackboardTool` | `Blackboard.post()` | `content, entry_type, thread_id, reply_to=None, mention_agents=[]` |
| `CiteTool` | `Blackboard.cite()` | `entry_ids: list[str]` |
| `VoteTool` | `Blackboard.vote()` | `entry_id: str` |
| `GetConfirmedTool` | `Blackboard.get_confirmed()` | `thread_id: str\|None` |

Each tool's `execute()` receives `(input_data, context)` where `context` carries `run_id`, `agent_id`, `thread_id`, `round` — these will be injected by the Phase 2 orchestrator. In this branch the tools are **registered and schema-complete** but not invoked by agents (no orchestrator yet). The `execute()` implementations are written in full so Phase 2 can call them without changes.

**Stub tools** also registered (schema only, `execute()` returns `{"ok": True}`):
- `SubmitBidTool` — `justification: str, thread_id: str|None`
- `AbstainTool` — `reason: str, thread_id: str|None`

**Registration:** `api/tools/registry.py` — all seven tools appended to existing registry.

---

## 3. API Endpoints

**File:** `api/routes/simulation.py`

### `GET /api/simulation/{run_id}/blackboard`

```
Query params:
  thread_id:       str | None   (default: None — all threads)
  layer:           "draft" | "confirmed" | "both"   (default: "both")
  include_deleted: bool         (default: false)

Response 200:
{
  "threads":   list[ThreadSchema],
  "confirmed": list[ConfirmedEntrySchema],
  "draft":     list[DraftEntrySchema]   // tree: children populated
}

Response 200 (run exists, no entries yet): all lists return empty — not 404.
Response 404: { "detail": "run not found" }  — only when run_id doesn't exist in swarm_runs.
```

Draft tree construction: done in Python — build `id → entry` map, assign children, return roots only.

### `POST /api/simulation/seed` *(dev only — gated on `DEBUG=true` env var)*

```
Request body:
{
  "prompt":   str,
  "agent_ids": list[str]   // must be existing agent IDs in DB
}

Response 200:
{
  "run_id":    str,
  "thread_id": str
}

Response 403: { "detail": "seed endpoint disabled in production" }
```

Creates one `swarm_run`, one `contract`, one `thread`, and inserts 3–4 sample `draft_entries` (proposals from each agent) plus one `confirmed_entries` anchor. Useful for frontend development without running the full swarm.

Router mounted at `/api/simulation` in `api/index.py`.

---

## 4. Frontend

### 4.1 `useBlackboard` Hook

**File:** `app/hooks/useBlackboard.ts`

```typescript
interface BlackboardState {
  threads: ThreadSchema[];
  confirmed: ConfirmedEntrySchema[];
  draft: DraftEntrySchema[];      // roots only; children nested
  loading: boolean;
  error: string | null;
}

function useBlackboard(runId: string | null): {
  state: BlackboardState;
  dispatch: (event: SimStep) => void;   // Phase 2: called by useSimulation SSE loop
}
```

**On mount / runId change:**
- If `runId` is null: reset to empty state.
- If `runId` is set: `GET /api/simulation/{runId}/blackboard` → populate state.

**`dispatch(event)`** — updates state in-memory based on event type:
- `bb-post`: prepend new `DraftEntrySchema` to draft (or nest under parent if `reply_to` set)
- `bb-promote`: move entry from draft to confirmed, add to `confirmed` list
- `bb-delete`: set `is_visible: false` on matching draft entry
- `bb-vote` / `bb-cite`: increment counters on matching entry
- All other event types: no-op (safe for Phase 2 SSE loop to call unconditionally)

### 4.2 Component Tree

**`BlackboardPanel`** — `app/components/blackboard-panel.tsx`
- Receives `runId: string | null`
- If no `runId`: renders nothing (hidden in topology mode)
- Calls `useBlackboard(runId)`
- Renders `ThreadTabs` (one per `state.threads`)
- Below tabs: `ConfirmedSection` + `DraftSection` for the active thread

**`ConfirmedSection`** — `app/components/confirmed-section.tsx`
- Props: `entries: ConfirmedEntrySchema[]`
- Sticky header "CONFIRMED"
- Renders each entry with type badge: 📌 anchor, ✅ finding, ⚙ system
- Shows `citation_count` and `round_confirmed`

**`DraftSection`** — `app/components/draft-section.tsx`
- Props: `entries: DraftEntrySchema[]` (roots only, children nested)
- Scrollable
- Maps over roots, renders `DraftEntry` for each

**`DraftEntry`** — `app/components/draft-entry.tsx`
- Props: `entry: DraftEntrySchema, depth: number`
- Renders: author name, round badge, entry type, content (via existing `MarkdownRenderer`), citation count (♡N), reply count
- If `!is_visible`: dimmed (30% opacity)
- If `entry.children.length > 0`: renders children recursively with `depth + 1` indentation
- Max depth indentation: 4 levels (capped visually)

### 4.3 Layout Integration

In the main canvas layout (`app/components/app.tsx` or equivalent):
- When `mode === "swarm"` and `runId` is set: canvas takes `30%` width, `BlackboardPanel` takes `70%`
- When `mode === "topology"` or no `runId`: existing full-width canvas layout unchanged

Existing `log-wall.tsx` remains as collapsible footer strip in both modes.

---

## 5. Out of Scope for This Branch

The following are deliberately deferred to Phase 2:

- Real embedding calls (`text-embedding-3-small`) — stub zeros used
- Market Maker (`api/swarm/market_maker.py`)
- Auction Engine (`api/swarm/auction.py`)
- Swarm orchestrator (`api/swarm/orchestrator.py`)
- Convergence Engine, Trust Registry, Amendment Engine, Termination Engine
- SSE stream from `POST /api/simulation/run` in swarm mode
- Canvas swarm nodes (Market Maker node, Blackboard node, Thread nodes)
- Swarm Config Modal
- Animation grammar (bid particles, promote glow, etc.)

---

## 6. Testing

- `api/tests/test_blackboard.py` — unit tests for `Blackboard` class methods using `DB_PATH=":memory:"`
- Tests cover: post + read round-trip, citation tracking, promotion threshold, soft-delete trigger, mention pinning
- Existing agent/file tests unaffected (all use in-memory DB)

---

## 7. How to Move Forward After This Branch

Once `feat-79-blackboard` is merged:

1. **Phase 2A — Embeddings** (`api/swarm/embeddings.py`): replace zero-vector stubs with real `text-embedding-3-small` calls. `capability_embedding` computed on `POST /api/agents/`.
2. **Phase 2B — Market Maker** (`api/swarm/market_maker.py`): prompt → Contract + Threads, post anchors to blackboard.
3. **Phase 2C — Auction Engine** (`api/swarm/auction.py`): invitation, self-selection, taker assignment.
4. **Phase 2D — Swarm Orchestrator** (`api/swarm/orchestrator.py`): wire MM → Auction → Round loop → SSE stream. The `useBlackboard.dispatch()` hook is already ready to consume SSE events.
5. **Phase 2E — Canvas nodes**: Market Maker node, Blackboard node, Thread nodes, animation grammar.
