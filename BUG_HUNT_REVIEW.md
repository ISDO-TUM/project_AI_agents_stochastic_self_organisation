# Bug Hunt Audit — Issue #117

## Summary

- **Total findings:** 40
- **High severity:** 11
- **Medium severity:** 18
- **Low severity:** 11

---

## Findings

### F-001 — Benchmark runner accesses non-existent simulation response fields [HIGH]

**File:** `server/benchmarks/run.py:256-268`
**Category:** bug
**Description:** `_run_simulation()` returns the parsed JSON from `POST /api/simulation/run`. That endpoint now returns `SimulationStartResponse` which only has `trial_id` and `status`. The runner then accesses `sim["converged"]`, `sim["rounds_used"]`, and `sim.get("consensus")` — none of which exist in the response. At runtime this raises `KeyError` on line 260, making the entire benchmark runner unusable.
**Evidence:**
```python
# run.py line 256-268
evaluated = _evaluate(client, benchmark_id, sim.get("consensus") or "")
row = {
    "trial": trial_idx,
    "answer_correct": evaluated["answer_correct"],
    "converged": sim["converged"],          # KeyError — field does not exist
    "rounds_used": sim["rounds_used"],      # KeyError — field does not exist
    ...
}
# SimulationStartResponse (schemas/__init__.py)
class SimulationStartResponse(BaseModel):
    trial_id: str
    status: str = Field(default="started")  # converged/rounds_used/consensus never added
```
**Fix:** The runner was written against an older synchronous simulation API. Either restore synchronous execution fields to the response (converged, rounds_used, consensus), or rewrite the runner to poll `GET /api/history/trials/{trial_id}` until `status == "completed"`, then derive the answer from the messages endpoint. The runner also needs to wait for completion before calling `_evaluate`.
**Auto-fixable:** no — requires design decision on polling vs. synchronous response.

---

### F-002 — Background simulation task receives a closed database connection [HIGH]

**File:** `server/routes/simulation.py:70-80`
**Category:** bug / undefined-behavior
**Description:** `run_simulation` uses `db: DBDep` which is a FastAPI dependency obtained via `get_db()` — a generator that yields a connection inside `async with _engine.connect() as conn`. FastAPI disposes yielded dependencies **after** the HTTP response is sent but **before** background tasks run. The background task `_run_simulation_background` therefore receives an already-closed (returned-to-pool) connection. With SQLAlchemy's async pool this is non-deterministic: on test runs using `StaticPool` the same connection is recycled invisibly, but in production with `asyncpg` the closed connection will be reused by a concurrent request, causing data corruption, `InvalidTransactionError`, or silent swallowed writes.
**Evidence:**
```python
# simulation.py
background_tasks.add_task(
    _run_simulation_background,
    body.prompt,
    db,          # <-- yielded by get_db(), will be released before task runs
    ...
)
```
**Fix:** Do not pass the request-scoped connection to a background task. Instead, pass `get_engine()` and open a new connection inside `_run_simulation_background`:
```python
async def _run_simulation_background(prompt, engine, rounds, ...):
    async with engine.connect() as db:
        ...
```
And change the route to pass `get_engine()` instead of `db`.
**Auto-fixable:** no — requires refactoring of the function signature.

---

### F-003 — `ApiKeysModal` component exported but never imported or used [HIGH]

**File:** `client/components/panels/api-keys-modal.tsx`
**Category:** dead-code
**Description:** `ApiKeysModal` is defined and exported but is not imported anywhere in the codebase. The same functionality is implemented inside `TweaksPanel` (in `tweaks-panel.tsx`). The file is dead code that will cause confusion about which is the canonical API key entry point.
**Evidence:**
```bash
grep -rn "ApiKeysModal" client/  # returns only the file itself (definition line)
```
**Fix:** Delete `client/components/panels/api-keys-modal.tsx` entirely.
**Auto-fixable:** yes — delete the file.

---

### F-004 — `connectNodes` silently creates bidirectional connections causing duplicate visual edges [HIGH]

**File:** `client/hooks/useCanvasState.ts:252-269`
**Category:** bug
**Description:** When a user drags from agent A to agent B, `connectNodes` adds A→B to the edge list (line 241), then also updates both A and B to include each other in their `connections` arrays (lines 252–269). This means when the canvas is re-loaded (e.g., after a page refresh), `fetchAgentFiles` will reconstruct edges for BOTH A's connection to B AND B's connection to A, rendering two overlapping edges in the EdgeLayer. The simulation engine handles this with deduplication via `frozenset` in `_build_incoming`, but the UI does not.
**Evidence:**
```typescript
// connectNodes: always adds edge A→B visually (line 241)
dispatch({ type: "ADD_EDGE", edge: { id: uuid(), from, to } });
// Then persists A→B AND B→A to both agents' .connections arrays
if (!agFrom.connections.includes(agTo.id)) { updateAgent(updatedFrom) }
if (!agTo.connections.includes(agFrom.id)) { updateAgent(updatedTo) }
// On reload, load() in useEffect reconstructs edges for BOTH
const agentEdges: Edge[] = agentList.flatMap((a) =>
  a.connections.filter(...).map((toId) => ({ id: uuid(), from: a.id, to: toId }))
```
**Fix:** On reload, deduplicate edges by treating them as an unordered pair, e.g. sort `[from, to]` and use a `Set` of the joined key.
**Auto-fixable:** no.

---

### F-005 — Simulation passes `db` connection AND also creates a trial before the background task [HIGH]

**File:** `server/routes/simulation.py:70`
**Category:** bug
**Description:** `create_trial` is called synchronously inside the request handler using the request-scoped `db` connection (line 70). When the same connection is passed to the background task (F-002 above), the background task calls `create_round`, `record_message`, etc. on the same connection. However, if the connection has been returned to pool between the handler completing and the background task starting, the background task commits data on a connection already owned by a different request, potentially interleaving two simulations' writes.
**Evidence:**
```python
trial_id = await create_trial(db, body.prompt, ...)  # uses request-scoped db
background_tasks.add_task(_run_simulation_background, ..., db, ...)  # same db
```
**Fix:** Part of the same fix as F-002. Open a fresh connection in the background task.
**Auto-fixable:** no.

---

### F-006 — `_generate_needle_fact` silently produces duplicate questions when pool is exhausted [HIGH]

**File:** `server/benchmarks/needlehaystack.py:193-210`
**Category:** bug / undefined-behavior
**Description:** The function retries up to 20 times to find a unique question. When all 20 attempts hit already-used questions, the `for-else` clause regenerates another (also likely duplicate) question and silently adds it. With `_DEMO_AGENT_COUNT=3` and up to 25 unique question combinations (5 organisations × 5 attributes), calling `create_needlehaystack_demo` with `num_needles > ~20` will silently produce duplicate questions that result in multiple agents holding conflicting needles about the same fact.
**Evidence:**
```python
for _ in range(20):
    ...
    if question not in used_questions:
        break
else:  # loop exhausted without finding unique question
    answer = _choice(PEOPLE)
    organisation = _choice(ORGANISATIONS)
    attribute = _choice(ATTRIBUTES)
    question = f"Which person in {organisation} has {attribute}?"
    # No check against used_questions — duplicate silently added
used_questions.add(question)
```
**Fix:** Raise `ValueError` in the `else` branch if the pool is exhausted, or pre-generate all unique (org, attr) combinations and sample without replacement.
**Auto-fixable:** no.

---

### F-007 — Benchmark runner `POST /api/agents/` uses trailing slash with `redirect_slashes=False` [HIGH]

**File:** `server/benchmarks/run.py:99, 159, 165, 169`
**Category:** bug
**Description:** The FastAPI app is configured with `redirect_slashes=False` (index.py:76). The benchmark runner makes requests to `/api/agents/` (with trailing slash), `/api/files/`, `/api/agents/{id}/files/{fid}` etc. With `redirect_slashes=False`, these requests return 404 because the registered routes are `/api/agents`, `/api/files` (no trailing slash). The `r.raise_for_status()` calls will then abort the entire benchmark run.
**Evidence:**
```python
r = client.post("/api/agents/", json=body)   # 404 — app is redirect_slashes=False
r.raise_for_status()
...
r = client.post("/api/files/", json={"name": file_name, "content": chunk})  # 404
```
**Fix:** Remove trailing slashes from all `httpx` calls in `run.py`.
**Auto-fixable:** yes — a simple sed/replace of `"/api/agents/"` → `"/api/agents"` and `"/api/files/"` → `"/api/files"`.

---

### F-008 — Benchmark `_run_simulation` expects a synchronous blocking response but gets "started" immediately [HIGH]

**File:** `server/benchmarks/run.py:130-145, 250-256`
**Category:** bug
**Description:** `_run_simulation` sets `timeout=600.0` and POSTs to `/api/simulation/run`, expecting to block until the simulation completes (as its docstring and the 10-minute timeout imply). The endpoint now returns `{"trial_id": ..., "status": "started"}` immediately (background task). The runner immediately calls `_evaluate` with `sim.get("consensus") or ""` — which is always `""` because the simulation hasn't run yet. This means every benchmark evaluation receives an empty string as the generated answer and will always report `answer_correct=False`.
**Evidence:**
```python
sim = _run_simulation(client, question, rounds)   # returns immediately with status="started"
evaluated = _evaluate(client, benchmark_id, sim.get("consensus") or "")  # always ""
```
**Fix:** The runner must poll `GET /api/history/trials/{trial_id}` until `status == "completed"`, then query messages to extract the final consensus answer. Or restore synchronous mode for the benchmark endpoint.
**Auto-fixable:** no.

---

### F-009 — `BENCHMARKS` in-memory dict grows without bound and is lost on restart [HIGH]

**File:** `server/benchmarks/needlehaystack.py:29`
**Category:** bug / undefined-behavior
**Description:** `BENCHMARKS: dict[str, BenchmarkRecord] = {}` is a module-level dict. Each call to `/benchmark/needlehaystack/create` appends an entry. No eviction, TTL, or size cap exists. In a long-running server, this is an unbounded memory leak. Additionally, if the server restarts, all benchmark IDs are lost — any call to `/benchmark/needlehaystack/evaluate` after a restart returns 404.
**Evidence:**
```python
BENCHMARKS: dict[str, BenchmarkRecord] = {}  # line 29
BENCHMARKS[benchmark_id] = BenchmarkRecord(...)  # line 282, never evicted
```
**Fix:** Use a TTL cache (e.g., `cachetools.TTLCache`) or persist benchmark records in the database. At minimum, cap the dict size (e.g., keep only the last 1000 entries with `collections.OrderedDict`).
**Auto-fixable:** no.

---

### F-010 — `_DEMO_SOURCE_TEMPLATES` has a duplicate filename [HIGH]

**File:** `server/benchmarks/needlehaystack.py:66-79`
**Category:** bug
**Description:** Indices 1 and 2 of `_DEMO_SOURCE_TEMPLATES` both have `"name": "org_structures_2.txt"`. The `create_needlehaystack_demo` endpoint creates knowledge files from these templates with these names. If both files are then used in the same agent context, only one will be retrievable by name via the `files` tool (since file lookup is by name, and both map to different content). The test only checks `.endswith(".txt")` and doesn't catch the collision.
**Evidence:**
```python
_DEMO_SOURCE_TEMPLATES = [
    {"id": "f111...", "name": "org_structures_1.txt", ...},
    {"id": "f222...", "name": "org_structures_2.txt", ...},  # index 1
    {"id": "f333...", "name": "org_structures_2.txt", ...},  # index 2 — DUPLICATE NAME
]
```
**Fix:** Rename index 2 to `"org_structures_3.txt"`.
**Auto-fixable:** yes.

---

### F-011 — `delete_all` endpoint has no authorization — any client can wipe the entire database [HIGH]

**File:** `server/routes/agents.py:226-239`
**Category:** security
**Description:** `DELETE /api/agents` (no `{agent_id}` path param) deletes ALL agents, knowledge files, and simulation history with no authentication requirement beyond having a route. There is no `Depends(use_credentials)`, no confirmation token, no rate limit. Any unauthenticated call (including cross-origin from a malicious page) can permanently destroy all data.
**Evidence:**
```python
@router.delete("", status_code=status.HTTP_204_NO_CONTENT, ...)
async def delete_all(db: DBDep) -> None:  # no Depends(use_credentials), no auth
    for table in (messages, connections, rounds, trials, agents, knowledge_files):
        await db.execute(delete(table))
    await db.commit()
```
**Fix:** At minimum add `dependencies=[Depends(use_credentials)]`. Consider adding a confirmation header or making this endpoint disabled in production.
**Auto-fixable:** no — requires security review.

---

### F-012 — `_DEFAULT_MAX_TOKENS = 1024` is far too small for production agents [MEDIUM]

**File:** `server/llm/anthropic_provider.py:11`, `server/llm/gemini_provider.py:27`, `server/llm/openai_provider.py:14`
**Category:** bug
**Description:** All three independent provider files hardcode `_DEFAULT_MAX_TOKENS = 1024`. For multi-round simulations with long system prompts, rules, and vote instructions, agents will regularly hit this limit mid-sentence, truncating their REASON and VOTE lines. The voting parser `_extract_vote` will then fail to find the VOTE line and return `None`, causing agents to abstain unintentionally.
**Evidence:**
```python
_DEFAULT_MAX_TOKENS = 1024  # anthropic_provider.py:11
_DEFAULT_MAX_TOKENS = 1024  # gemini_provider.py:27
_DEFAULT_MAX_TOKENS = 1024  # openai_provider.py:14
```
**Fix:** Raise to at least 4096 or make this configurable per-agent. Centralise the constant to avoid three separate definitions.
**Auto-fixable:** yes — change the value and centralise.

---

### F-013 — `unused imports` in `server/simulation/__init__.py` [MEDIUM]

**File:** `server/simulation/__init__.py:39-41`
**Category:** unused-import
**Description:** Three symbols are imported but never referenced in the module:
- `uuid` (line 39) — no `uuid.` usage exists anywhere in the file.
- `dataclass` and `field` from `dataclasses` (line 41) — no `@dataclass` decoration or `field()` call exists.
These imports are likely leftovers from a refactoring.
**Evidence:**
```python
import uuid           # never used
from dataclasses import dataclass, field  # never used
```
**Fix:** Remove both import lines.
**Auto-fixable:** yes — ruff/autoflake will remove them.

---

### F-014 — `SimStep["agent-to-source"]` type is dead — never set by `historyMessageToStep` [MEDIUM]

**File:** `client/hooks/useSimulation.ts:24-44`, `client/lib/types.ts:7`
**Category:** dead-code
**Description:** `SimStepType` includes `"agent-to-source"`. `historyMessageToStep` only emits `"tool"`, `"agent-to-agent"`, or `"system"`. The `"agent-to-source"` branch in `typeColor` (log-wall.tsx) and `typeIcon` is therefore unreachable dead code.
**Evidence:**
```typescript
// types.ts
export type SimStepType = "system" | "agent-to-agent" | "tool" | "agent-to-source";

// useSimulation.ts historyMessageToStep
const type: SimStep["type"] =
  message.messageType === "tool" ? "tool"
  : isAgentToAgent ? "agent-to-agent"
  : "system";   // "agent-to-source" is never assigned
```
**Fix:** Either implement mapping for agent-to-source messages (e.g. when `message.messageType === "agent_output"` and the to-agent is a source), or remove `"agent-to-source"` from the type union and remove the dead branch in `typeColor`/`typeIcon`.
**Auto-fixable:** no.

---

### F-015 — `console.error` left in production code [MEDIUM]

**File:** `client/components/panels/agent-panel.tsx:59`
**Category:** bug / formatting
**Description:** `fetchModels().then(setAvailableModels).catch(console.error)` logs to the browser console. In production this exposes internal error messages (stack traces, network details) to any user who opens DevTools.
**Evidence:**
```typescript
fetchModels().then(setAvailableModels).catch(console.error);  // line 59
```
**Fix:** Replace with a silent catch or a controlled error state:
```typescript
fetchModels().then(setAvailableModels).catch(() => {});
```
**Auto-fixable:** yes.

---

### F-016 — `gpt-4.1-nano` default model in `OpenAIPromptRequest` doesn't exist in the models list [MEDIUM]

**File:** `server/schemas/__init__.py:257-266`
**Category:** api-mismatch
**Description:** `_OPENAI_DEFAULT_MODEL = "gpt-4.1-nano"` is used as the default `model` in `OpenAIPromptRequest`. The `MODELS` list in `models.py` contains `gpt-4.1` and `gpt-4.1-mini` (SAP_SUPPORTED_MODELS) but no `gpt-4.1-nano`. Calling `POST /api/test/openai` without specifying a model will attempt to use `gpt-4.1-nano` which will be rejected by the OpenAI API.
**Evidence:**
```python
_OPENAI_DEFAULT_MODEL = "gpt-4.1-nano"  # not in MODELS or SAP_SUPPORTED_MODELS
class OpenAIPromptRequest(BaseModel):
    model: str = Field(_OPENAI_DEFAULT_MODEL, ...)  # broken default
```
**Fix:** Change `_OPENAI_DEFAULT_MODEL` to `"gpt-4o-mini"` which is in the MODELS list and is universally available.
**Auto-fixable:** yes.

---

### F-017 — `gpt-5` and `gpt-5-mini` are duplicated between `MODELS` and `SAP_SUPPORTED_MODELS` [MEDIUM]

**File:** `server/routes/models.py:38-42, 161-167`
**Category:** bug / duplicate
**Description:** `Model(id="gpt-5", ...)` and `Model(id="gpt-5-mini", ...)` appear in both `MODELS` (lines 38, 32) and `SAP_SUPPORTED_MODELS` (lines 161, 167). When `creds.resolve_base_url(provider)` returns `None` (standard OpenAI), `list_models()` returns models from `MODELS` only, which is correct. But the duplication means that if the business logic ever changes, both lists must be kept in sync, and the duplication creates confusion about which is the source of truth.
**Evidence:**
```python
MODELS = [..., Model(id="gpt-5", ...), Model(id="gpt-5-mini", ...), ...]
SAP_SUPPORTED_MODELS = [..., Model(id="gpt-5", ...), Model(id="gpt-5-mini", ...), ...]
```
**Fix:** Remove `gpt-5` and `gpt-5-mini` from `SAP_SUPPORTED_MODELS`, or deduplicate the lists by using a shared base and extending.
**Auto-fixable:** no — requires review of which models the SAP proxy actually supports.

---

### F-018 — `_run_tests` in `pre-commit-formatter.py` accepts unused `uv` parameter [MEDIUM]

**File:** `scripts/pre-commit-formatter.py:311`
**Category:** dead-code
**Description:** `_run_tests(repo_root: str, uv: str)` accepts `uv` but never uses it inside the function body. The `pytest_bin` is hardcoded as a path under `server/.venv/bin/pytest`. The `uv` parameter was likely intended for running pytest via `uv run pytest` but was never wired up.
**Evidence:**
```python
def _run_tests(repo_root: str, uv: str) -> tuple[bool, str, str]:
    ...
    pytest_bin = os.path.join(repo_root, "server", ".venv", "bin", "pytest")
    proc = subprocess.run([pytest_bin, ...])  # uv is never referenced
```
**Fix:** Either remove the `uv` parameter and update the call site, or use `uv` to invoke pytest: `[uv, "run", "--project", server_dir, "pytest", ...]`.
**Auto-fixable:** no — intent unclear.

---

### F-019 — Pre-commit script hardcodes `server/.venv/bin/pytest` — breaks on non-Unix or different venv name [MEDIUM]

**File:** `scripts/pre-commit-formatter.py:322`
**Category:** bug
**Description:** `pytest_bin = os.path.join(repo_root, "server", ".venv", "bin", "pytest")` uses a hardcoded Unix path. On Windows this would be `Scripts/pytest.exe`. If `pytest` is not installed (e.g., the venv doesn't exist), `subprocess.run` will raise `FileNotFoundError` — an unhandled exception that crashes the formatter with no user-friendly message.
**Evidence:**
```python
pytest_bin = os.path.join(repo_root, "server", ".venv", "bin", "pytest")
proc = subprocess.run([pytest_bin, ...])  # no existence check, no try/except
```
**Fix:** Check `os.path.isfile(pytest_bin)` and return early with a warning if missing. Or use the `uv` parameter already accepted by the function.
**Auto-fixable:** no.

---

### F-020 — `saveAgent` in `useCanvasState` performs optimistic local update on API failure, diverging client/server state [MEDIUM]

**File:** `client/hooks/useCanvasState.ts:183-208`
**Category:** bug / undefined-behavior
**Description:** In the `catch` block of `saveAgent`, if `updateAgent` or `createAgent` fails, the code still dispatches `UPDATE_AGENT` or `ADD_AGENT` with the locally-modified data. This means the client renders state that the server never acknowledged. After a page refresh, the server's stale state will overwrite the client's optimistic changes, causing the user to silently lose their edits.
**Evidence:**
```typescript
} catch {
  if (exists) {
    dispatch({ type: "UPDATE_AGENT", agent: data });  // optimistic update on failure
    ...
  } else {
    dispatch({ type: "ADD_AGENT", agent: data });  // adds agent that doesn't exist in DB
    ...
  }
}
```
**Fix:** In the catch block, either show an error notification and revert optimistic state, or do not dispatch any action and re-throw the error to the caller.
**Auto-fixable:** no.

---

### F-021 — `saveSource` fire-and-forget silently drops API errors for new sources [MEDIUM]

**File:** `client/hooks/useCanvasState.ts:221-232`
**Category:** missing-error-handling
**Description:** For a new source, `createFile(data.name, data.content, data.id).catch(() => {})` swallows all errors. If the API call fails, the source is shown locally but doesn't exist in the database. On the next simulation run, the agent's knowledge file won't be available. Similarly `updateFileContent` and `deleteFileApi` all swallow errors silently.
**Evidence:**
```typescript
dispatch({ type: "ADD_SOURCE", source: data });
createFile(data.name, data.content, data.id).catch(() => {});  // all errors silently dropped
```
**Fix:** Propagate errors to the UI. At minimum show a toast notification when the API call fails.
**Auto-fixable:** no.

---

### F-022 — `cleanup_stale_data` can delete rounds/trials of non-stale simulations [MEDIUM]

**File:** `server/db/__init__.py:110-111`
**Category:** bug
**Description:** The cleanup function deletes rounds that have no remaining connections after removing stale-agent connections. If a trial involves a mix of stale and non-stale agents, the round rows may still have connections for non-stale agents, and the NOT IN subquery correctly preserves them. However, if a trial involved ONLY stale agents, its rounds are deleted — this is intended. But line 111 then deletes trials with no remaining rounds. If a trial was created but its agents were deleted separately (e.g., via the API), the trial record will be orphaned and then deleted here silently, losing simulation history unexpectedly.
**Evidence:**
```python
await conn.execute(delete(rounds).where(rounds.c.id.not_in(select(connections.c.round_id))))
await conn.execute(delete(trials).where(trials.c.id.not_in(select(rounds.c.trial_id))))
# rounds.c.round_id can be NULL (nullable FK), making the NOT IN subquery
# potentially exclude all rows when any NULL exists in connections
```
**Fix:** Ensure `connections.c.round_id` is never NULL, or use `IS NOT NULL` filter in the subquery: `select(connections.c.round_id).where(connections.c.round_id.isnot(None))`.
**Auto-fixable:** no.

---

### F-023 — `GroqProvider._append_assistant_and_tool_results` does not guard against `None` tool_calls [MEDIUM]

**File:** `server/llm/groq_provider.py:51`
**Category:** bug / undefined-behavior
**Description:** `[tc.model_dump() for tc in message.tool_calls]` will raise `TypeError: 'NoneType' is not iterable` if `message.tool_calls` is `None`. While the base class's loop only calls this method after `_extract_tool_calls` returns a non-empty list, direct calls or future refactoring could hit this path. The `OpenAIProvider._append` avoids this by using `message.model_dump()` which serialises the full message object.
**Evidence:**
```python
messages.append({
    "role": "assistant",
    "content": message.content,
    "tool_calls": [tc.model_dump() for tc in message.tool_calls],  # TypeError if None
})
```
**Fix:**
```python
"tool_calls": [tc.model_dump() for tc in (message.tool_calls or [])],
```
**Auto-fixable:** yes.

---

### F-024 — Benchmark router prefix `/benchmark/...` is not covered by Next.js rewrites [MEDIUM]

**File:** `client/next.config.ts:10-14`, `server/benchmarks/needlehaystack.py:27`
**Category:** api-mismatch
**Description:** `next.config.ts` only rewrites `/api/:path*` to the backend. The benchmark router uses prefix `/benchmark/needlehaystack` (not under `/api`). Any browser-side call to these routes will receive a 404 from Next.js, not the backend. Currently the frontend doesn't call benchmark routes directly (the runner script is CLI-only), but if the frontend ever needs to (e.g., demo import flows), it would fail silently.
**Evidence:**
```typescript
// next.config.ts — only /api/* is proxied
{ source: "/api/:path*", destination: `${internalApiUrl}/api/:path*` }
// But benchmark router has prefix:
router = APIRouter(prefix="/benchmark/needlehaystack", ...)
```
**Fix:** Add a rewrite rule for `/benchmark/:path*` in `next.config.ts`, or move the benchmark router under `/api/benchmark/...`.
**Auto-fixable:** yes for next.config.ts change.

---

### F-025 — `historyMessageToStep` in `useSimulation` uses non-deterministic edge matching [MEDIUM]

**File:** `client/hooks/useSimulation.ts:73-80`
**Category:** bug
**Description:** When finding the active edge, the code matches on `(e.from === s.fromId && e.to === s.toId) || (e.from === s.toId && e.to === s.fromId)`. Since `connectNodes` creates bidirectional edges in the DB but only one directed visual edge in the `edges` array (the drag direction), the reverse-direction lookup may find no matching edge when an agent responds back to its sender, leaving `activeEdge` as `null` and no highlight shown in the UI.
**Evidence:**
```typescript
const e = edges.find(
  (e) =>
    (e.from === s.fromId && e.to === s.toId) ||
    (e.from === s.toId && e.to === s.fromId),  // may not exist if only one direction stored
);
setActEdge(e ? e.id : null);  // silently no highlight
```
**Fix:** Normalise edge direction in the reducer or ensure both directed edges are always stored and rendered.
**Auto-fixable:** no.

---

### F-026 — `_VOTE_INSTRUCTION` has a missing newline in the "none" example [MEDIUM]

**File:** `server/simulation/__init__.py:158-169`
**Category:** bug / formatting
**Description:** The string `_VOTE_INSTRUCTION` is missing a newline between the "unknown" example closing line and the "none" example opening text. The two instructions are concatenated without separation, producing a malformed instruction that confuses the model.
**Evidence:**
```python
"if you dont think there is a correct answer, vote with: none"
"Examples:\n"   # missing "\n" before this — runs directly onto prev line
```
The concatenated result at runtime: `"...vote with: noneExamples:\n..."`.
**Fix:** Add `"\n"` at end of the `"if you dont think..."` line:
```python
"if you dont think there is a correct answer, vote with: none\n"
```
**Auto-fixable:** yes.

---

### F-027 — `_build_incoming` treats agent connections as undirected, ignoring the directed semantics [MEDIUM]

**File:** `server/simulation/__init__.py:270-285`
**Category:** bug
**Description:** The docstring says "Build the undirected adjacency dict". The `connections` field on each agent is documented as "UUIDs of agents this agent **may delegate work to**" — which is directed (A→B means A sends to B, not that B sends to A). By deduplicating with `frozenset` and adding both `incoming[target_id].append(agent["id"])` and `incoming[agent["id"]].append(target_id)`, the engine makes every connection bidirectional. This means if only A has B in its connections list, B will still receive A's messages AND A will receive B's messages — violating the stated directed semantics.
**Evidence:**
```python
seen.add(pair)
incoming[target_id].append(agent["id"])  # B receives from A
incoming[agent["id"]].append(target_id)  # A receives from B — unexpected for directed graph
```
**Fix:** Remove the bidirectional logic. Only add `incoming[target_id].append(agent["id"])`. Update the docstring and UI to make directed edges explicit.
**Auto-fixable:** no — significant behavioral change.

---

### F-028 — `useSimulation.runSim` does not cancel the polling loop when `stopSim` is called mid-poll [MEDIUM]

**File:** `client/hooks/useSimulation.ts:119-143`
**Category:** bug / undefined-behavior
**Description:** The `while (!complete && runSeqRef.current === runSeq)` loop polls `fetchHistoryMessages` and `fetchHistoryTrial`. The 750ms sleep uses `new Promise<void>((r) => setTimeout(r, 750))`. If `stopSim` is called during the sleep, `runSeqRef.current` is incremented. On the next iteration the condition `runSeqRef.current === runSeq` is false and the loop exits — correct. However, if `stopSim` is called while `fetchHistoryMessages` or `fetchHistoryTrial` is awaiting (in-flight HTTP), those promises are not cancelled. The in-flight responses will resolve and `setSteps` / `setOutcome` will be called with stale data, potentially causing a React state update on an unmounted or reset component.
**Evidence:**
```typescript
while (!complete && runSeqRef.current === runSeq) {
  const messages = await fetchHistoryMessages(...);  // in-flight, not cancellable
  ...
  setSteps((prev) => { ... });  // called even if runSeq changed during await
}
```
**Fix:** Check `runSeqRef.current === runSeq` immediately after each `await` call before dispatching any state updates.
**Auto-fixable:** yes — add guard checks after each `await`.

---

### F-029 — `app.tsx` shows "Space → pan" keyboard hint but Space panning is not implemented in `app.tsx` [MEDIUM]

**File:** `client/components/app.tsx:599-603`
**Category:** bug
**Description:** The on-canvas hint bar shows `["Space", "pan"]` as a keyboard shortcut. The Space pan is implemented in `canvas/index.tsx` (using `spaceDown` ref + `canvasMouseDown` check), but `app.tsx`'s `onKeyDown` handler (lines 157-198) does not handle Space at all. If the user is focused on the app level (not on the canvas), Space does not trigger panning.
**Evidence:**
```typescript
// app.tsx line 599-603 — hint shown
["Space", "pan"],
// app.tsx onKeyDown does NOT handle Space
if (e.key === "Escape") { ... }
if (e.key === "Delete" || e.key === "Backspace") { ... }
// No Space case
```
**Fix:** The hint is technically accurate when the canvas element has focus, but it's misleading at the app level. Clarify in the hint or move Space handling to the canvas only, removing it from the app-level hint.
**Auto-fixable:** no.

---

### F-030 — `Tweaks` state in `app.tsx` is immutable — the UI offers no way to change visual tweaks [MEDIUM]

**File:** `client/components/app.tsx:46`
**Category:** dead-code
**Description:** `const [tweaks] = useState<Tweaks>(defaultTweaks)` uses array destructuring without the setter, so `tweaks` is locked to `defaultTweaks` for the lifetime of the component. The `TweaksPanel` component receives `rules` and `selectedRules` props but not `tweaks` or a setter, meaning the visual tweaks (node size, edge width, grid density, particle speed, etc.) defined in the `Tweaks` type can never be changed by the user through the UI.
**Evidence:**
```typescript
const [tweaks] = useState<Tweaks>(defaultTweaks);  // no setter
// TweaksPanel does not accept tweaks props
<TweaksPanel rules={rules} selectedRules={selectedRules} onToggleRule={toggleRule} onClose={...} />
```
**Fix:** Either remove the tweaks feature entirely (delete `Tweaks` type, the `tweaks` prop from Canvas/AgentNode/SourceNode/EdgeLayer), or add tweak controls to `TweaksPanel` and expose a setter.
**Auto-fixable:** no.

---

### F-031 — `MarkdownRenderer` renders arbitrary external images with no Content Security Policy [MEDIUM]

**File:** `client/components/markdown-renderer.tsx:339-356`
**Category:** security
**Description:** The `img` component renderer uses a plain `<img src={src} />` which renders any URL from the markdown content, including tracking pixels, SSRF-triggering private-network URLs, or content from malicious domains. While `rehype-sanitize` is applied (which helps with XSS), it does not block image loading from arbitrary external origins.
**Evidence:**
```tsx
img: ({ src, alt }) => (
  <img src={src} alt={alt ?? ""} ... loading="lazy" />
  // src is from untrusted user content (agent LLM responses)
)
```
**Fix:** Set a Content Security Policy header (`img-src 'self' data: https:`) or add a URL allowlist check before rendering the image. At minimum, remove the `img` override and let `rehype-sanitize` strip images entirely.
**Auto-fixable:** no.

---

### F-032 — `useCanvasState` initial load swallows all errors silently [MEDIUM]

**File:** `client/hooks/useCanvasState.ts:150`
**Category:** missing-error-handling
**Description:** `load().catch(() => {})` silently discards all errors from the initial canvas load (agent fetch, file fetch, agent-file relationship fetch). If the backend is unavailable, the canvas will silently render empty with no indication to the user.
**Evidence:**
```typescript
load().catch(() => {});  // all network errors silently swallowed on initial load
```
**Fix:** Surface the error to the user, at minimum with a toast or error state.
**Auto-fixable:** no.

---

### F-033 — `AgentPanel` lists connections by raw UUID with truncated `shortId` — no usability but also no validation [LOW]

**File:** `client/components/panels/agent-panel.tsx:128-140`
**Category:** bug
**Description:** The `addConn` function in `AgentPanel` appends whatever string is typed in `connIn` directly to `form.connections` with no validation that it is a valid agent ID. Any string (including typos, empty spaces after trim, or arbitrary IDs) can be added. The connection will be persisted to the backend and the agent's `connections` array will contain invalid UUIDs, causing silent failures in simulation topology building.
**Evidence:**
```typescript
const addConn = () => {
  const val = connIn.trim();
  if (val && !form.connections.includes(val)) {
    set("connections", [...form.connections, val]);  // no UUID validation
```
**Fix:** Validate that `val` is a UUID of an existing agent (check against `agents` prop), or replace the text input with a searchable dropdown of current agents.
**Auto-fixable:** no.

---

### F-034 — `TOOL_ICON` map in `icons.tsx` has no entry for the only registered tool `"files"` [LOW]

**File:** `client/lib/icons.tsx:4-11`
**Category:** dead-code / formatting
**Description:** `TOOL_ICON` maps display names like `"Web Search"` → `"Globe"`, but the only tool registered in the registry is `"files"`. Tool icons in `AgentPanel` and `AgentNode` use `TOOL_ICON[tool] || "Wrench"` — so `"files"` always falls through to the `"Wrench"` default. The declared entries (`"Web Search"`, `"Database Query"`, etc.) are dead code that map to tools that don't exist.
**Evidence:**
```typescript
export const TOOL_ICON: Record<string, string> = {
  "Web Search": "Globe",      // tool "Web Search" is not registered
  "Database Query": "Database",  // tool "Database Query" is not registered
  ...
  // "files": missing — the only actual tool
};
```
**Fix:** Add `"files": "FileText"` to `TOOL_ICON` and remove the entries for non-existent tools.
**Auto-fixable:** yes.

---

### F-035 — `pre-commit-formatter.py` imports `shutil` inside `_find_uv` function body [LOW]

**File:** `scripts/pre-commit-formatter.py:289`
**Category:** formatting
**Description:** `import shutil` is placed inside `_find_uv()` rather than at the module top level. This is an unusual pattern, not idiomatic Python, and prevents static analysis tools from detecting the import at a glance.
**Evidence:**
```python
def _find_uv() -> str:
    import shutil   # should be at module top level
    if found := shutil.which("uv"):
```
**Fix:** Move `import shutil` to the top of the file with the other standard library imports.
**Auto-fixable:** yes.

---

### F-036 — `_find_uv` returns `"uv"` as a last resort, silently relying on PATH [LOW]

**File:** `scripts/pre-commit-formatter.py:300`
**Category:** undefined-behavior
**Description:** `_find_uv` returns the bare string `"uv"` if `shutil.which` and the two candidate paths all fail. This means `subprocess.run(["uv", ...])` will rely on `PATH` resolution. In CI environments where `uv` is not installed or not on `PATH`, this silently uses whatever `uv` is found first (or raises `FileNotFoundError`).
**Evidence:**
```python
return "uv"  # fallback to PATH — may find the wrong executable or raise
```
**Fix:** Raise `RuntimeError("uv not found — install it from https://github.com/astral-sh/uv")` instead of returning the bare string.
**Auto-fixable:** yes.

---

### F-037 — `PROVIDERS` dict in `utils.ts` diverges from `MODELS` list in `models.py` [LOW]

**File:** `client/lib/utils.ts:19-61`
**Category:** api-mismatch
**Description:** The client hardcodes a static list of models per provider in `PROVIDERS`. This list diverges from the backend's dynamic `MODELS`/`SAP_SUPPORTED_MODELS` lists. For example, the client lists `gemini-2.0-flash` and `gemini-2.5-flash-preview-05-20`, while the backend lists `gemini-2.5-flash`. The `AgentPanel` now fetches models dynamically via `fetchModels()` and uses those — but `PROVIDERS` in `utils.ts` is still used as the static fallback. If the API is unavailable at panel open time, the user sees stale model options.
**Evidence:**
```typescript
// utils.ts
gemini: { models: [
  { label: "Gemini 2.0 Flash", value: "gemini-2.0-flash" },
  { label: "Gemini 2.5 Flash", value: "gemini-2.5-flash-preview-05-20" },  // wrong ID
```
vs
```python
# models.py
Model(id="gemini-2.5-flash", ...)  # different ID
```
**Fix:** Remove the hardcoded model lists from `utils.ts` `PROVIDERS`. The `AgentPanel` should always use the dynamically fetched list. Keep provider-level metadata (label) but drop model arrays.
**Auto-fixable:** no.

---

### F-038 — `ContextMenu` uses `mousedown` to close but context items use `click` — rapid clicks can skip close [LOW]

**File:** `client/components/context-menu.tsx:28-35`
**Category:** bug
**Description:** The close handler listens for `mousedown` outside the menu. Context item buttons fire `click` which occurs after `mousedown`. When clicking outside, `mousedown` fires first and calls `onClose()`, which unmounts the menu before `click` fires. This is correct for the dismiss case. However, when rapidly double-clicking an item, the second click fires after the first click's `item.fn()` + `onClose()` sequence, potentially triggering the parent canvas's `onClick` handler with unintended behaviour.
**Evidence:**
```typescript
window.addEventListener("mousedown", handler);  // closes on mousedown outside
// items fire: item.fn(); onClose();  // via click — correct order
```
**Fix:** Minor — use `click` for the outside-dismiss listener to match the item interaction model. Or add `e.stopPropagation()` on the context menu container for `click` events.
**Auto-fixable:** no.

---

### F-039 — `test_simulation.py` imports private internal functions directly [LOW]

**File:** `server/tests/test_simulation.py:6`
**Category:** test-quality
**Description:** `from server.simulation import _extract_reason, _extract_vote, _tally` imports private (underscore-prefixed) functions. This tightly couples the tests to implementation details. If these functions are renamed or inlined, the tests break even if external behaviour is unchanged.
**Evidence:**
```python
from server.simulation import _extract_reason, _extract_vote, _tally
```
**Fix:** Either expose these as public helpers with a stable contract (e.g., move to a `voting_utils.py` module), or test them indirectly through the simulation API.
**Auto-fixable:** no.

---

### F-040 — `test_use_credentials_sets_and_resets` tests undefined generator cleanup behavior [LOW]

**File:** `server/tests/test_credentials.py:79-97`
**Category:** test-quality
**Description:** The test manually calls `await gen.__anext__()` twice to drive the `use_credentials` async generator. On the second call it expects `StopAsyncIteration`, then asserts the context var is reset. This works but is fragile — it relies on the generator's internal cleanup (the `finally` block) running during `StopAsyncIteration`. If the generator is refactored to an `async def` with explicit cleanup, this test pattern would silently skip the finally block and pass incorrectly.
**Evidence:**
```python
await gen.__anext__()
assert current_credentials().resolve_key("openai") == "sk-ctx"
with pytest.raises(StopAsyncIteration):
    await gen.__anext__()  # triggers finally — works today but fragile
```
**Fix:** Use `async with` or call `await gen.aclose()` explicitly after asserting the set state. This tests cleanup correctly regardless of generator implementation.
**Auto-fixable:** no.

---

## Additional Structural Note

**Files listed in the audit scope that do not exist on disk:**

The following files were listed in the audit request but are absent from the repository:
- `server/swarm/blackboard.py`
- `server/swarm/schemas.py`
- `api/swarm/blackboard.py`
- `api/swarm/schemas.py`
- `server/tests/test_blackboard.py`
- `server/tests/test_schema.py`
- `client/hooks/useBlackboard.ts`
- `client/components/blackboard-panel.tsx`
- `client/components/canvas/swarm-nodes.tsx`
- `client/components/swarm-activity-log.tsx`
- `client/components/confirmed-section.tsx`
- `client/components/draft-entry.tsx`
- `client/components/draft-section.tsx`
- `client/components/mode-gate.tsx`

These appear to be remnants of a `feat/79-blackboard` feature branch that was partially integrated. No dangling imports reference these files from existing code. The `BENCHMARKS` export in `server/benchmarks/__init__.py` is the only live module that exports a symbol (`BENCHMARKS`) beyond its router; this symbol is not consumed anywhere outside its own package.
