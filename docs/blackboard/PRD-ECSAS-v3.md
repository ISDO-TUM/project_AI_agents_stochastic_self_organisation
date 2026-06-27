# Product Requirements & Software Requirements Specification

## Emergent Consensus via Stochastic Agent Swarms — Version 3.0

> **Architecture Codename:** ECSAS
> **Baseline:** V0 — `project_AI_agents_stochastic_self_organisation` (this repository)
> **Status:** Final — ready for implementation

---

| Field                | Value                                              |
| -------------------- | -------------------------------------------------- |
| **Document Version** | 3.0                                                |
| **Supersedes**       | PRD-ECSAS v2.0 (docs/PRD-ECSAS.md)                 |
| **Author**           | Mohamed Nejjar (Product Owner / Architecture Lead) |
| **Stakeholders**     | TUM SAP Practical Course supervision               |
| **Course Window**    | May – July 2026 (≈ 12 weeks)                       |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Baseline Audit & Integration Strategy](#2-baseline-audit--integration-strategy)
3. [Glossary & Conventions](#3-glossary--conventions)
4. [Core Design Principles](#4-core-design-principles)
5. [System Architecture](#5-system-architecture)
6. [Component Specifications](#6-component-specifications)
7. [Data Models & Schema](#7-data-models--schema)
8. [Tool Registry](#8-tool-registry)
9. [Agent Prompt Templates](#9-agent-prompt-templates)
10. [API Surface](#10-api-surface)
11. [End-to-End Flow](#11-end-to-end-flow)
12. [Frontend Specification](#12-frontend-specification)
13. [Engineering Roadmap](#13-engineering-roadmap)
14. [Non-Functional Requirements](#14-non-functional-requirements)
15. [Configuration Constants & Defaults](#15-configuration-constants--defaults)
16. [Open Problems & Risks](#16-open-problems--risks)
17. [Appendices](#17-appendices)

---

# 1. Executive Summary

ECSAS replaces centralized orchestration with a self-organizing swarm. Agents bid on contracts, deliberate on a shared append-only blackboard structured like a Reddit thread, and converge to a ratified answer through citation mechanics — no privileged orchestrator, no judge, no adversarial veto.

The system is built on top of the existing V0 repository (`project_AI_agents_stochastic_self_organisation`), which already delivers a working multi-provider LLM layer, agent CRUD, knowledge files, a visual canvas, and a simulation playground. ECSAS extends this foundation with seven new backend components and an evolved frontend — nothing in V0 is torn down.

**The three architectural pillars:**

- **Free-market bidding** (Hayek): agents self-select into contracts based on their own judgment, not central routing
- **Reddit-like blackboard** (HEARSAY-II): agents coordinate through threaded public posts, not direct messages
- **Citation-based stigmergy** (Grassé): posts that earn citations survive and get confirmed; uncited posts fade and are soft-deleted

---

# 2. Baseline Audit & Integration Strategy

## 2.1 What V0 Delivers (Preserved Unchanged)

| Component                                    | Location                                  | Status                                    |
| -------------------------------------------- | ----------------------------------------- | ----------------------------------------- |
| FastAPI application                          | `server/index.py`                         | ✅ Unchanged                              |
| Agent CRUD REST API                          | `server/routes/agents.py`                 | ✅ Unchanged                              |
| Knowledge Files API                          | `server/routes/files.py`                  | ✅ Unchanged                              |
| LLM provider layer (OpenAI, Anthropic, Groq) | `server/llm/`                             | ✅ Unchanged                              |
| `BaseLLMProvider` + tool-call loop           | `server/llm/base_provider.py`             | ✅ Unchanged                              |
| Tool abstraction (`Tool` ABC)                | `server/tools/base.py`                    | ✅ Unchanged                              |
| Tool registry                                | `server/tools/registry.py`                | ✅ Extended (new tools registered)        |
| Files tool (`FilesTool`)                     | `server/tools/builtin/files.py`           | ✅ Unchanged                              |
| V0 topology simulation                       | `server/topology/__init__.py`             | ✅ Unchanged (preserved as B-02 baseline) |
| Visual canvas (Builder + Simulator)          | `client/components/canvas/`               | ✅ Extended (new node types, new mode)    |
| Agent / Source panels                        | `client/components/panels/`               | ✅ Unchanged                              |
| Log wall                                     | `client/components/log-wall.tsx`          | ✅ Extended (secondary role)              |
| Theme (dark/light, `#8B1A2F`)                | `client/lib/theme.ts`                     | ✅ Unchanged                              |
| Markdown renderer                            | `client/components/markdown-renderer.tsx` | ✅ Unchanged                              |

## 2.2 What Changes

| Change                                           | Scope                           | Reason                                                                                                                        |
| ------------------------------------------------ | ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Persistent store: PostgreSQL via SQLAlchemy Core | `server/db/`                    | Blackboard must persist across request boundaries (Postgres in prod/Docker via `DATABASE_URL`; in-memory SQLite for tests)    |
| `agents` table: two new columns                  | `server/db/tables.py`           | `capability_embedding`, `created_at`                                                                                          |
| Eleven new DB tables                             | `server/db/tables.py`           | swarm_runs, contracts, threads, bids, draft_entries, citations, votes, confirmed_entries, reputation, agent_trust, amendments |
| New module: `server/market_hive/`                | New                             | All ECSAS backend logic (the "market-hive" engine)                                                                            |
| New route: `server/routes/simulation.py`         | New                             | `POST /api/simulation/run` (SSE, mode-dispatched) and blackboard/audit endpoints                                              |
| `useSimulation.ts` refactored                    | `client/hooks/useSimulation.ts` | SSE consumption in Swarm mode; topology mode unchanged                                                                        |
| New frontend components                          | `client/components/`            | BlackboardPanel, ThreadTabs, SwarmConfigModal, new canvas nodes                                                               |
| New canvas mode (Swarm)                          | `client/components/canvas/`     | Market Maker node, Blackboard node, swarm-specific animations                                                                 |

---

# 3. Glossary & Conventions

## 3.1 Domain Terms

| Term                       | Definition                                                                                                                                                                                                                           |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Agent**                  | A specialized LLM instance with a distinct system prompt, provider, model, tools, and knowledge files. The fundamental unit of participation.                                                                                        |
| **Contract**               | A structured representation of one user prompt. Produced by the Market Maker. The atomic unit of work. Every user prompt = one contract.                                                                                             |
| **Thread**                 | A subcontract inside a contract. For single-step tasks: exactly one thread (the contract itself). For multi-step tasks: N threads, each scoping a sub-problem with its own `required_expertise` and `thread_embedding`.              |
| **Market Maker (MM)**      | The entry-layer component that converts raw user prompts into contracts and threads. Advisory, not authoritative — the swarm can propose amendments.                                                                                 |
| **Auction**                | The phase where agents self-select into a contract. The system invites agents above an embedding floor; invited agents decide themselves whether to bid or abstain.                                                                  |
| **Taker**                  | An agent who submitted a bid and was selected (up to `max_takers`). Takers have full read/write blackboard access.                                                                                                                   |
| **Observer**               | An agent who was invited to the auction but lost (or lost at thread level). Receives zero access to the run. Cross-run trust is decremented.                                                                                         |
| **Non-participant**        | An agent below the embedding invitation floor. Never sees the auction. Zero changes.                                                                                                                                                 |
| **Blackboard**             | The shared append-only coordination substrate. Structured as a Reddit thread: each thread has top-level posts (proposals) and nested comments (replies). Two layers: Draft and Confirmed.                                            |
| **Draft Layer**            | The live, evolving discussion. Posts can be soft-deleted after N uncited rounds.                                                                                                                                                     |
| **Confirmed Layer**        | Permanent, ratified findings. Starts with contract/thread anchors. New entries promoted from Draft via citation threshold. Never deleted.                                                                                            |
| **Post**                   | A top-level entry in a thread's Draft layer (round 1 = proposal, rounds 2+ = top-level reply).                                                                                                                                       |
| **Comment**                | A nested entry with a `reply_to` pointing to a parent post or another comment.                                                                                                                                                       |
| **Cite**                   | A tool call endorsing another entry. Means: "I am building on or agreeing with this entry." Citation = positive signal only. Disagreement is expressed through reply content, not citation. Self-citations are filtered server-side. |
| **Vote**                   | A tool call used exclusively in the cold-start vote sub-round (after round 1) to initialize per-agent confidence scores. Votes are not promotion signals — only citations count for promotion.                                       |
| **Mention**                | Tagging a specific agent inside a post via `mention_agents` field. Ensures the mentioned agent sees this entry at the top of their next `read_blackboard` result. Enables cross-thread expertise requests.                           |
| **Citation Threshold (M)** | The number of distinct non-self citations required to promote a Draft entry to Confirmed. `M = max(1, floor(N_thread_participants / 3) + 1)`. Lenient by design.                                                                     |
| **Soft Delete**            | A Draft entry not cited for N rounds has `is_visible = false` set. Agents never see it again (context clean). The entry persists in the DB for audit trail.                                                                          |
| **Pheromone**              | The citation-count signal on a Draft entry. Entries with rising pheromone (accumulating citations) survive and get promoted. Entries with zero pheromone over N rounds are soft-deleted. The blackboard is self-cleaning.            |
| **Confidence Score**       | Per-agent scalar [0.0, 1.0]. Initialized via the vote sub-round. Updated each round as a function of citation share. High confidence = agent's posts are widely cited = agent holds firm.                                            |
| **Conceding Temperature**  | Per-agent. `T = max(1 - confidence, T_floor(round))`. High T = agent is more willing to concede and seek consensus. Injected as graduated natural language into the agent's system prompt.                                           |
| **Contract Amendment**     | An agent-proposed addition to the contract scope, submitted via `request_expertise`. Evaluated by majority vote of existing takers + the Market Maker (equal vote). New threads can be created mid-run.                              |
| **Run**                    | A single end-to-end execution of the swarm for one contract. Has a UUID. All data is scoped to a run_id.                                                                                                                             |
| **Per-run Reputation**     | Agent's domain credibility within a single run. Starts at 0.5. Feeds into conceding temperature. Resets between runs.                                                                                                                |
| **Cross-run Trust**        | Persistent per-agent, per-domain score in `agent_trust` table. Updated at run end. Feeds into bid score. Starts at 0.5 for new agents.                                                                                               |
| **Equilibrium**            | State where zero new non-anchor Confirmed entries are added for K consecutive rounds AND at least `min_rounds` have elapsed.                                                                                                         |
| **Swarm Mode**             | The ECSAS execution mode. Distinct from Topology Mode (V0).                                                                                                                                                                          |
| **Topology Mode**          | The existing V0 simulation. Preserved unchanged as B-02 evaluation baseline.                                                                                                                                                         |

## 3.2 Requirement Conventions

- **MUST** — Hard requirement. System non-conformant if absent.
- **SHOULD** — Strong recommendation.
- **MAY** — Optional.
- `[FR-XX-NN]` — Functional requirement tag.
- `[NFR-XX-NN]` — Non-functional requirement tag.

---

# 4. Core Design Principles

| ID   | Principle                                                                                                                                                                                                 |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P-01 | **No orchestrator.** No agent has routing, decision-making, or termination authority over others.                                                                                                         |
| P-02 | **No judge.** No agent can unilaterally confirm or reject findings. Confirmation is emergent via citation.                                                                                                |
| P-03 | **Append-only write.** No entry is ever mutated after posting. Soft delete = visibility flag only. DB record preserved.                                                                                   |
| P-04 | **Symmetric authority.** All agents — including the Market Maker acting as voter — have equal democratic weight.                                                                                          |
| P-05 | **Agent autonomy.** Agents self-select into contracts. They may abstain. Computation is not forced on unwilling agents.                                                                                   |
| P-06 | **Tools for all side effects.** The LLM generates content. Every interaction with the blackboard (read, post, cite, vote, mention) is a deterministic tool call. Nothing is inferred from free-form text. |
| P-07 | **Reddit-like coordination.** Agents post proposals, reply in nested comments, cite entries they agree with, mention agents they need. The blackboard is a social medium, not a log.                      |
| P-08 | **Citation = endorsement only.** Agents never cite entries they disagree with. Disagreement is expressed through reply content.                                                                           |
| P-09 | **Self-cleaning blackboard.** Entries not cited for N rounds are soft-deleted. Agents operate on a lean, relevant context window.                                                                         |
| P-10 | **Backward compatibility.** V0 topology simulation is preserved, unchanged, as the B-02 baseline.                                                                                                         |
| P-11 | **Auditability by construction.** Soft-deleted entries remain in DB. Full audit trail exportable at any time.                                                                                             |

---

# 5. System Architecture

## 5.1 Dual Execution Mode

| Mode              | Engine                                           | Trigger                                 |
| ----------------- | ------------------------------------------------ | --------------------------------------- |
| **Topology (V0)** | `server/topology/__init__.py:run_topology()`     | Mode selector = "Topology" in PromptBar |
| **Swarm (ECSAS)** | `server/market_hive/orchestrator.py:run_swarm()` | Mode selector = "Swarm" in PromptBar    |

Both modes stream `SimulationStep` events via SSE from `POST /api/simulation/run`. The `mode` field in the request body selects the engine.

## 5.2 The Seven ECSAS Backend Components

| Component          | Module                               | Responsibility                                                             |
| ------------------ | ------------------------------------ | -------------------------------------------------------------------------- |
| Market Maker       | `server/market_hive/market_maker.py` | Prompt → Contract + Threads. Votes on amendments.                          |
| Auction Engine     | `server/market_hive/auction.py`      | Invites agents, manages self-selection, assigns takers to threads.         |
| Blackboard         | `server/market_hive/blackboard.py`   | Append-only storage, attention queries, soft delete, citation tracking.    |
| Convergence Engine | `server/market_hive/convergence.py`  | Promotion logic, citation threshold checks, temperature updates.           |
| Contract Amendment | `server/market_hive/amendment.py`    | Handles `request_expertise` proposals, majority vote, new thread creation. |
| Termination Engine | `server/market_hive/termination.py`  | Equilibrium detection, budget tracking, final output selection.            |
| Trust Registry     | `server/market_hive/trust.py`        | Cross-run `agent_trust` updates at run end.                                |

## 5.3 Information Flow

```
USER PROMPT
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ MARKET MAKER                                                 │
│ prompt → Contract (task_type, task_nature, required_        │
│          expertise, complexity, confidence)                  │
│ if multi-step: → N Threads (each with full metadata)        │
│ Contract + Threads → Confirmed Layer as permanent ANCHORS   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ AUCTION ENGINE                                               │
│ 1. Compute preliminary embedding scores for all agents      │
│ 2. Invite agents above INVITE_FLOOR (default 0.3)           │
│ 3. Invited agents call submit_bid() or abstain()            │
│ 4. Takers selected (quorum + min/max enforcement)           │
│ 5. Multi-step: each taker bids per thread (explicit choice) │
│    → Every thread must have ≥ 1 taker                       │
│    → If thread has 0 bids: auto-trigger request_expertise   │
│ 6. Bid-and-lost agents become observers (no run access,     │
│    cross-run trust decremented at end)                      │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ ROUND 1 — OPENING PROPOSALS                                  │
│ All takers (parallel, per thread):                          │
│ 1. read_blackboard() → see contract/thread anchors          │
│ 2. [optional] files(), other knowledge tools                │
│ 3. post_to_blackboard(entry_type="proposal", ...)           │
│    Content: capability declaration + initial answer +       │
│             tools/sources used + reasoning                   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ VOTE SUB-ROUND (between rounds 1 and 2)                      │
│ Each taker reviews all round-1 proposals in their threads.  │
│ Calls vote(entry_id) for each proposal they endorse.        │
│ System computes:                                             │
│   confidence_0[agent] = votes_received / (N_participants-1) │
│   T_0[agent] = max(1 - confidence_0, T_floor(1))            │
│ (Votes are NOT promotion signals — only citations are)      │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ ROUNDS 2 → max_rounds                                        │
│ Each round, each taker (parallel, per thread):              │
│ 1. read_blackboard(query) → top-K relevant visible entries  │
│    [compact summary pre-loaded in initial prompt]           │
│ 2. Generate analysis                                         │
│ 3. post_to_blackboard(content, reply_to, "reply",           │
│                        thread_id, mention_agents)           │
│ 4. cite(entry_ids) → endorse entries being built on         │
│ 5. [optional] request_expertise(domain, reason, thread_id)  │
│                                                              │
│ End-of-round system actions:                                 │
│ 1. Check promotion: entries with M distinct citations        │
│    → promoted to Confirmed layer                            │
│ 2. Soft-delete: entries with 0 citations for N rounds        │
│    → is_visible=false, deleted_at set                       │
│ 3. Recompute confidence per agent                           │
│    confidence[agent] = agent_citations / total_round_cites  │
│ 4. Update conceding temperature                             │
│    T[agent] = max(1-confidence[agent], T_floor(round))      │
│ 5. Update per-run reputation                                │
│ 6. Check contract amendments (if any request_expertise      │
│    calls made — see Amendment Engine)                       │
│ 7. Check equilibrium                                        │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ TERMINATION                                                  │
│ Equilibrium condition:                                       │
│   new Confirmed entries == 0 for K consecutive rounds       │
│   AND current_round >= min_rounds                           │
│ OR max_rounds reached OR token_budget exhausted             │
│                                                              │
│ FINAL OUTPUT (per thread):                                   │
│   Most-cited non-anchor Confirmed entry for that thread.    │
│   Tie-break: earliest round_confirmed.                      │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ TRUST REGISTRY UPDATE                                        │
│ For each taker: trust_score[domain] += δ_winner_gain        │
│ For each observer: trust_score[domain] -= δ_observer_loss   │
│ Proportional to citation share of confirmed findings.       │
└─────────────────────────────────────────────────────────────┘
```

---

# 6. Component Specifications

## 6.1 Market Maker

**Module:** `server/market_hive/market_maker.py`

**Responsibilities:**

1. Convert raw user prompt → `Contract` via structured LLM call
2. For multi-step tasks: decompose into `Thread` list, each with full metadata
3. Return a fallback contract (`confidence=0.0`) on LLM failure — never block the run
4. Cast one democratic vote on contract amendment proposals (equal weight to taker agents)

**Interface:**

```python
class MarketMaker:
    async def make_contract(self, raw_prompt: str, run_id: str) -> tuple[Contract, list[Thread]]: ...
    async def cast_amendment_vote(self, amendment: AmendmentProposal) -> Literal["approve", "reject"]: ...
```

**Contract production:**

- Calls existing `call_agent()` with a structured-output system prompt
- Validates output against `Contract` Pydantic schema
- For multi-step: produces threads with `required_expertise`, `complexity`, `description`, `thread_embedding`
- All produced objects are immediately persisted to DB and posted to Confirmed layer as anchors

**Single point of failure mitigation:**

- Fallback contract on failure: `task_nature="single"`, `confidence=0.0`, one thread
- Agents can propose contract amendments via `request_expertise` tool
- The MM is ONE vote among equals when amendments are proposed

---

## 6.2 Auction Engine

**Module:** `server/market_hive/auction.py`

**Phase 1 — Invitation (server-side, no LLM):**

```
For each agent in DB:
    preliminary_score = cosine(agent.capability_embedding, contract.contract_embedding)
    if preliminary_score >= INVITE_FLOOR (default 0.3):
        invite agent to auction
```

**Phase 2 — Self-selection (per invited agent, one LLM call):**

Agent receives:

- Compact contract + thread list
- Their preliminary embedding score
- Their `trust_score[task_type]` from `agent_trust` table
- Confirmed anchors via pre-loaded context

Agent may call:

- `read_blackboard()` — reads contract/thread anchors
- `files()` — consults own knowledge
- `submit_bid(justification: str)` — commits to taking the contract
- `abstain(reason: str)` — opts out entirely

**Phase 3 — Taker selection:**

```
bidders = agents who called submit_bid()

if len(bidders) > max_takers:
    takers = top max_takers by preliminary_score

if len(bidders) < min_takers:
    takers = all bidders (even if below quorum)

if len(bidders) == 0:
    emit SSE: "No agents qualified. Run aborted."
    terminate run
```

**Phase 4 — Thread assignment (multi-step only):**

For each taker, for each thread, one LLM call:

- Agent sees thread metadata (title, description, required_expertise)
- Agent calls `submit_bid(thread_id)` or `abstain(thread_id, reason)`

Thread coverage enforcement:

```
for each thread:
    if count(thread_takers) == 0:
        auto-trigger request_expertise for this thread
        mini-auction: all remaining agents invited to bid on this thread only
        if still 0 takers: thread is dissolved (scope merged into parent thread)
```

**Bid scoring formula:**

```python
bid_score = (
    alpha * cosine(capability_embedding, contract_embedding)
    + beta  * trust_score[task_type]           # cross-run, persistent
    + gamma * (1 - (1 - contract.confidence))  # market maker confidence
)
```

Default: `alpha=0.5`, `beta=0.4`, `gamma=0.1`. Sum = 1.0.

**Observer designation:**

- Agents invited but who abstained OR lost taker selection → **observers** for this run
- Observers: zero blackboard access, zero LLM calls, dimmed on canvas
- At run end: `trust_score[domain] -= delta_observer_loss` (default 0.02)

---

## 6.3 Blackboard

**Module:** `server/market_hive/blackboard.py`

### Structure

The blackboard is a Reddit-like threaded discussion. Per thread:

```
THREAD: "Pricing Fairness Analysis"  [required_expertise: "contract_law, finance"]
│
│  ┌─── CONFIRMED (sticky, permanent) ─────────────────────────────────┐
│  │  📌 [ANCHOR] Contract: "Analyze this energy contract for..."      │
│  │  📌 [ANCHOR] Thread: "Pricing Fairness Analysis"                  │
│  │  ✅ [CF-003] Round 2, 3 citations: "Section 4.2 is unenforceable" │
│  └────────────────────────────────────────────────────────────────────┘
│
│  ┌─── DRAFT (scrollable, self-cleaning) ──────────────────────────────┐
│  │  [BB-001] Alpha · Round 1 · proposal                              │
│  │  "The penalty clause in §4.2 is ambiguous because..."             │
│  │  👍 3 citations  |  💬 2 replies                                  │
│  │    ↳ [BB-003] Beta · Round 1 · vote                              │
│  │    "Agree — the liquidated damages formula contradicts §7.1"      │
│  │      ↳ [BB-007] Alpha · Round 2 · reply                          │
│  │      "@FinancialAgent, can you verify the DCF assumption here?"   │
│  │  [BB-002] Gamma · Round 1 · proposal  [DIMMED — 2 rounds idle]   │
│  └────────────────────────────────────────────────────────────────────┘
```

### Properties

| Property         | Value                                                                                  |
| ---------------- | -------------------------------------------------------------------------------------- |
| Write semantics  | Append-only. No entry mutated after creation.                                          |
| Delete semantics | Soft delete only: `is_visible=false`, `deleted_at` set. Entry stays in DB.             |
| Agent visibility | Agents only see `is_visible=true` entries via `read_blackboard` tool.                  |
| Audit trail      | All entries (including soft-deleted) returned by `GET /api/simulation/{run_id}/audit`. |
| Threading        | `reply_to` field: entry_id of parent post or null. Fully independent from citations.   |
| Cross-thread     | An agent in Thread 1 may `read_blackboard(thread_id=None)` to search across threads.   |

### Attention Query (used by `read_blackboard` tool)

```python
def top_k_visible(
    query: str,
    thread_id: str | None,
    run_id: str,
    k: int = 10,
) -> list[DraftEntry]:
    entries = db.query(
        "SELECT * FROM draft_entries "
        "WHERE run_id=? AND is_visible=1 "
        "AND (thread_id=? OR ?='cross')",
        ...
    )
    scored = [
        (entry, cosine(embed(query), entry.content_embedding) * entry.citation_count_weight)
        for entry in entries
    ]
    return top_k(scored)
```

`citation_count_weight = log(1 + citation_count)` — cited entries naturally surface higher in attention results, implementing pheromone amplification without a separate influence_weight field.

### Soft Delete Trigger

At end of each round:

```python
for entry in draft_entries_not_cited_this_run:
    rounds_since_citation = current_round - entry.last_cited_round
    if rounds_since_citation >= N_DECAY_ROUNDS:  # default 3
        entry.is_visible = False
        entry.deleted_at = now()
```

Exception: entries in round 1 are exempt from deletion until round 2 has completed (agents need to vote on them first).

### Promotion Check

At end of each round:

```python
for entry in visible_draft_entries:
    distinct_citers = count_distinct_non_self_citations(entry.id, run_id)
    n_participants = count_thread_takers(entry.thread_id, run_id)
    M = max(1, n_participants // 3 + 1)
    if distinct_citers >= M:
        promote_to_confirmed(entry)
```

Promotion creates a `ConfirmedEntry` record and does NOT soft-delete the draft entry (the discussion context is preserved for later rounds).

### Mention Mechanism

When `post_to_blackboard(mention_agents=["agent_id_X"])` is called:

- A system record is created: `{mentioned_agent_id: "X", entry_id: "BB-NNN"}`
- On agent X's next `read_blackboard()` call, `BB-NNN` is pinned to position 0 of results regardless of attention score
- SSE event emitted to frontend: `{ type: "mention", agent_id: "X", entry_id: "BB-NNN" }`

---

## 6.4 Convergence Engine

**Module:** `server/market_hive/convergence.py`

### Confidence Score

**Cold start (vote sub-round after round 1):**

```
confidence_0[agent_i] = votes_received_for_agent_i_round1_post[thread]
                       / (N_thread_participants - 1)
```

**Per round R ≥ 2:**

```
total_citations_this_round[thread] = sum of all cite() calls in round R for this thread
citations_for_agent_i[thread] = cite() calls pointing to entries authored by agent_i

confidence[agent_i][R] = citations_for_agent_i / max(1, total_citations_this_round)
```

Range: [0.0, 1.0]. An agent whose posts are widely cited has high confidence (their view is the consensus). An isolated outlier has low confidence.

**Conceding Temperature:**

```
T_floor(R) = T_initial + (R - 1) * delta_T          # e.g. 0.0 + (R-1) * 0.1
T[agent_i][R] = max(1 - confidence[agent_i][R], T_floor(R))
```

| T range     | Natural language instruction injected                                                              |
| ----------- | -------------------------------------------------------------------------------------------------- |
| 0.00 – 0.25 | "Defend your analysis firmly. Only revise if shown clear, contradicting evidence."                 |
| 0.25 – 0.50 | "Acknowledge valid points from others. Defend your core reasoning but remain open to refinement."  |
| 0.50 – 0.75 | "Actively seek common ground. Revise your position where others present stronger arguments."       |
| 0.75 – 1.00 | "Prioritize consensus. If the majority position is well-supported, align with it and explain why." |

### Per-run Reputation Update

At end of each round:

```
For each agent, for each thread:
    if agent authored an entry promoted to Confirmed this round:
        reputation[agent][domain] += delta_confirm (default 0.05)
    if agent's entry was soft-deleted this round:
        reputation[agent][domain] -= delta_reject  (default 0.03)
    if agent made no post this round (abstained/silent):
        no change

reputation clamped to [0.0, 1.0]
```

---

## 6.5 Contract Amendment Engine

**Module:** `server/market_hive/amendment.py`

**Trigger:** A taker calls `request_expertise(domain, reason, thread_id)`.

**Flow:**

```
1. PROPOSAL POSTED:
   System creates a SYSTEM entry in Confirmed layer (visible to all):
   "[Agent X] requests [domain] expertise for [Thread Y]: [reason]"

2. MAJORITY VOTE:
   All current takers + Market Maker cast votes.
   Each voter calls vote(amendment_entry_id) to approve.
   "Approve" = calling vote(). Silence = abstain (not a rejection).

   approve_count = votes received (including MM's one vote)
   total_voters = N_takers + 1 (the MM)
   approved = approve_count > total_voters / 2

3a. IF APPROVED:
    - New Thread created with the requested domain as required_expertise
    - Mini-auction: all non-taker agents invited if embedding matches new thread
    - New takers join the run from round R+1 onward
    - System entry in Confirmed: "Amendment approved. Thread [new_title] created."

3b. IF REJECTED:
    - System entry in Confirmed: "Amendment rejected. [MM reasoning]."
    - Run continues unchanged.

4. HARD LIMIT:
   max_amendments per run (default 2, UI parameter).
   If limit reached, further request_expertise calls return an error message.
```

---

## 6.6 Termination Engine

**Module:** `server/market_hive/termination.py`

**Equilibrium condition:**

```python
def check_equilibrium(run_id, current_round, config) -> bool:
    if current_round < config.min_rounds:
        return False

    for r in range(current_round - config.k_consecutive, current_round + 1):
        new_confirmed = count_confirmed_this_round(run_id, r, exclude_anchors=True)
        if new_confirmed > config.epsilon_entropy:
            return False
    return True
```

**Budget tracking:**

- `TokenTracker` accumulates across all LLM calls scoped to a run
- At start of each agent turn: check `tracker.remaining() >= MIN_TURN_BUDGET`
- If budget exhausted: graceful halt, termination_reason = "budget"

**Final output selection (per thread):**

```python
def select_final_answer(thread_id, run_id) -> ConfirmedEntry | None:
    findings = confirmed_entries.filter(
        thread_id=thread_id,
        run_id=run_id,
        entry_type="finding",   # exclude anchors
        archived=False
    ).order_by(citation_count DESC, round_confirmed ASC)
    return findings.first()
```

**Output schema:**

```python
class SwarmFinalOutput(BaseModel):
    run_id: str
    answers: dict[str, ConfirmedEntry]   # thread_id → final answer entry
    confirmed_layer: list[ConfirmedEntry]
    termination_round: int
    termination_reason: Literal["equilibrium", "max_rounds", "budget"]
    metadata: dict                        # token usage, latency, agent participation
```

---

## 6.7 Trust Registry

**Module:** `server/market_hive/trust.py`

Called once at run end.

```python
async def update_trust(run_id: str, db: Connection) -> None:
    takers = get_takers(run_id)
    observers = get_observers(run_id)
    domain = get_contract_domain(run_id)

    # Takers: reward proportional to citation share of confirmed findings
    total_confirmed_citations = sum(e.citation_count for e in get_confirmed_findings(run_id))
    for taker in takers:
        taker_share = taker_confirmed_citation_share(taker.id, run_id)
        delta = DELTA_WINNER_GAIN * taker_share
        update_trust_score(taker.id, domain, +delta)

    # Observers: flat penalty
    for observer in observers:
        update_trust_score(observer.id, domain, -DELTA_OBSERVER_LOSS)

    # Clamp all trust scores to [0.0, 1.0]
```

---

# 7. Data Models & Schema

## 7.1 Migration Plan

**MIG-01 — Persistent store (already satisfied):**
The codebase uses **PostgreSQL via SQLAlchemy Core**, configured through `DATABASE_URL`
in `server/db/__init__.py` (Postgres in production/Docker; the test suite points the
same Core schema at an in-memory SQLite database via `conftest.py`). Persistence across
request boundaries and restarts is therefore already provided by Postgres — there is no
`aiosqlite`/`DB_PATH`/`./data/swarm.db` step. The schema is defined once as SQLAlchemy
`Table` objects in `server/db/tables.py` and created on startup via `metadata.create_all`,
with additive `ALTER TABLE … IF NOT EXISTS` guards in `_apply_column_migrations` for
columns added to already-provisioned databases.

**MIG-02 — Agents table additions:**

```sql
ALTER TABLE agents ADD COLUMN capability_embedding TEXT DEFAULT NULL;
ALTER TABLE agents ADD COLUMN created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
```

**MIG-03 — ECSAS tables:**

```sql
-- ── Run bookkeeping ────────────────────────────────────────
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

-- ── Contracts ─────────────────────────────────────────────
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

-- ── Threads (subcontracts) ────────────────────────────────
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

-- ── Bids ─────────────────────────────────────────────────
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

-- ── Draft entries ─────────────────────────────────────────
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

-- ── Citations (cite() tool calls) ────────────────────────
CREATE TABLE IF NOT EXISTS citations (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES swarm_runs(id),
    citing_agent_id     TEXT NOT NULL REFERENCES agents(id),
    cited_entry_id      TEXT NOT NULL REFERENCES draft_entries(id),
    citing_entry_id     TEXT REFERENCES draft_entries(id),
    round               INTEGER NOT NULL,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(citing_agent_id, cited_entry_id, round)  -- one cite per agent per entry per round
);

-- ── Votes (vote() tool calls — cold start only) ──────────
CREATE TABLE IF NOT EXISTS votes (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES swarm_runs(id),
    voter_agent_id      TEXT NOT NULL REFERENCES agents(id),
    voted_entry_id      TEXT NOT NULL REFERENCES draft_entries(id),
    thread_id           TEXT NOT NULL REFERENCES threads(id),
    round               INTEGER NOT NULL DEFAULT 1,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(voter_agent_id, voted_entry_id)  -- one vote per agent per entry
);

-- ── Confirmed entries ─────────────────────────────────────
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

-- ── Per-run reputation ────────────────────────────────────
CREATE TABLE IF NOT EXISTS reputation (
    run_id              TEXT NOT NULL REFERENCES swarm_runs(id),
    agent_id            TEXT NOT NULL REFERENCES agents(id),
    domain              TEXT NOT NULL,
    score               REAL NOT NULL DEFAULT 0.5
                        CHECK(score >= 0.0 AND score <= 1.0),
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, agent_id, domain)
);

-- ── Cross-run trust (persistent) ─────────────────────────
CREATE TABLE IF NOT EXISTS agent_trust (
    agent_id            TEXT NOT NULL REFERENCES agents(id),
    domain              TEXT NOT NULL,
    trust_score         REAL NOT NULL DEFAULT 0.5
                        CHECK(trust_score >= 0.0 AND trust_score <= 1.0),
    runs_participated   INTEGER NOT NULL DEFAULT 0,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (agent_id, domain)
);

-- ── Amendment proposals ───────────────────────────────────
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

-- ── Indexes ───────────────────────────────────────────────
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
```

## 7.2 Pydantic Schemas (`server/market_hive/schemas.py`)

```python
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

# ── Swarm run ─────────────────────────────────────────────────────────
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
    # Advanced (not shown in UI by default)
    invite_floor: float = Field(default=0.3, ge=0.0, le=1.0)
    alpha: float = Field(default=0.5)
    beta: float = Field(default=0.4)
    gamma: float = Field(default=0.1)
    k_attention: int = Field(default=10, ge=3, le=30)
    k_consecutive: int = Field(default=2, ge=1, le=5)
    epsilon_entropy: int = Field(default=0, ge=0)
    t_initial: float = Field(default=0.0)
    delta_t: float = Field(default=0.1)

# ── Contract & Threads ────────────────────────────────────────────────
class ThreadSchema(BaseModel):
    id: str
    contract_id: str
    run_id: str
    title: str
    description: str
    required_expertise: list[str]
    complexity: Literal["low", "medium", "high"]
    thread_embedding: list[float] | None = None
    created_at: datetime

class ContractSchema(BaseModel):
    id: str
    run_id: str
    original_prompt: str
    task_type: str
    task_nature: Literal["single", "multi"]
    required_expertise: list[str]
    complexity: Literal["low", "medium", "high"]
    confidence: float
    contract_embedding: list[float] | None = None
    threads: list[ThreadSchema] = []
    created_at: datetime

# ── Blackboard entries ────────────────────────────────────────────────
class DraftEntrySchema(BaseModel):
    id: str
    run_id: str
    thread_id: str
    round: int
    author_id: str
    author_name: str   # denormalized for frontend display
    entry_type: Literal["proposal", "reply", "vote", "system"]
    content: str
    reply_to: str | None = None
    mention_agents: list[str] = []
    is_visible: bool = True
    deleted_at: datetime | None = None
    last_cited_round: int = 0
    citation_count: int = 0   # computed at query time from citations table
    created_at: datetime
    children: list["DraftEntrySchema"] = []  # for threaded rendering

class ConfirmedEntrySchema(BaseModel):
    id: str
    run_id: str
    thread_id: str
    source_draft_id: str | None = None
    content: str
    entry_type: Literal["anchor", "finding", "system"]
    citation_count: int = 0
    round_confirmed: int
    created_at: datetime

# ── Final output ─────────────────────────────────────────────────────
class SwarmFinalOutput(BaseModel):
    run_id: str
    answers: dict[str, ConfirmedEntrySchema]   # thread_id → final answer
    confirmed_layer: list[ConfirmedEntrySchema]
    termination_round: int
    termination_reason: Literal["equilibrium", "max_rounds", "budget"]
    metadata: dict[str, Any]

# ── Extended SimulationStep types ────────────────────────────────────
SimStepType = Literal[
    # V0 (unchanged)
    "system", "agent-to-agent", "tool", "agent-to-source",
    # ECSAS (new)
    "bid",               # agent submitted a bid
    "abstain",           # agent abstained from auction
    "bb-post",           # post to Draft layer
    "bb-cite",           # cite tool called
    "bb-vote",           # vote tool called (cold start)
    "bb-promote",        # entry promoted to Confirmed
    "bb-delete",         # entry soft-deleted
    "bb-mention",        # agent mentioned by another
    "amendment",         # request_expertise called
    "amendment-approved",
    "amendment-rejected",
    "convergence",       # equilibrium reached, final output
]
```

---

# 8. Tool Registry

All ECSAS tools are registered in `server/tools/registry.py` alongside existing tools.
Each tool follows the existing `Tool` ABC pattern with Pydantic input models and `to_openai()`/`to_anthropic()` adapters.

## 8.1 Complete Tool Catalogue

### `read_blackboard`

```
Purpose:   Query the Draft + Confirmed layers for relevant entries.
Phase:     All phases (auction through final rounds).
Returns:   Top-K entries sorted by (cosine_similarity × log(1+citation_count)).
           Mentions targeting this agent are always pinned to position 0.
Input:
  query:      str          — natural language search query
  thread_id:  str | None   — None for cross-thread search
  k:          int = 10     — max entries to return
Output:   list of { id, content, author_name, round, reply_to, entry_type,
                    thread_title, citation_count, is_confirmed }
```

### `post_to_blackboard`

```
Purpose:   Write a proposal or reply to the Draft layer.
Phase:     Round 1 (proposals) and Rounds 2+ (replies).
Input:
  content:        str                          — full text of the post
  entry_type:     "proposal" | "reply"
  thread_id:      str                          — required; every post belongs to a thread
  reply_to:       str | None                   — entry_id of parent (null for top-level)
  mention_agents: list[str] = []               — agent IDs to notify
Output:   { entry_id: str }                    — ID of the created entry
Server-side enforced:
  - entry_type="proposal" only valid in round 1
  - Soft-deleted entries cannot be reply_to targets
  - Agent must be a taker for this thread
```

### `cite`

```
Purpose:   Record endorsement of entries being built upon in current post.
Phase:     Rounds 2+ only (server rejects in round 1 or vote sub-round).
Semantics: ONLY call when genuinely building on or agreeing with the entry.
           Disagreement is expressed through reply content, NOT citation.
Input:
  entry_ids:  list[str]   — IDs of entries to endorse (self-citations filtered server-side)
Output:   { cited: int, skipped_self: int }
Side effects:
  - Increments citation_count on each cited entry (for attention and promotion)
  - Updates last_cited_round on each cited entry (resets decay clock)
  - Creates records in citations table
  - Checks promotion threshold after each cite
```

### `vote`

```
Purpose:   Formal endorsement during cold start vote sub-round (after round 1).
Phase:     Vote sub-round ONLY. Server rejects vote() calls in other phases.
Semantics: "I find this round-1 proposal valid and would build on it."
           Vote counts feed into confidence_0 initialization. NOT promotion signals.
Input:
  entry_id:  str    — ID of a round-1 proposal to endorse
Output:   { ok: bool }
Side effects:
  - Creates record in votes table
  - confidence_0 recalculated after all votes collected
```

### `get_confirmed`

```
Purpose:   Retrieve the Confirmed layer (anchors + promoted findings).
Phase:     Any phase.
Input:
  thread_id:  str | None   — None for all threads
Output:   list of { id, content, entry_type, citation_count, round_confirmed,
                    thread_title }
Use case:  Agent orients itself at start of each round to see ratified findings.
```

### `submit_bid`

```
Purpose:   Agent commits to taking a contract or a specific thread.
Phase:     Auction phase (contract bid) and thread assignment phase.
Input:
  justification:  str           — agent's reasoning for participating
  thread_id:      str | None    — None for main contract bid; set for thread sub-bid
Output:   { ok: bool, preliminary_score: float }
```

### `abstain`

```
Purpose:   Agent opts out of a contract or thread.
Phase:     Auction phase and thread assignment phase.
Input:
  reason:    str           — agent's reasoning for opting out
  thread_id: str | None    — None for full contract abstention; set for per-thread
Output:   { ok: bool }
Side effects (contract abstention):
  - Agent is marked as non-participant; no run access
  - No trust score changes (fully voluntary exit)
Side effects (bid-and-lost — system-assigned observer status):
  - trust_score[domain] -= delta_observer_loss at run end
```

### `request_expertise`

```
Purpose:   Propose that the contract needs additional agent expertise.
Phase:     Rounds 1+ (any round, up to max_amendments per run).
Input:
  domain:     str   — e.g. "financial_modeling", "regulatory_compliance"
  reason:     str   — why this expertise gap matters for the thread
  thread_id:  str   — which thread needs it
Output:   { amendment_id: str, status: "pending" | "rejected_limit_reached" }
Side effects:
  - SYSTEM entry posted to Confirmed layer (all participants see it)
  - Majority vote initiated among takers + Market Maker
  - If approved: new Thread created, mini-auction triggered
```

### `files` (existing, unchanged)

```
Purpose:   Access knowledge files attached to this agent.
Input:     action: "list" | "read", file_name: str | None
Output:    str
```

---

# 9. Agent Prompt Templates

## 9.1 Auction Phase Prompt

```
SYSTEM:
{agent.system_prompt}

You are being invited to bid on a contract in a multi-agent collaborative system.
Review the contract carefully. Use read_blackboard() to read the contract and thread details.
Use files() to consult your knowledge base if relevant.
Then call submit_bid(justification) if you can contribute, or abstain(reason) if you cannot.
Only bid if you genuinely have relevant expertise. Compute efficiency is precious.

USER:
CONTRACT INVITATION
Task type: {contract.task_type}
Task nature: {contract.task_nature}
Original prompt: {contract.original_prompt}
Required expertise: {contract.required_expertise}
Complexity: {contract.complexity}
Market Maker confidence: {contract.confidence:.2f}

YOUR PRELIMINARY MATCH SCORE: {preliminary_score:.3f}
YOUR TRUST SCORE (this domain): {trust_score:.3f}

Review the full contract and threads by calling read_blackboard().
Then call submit_bid(justification) or abstain(reason).
```

## 9.2 Thread Bidding Prompt (Multi-Step Only)

```
SYSTEM:
{agent.system_prompt}

You have been accepted as a taker for this contract.
You now need to decide which threads (sub-topics) you want to work on.
Review each thread carefully and submit a bid for threads where you can contribute,
or abstain from threads outside your expertise.

USER:
CONTRACT: {contract.original_prompt}

THREADS AVAILABLE:
{for each thread:
  [THREAD-{id}] {title}
  Description: {description}
  Required expertise: {required_expertise}
  Complexity: {complexity}
  Current takers: {count}
}

For each thread: call submit_bid(thread_id) or abstain(thread_id, reason).
Every thread must have at least one taker. Threads you do not bid on may trigger
a new recruitment round if no other agent covers them.
```

## 9.3 Round 1 — Opening Proposal Prompt

```
SYSTEM:
{agent.system_prompt}

You are participating in a collaborative multi-agent blackboard system.
The blackboard works like a Reddit thread: you read posts, write replies,
cite posts you agree with, and mention agents you need.

RULES:
- Use read_blackboard() to orient yourself before posting.
- Use post_to_blackboard() to write your contribution.
- Use cite(entry_ids) ONLY for entries you are building on or agree with.
- Do NOT cite entries you disagree with — express disagreement in your reply content.
- Use mention_agents in post_to_blackboard() to alert specific agents.
- Use files() to access your attached knowledge.

ROUND 1 INSTRUCTION: Write your opening proposal for this thread.
Include: (1) why you are qualified for this task,
         (2) your initial analysis and answer,
         (3) what tools or sources you used.
This is your stake in the ground. Make it thorough.

{conceding_temperature_instruction}

USER:
CONTRACT: {contract.original_prompt}
YOUR THREAD: [{thread.id}] {thread.title} — {thread.description}
ROUND: 1 of {max_rounds}
CO-WORKERS ON THIS THREAD: {list of taker names + descriptions}

RECENT CONFIRMED LAYER:
{compact list of contract/thread anchors}

Use read_blackboard(thread_id="{thread.id}") to see the full context,
then use post_to_blackboard() to write your Round 1 proposal.
```

## 9.4 Vote Sub-Round Prompt (Between Rounds 1 and 2)

```
SYSTEM:
{agent.system_prompt}

You are in the cold-start voting phase. Review all Round 1 proposals
from your co-workers and call vote(entry_id) for each proposal you find
valid and would build on. You may vote on multiple proposals.
This is NOT about selecting a winner — it establishes initial confidence scores.

USER:
ROUND 1 PROPOSALS IN YOUR THREAD [{thread.title}]:
{formatted list of round-1 entries with IDs and content}

Call vote(entry_id) for each proposal you find valid.
Call read_blackboard() if you need to review any entry in detail.
```

## 9.5 Rounds 2+ — Discussion Prompt

```
SYSTEM:
{agent.system_prompt}

You are in round {R} of a collaborative multi-agent discussion.
The blackboard is a Reddit-like thread: read posts, write replies,
cite what you agree with, @mention agents whose help you need.

{conceding_temperature_instruction}

USER:
CONTRACT: {contract.original_prompt}
YOUR THREAD: [{thread.id}] {thread.title}
ROUND: {R} of {max_rounds}

CONFIRMED SO FAR:
{top 3 confirmed findings for this thread}

RECENT ACTIVITY (last 5 visible entries):
{compact summary: [ID] Author · Type: "excerpt..."}

Use read_blackboard() to explore the discussion in depth.
Use post_to_blackboard(reply_to=...) to respond to specific posts.
Use cite(entry_ids=[...]) for entries you are building on.
Use request_expertise(...) if you identify a gap the current team cannot fill.
Use mention_agents=[...] in post_to_blackboard() to invite specific agents into a sub-discussion.
```

---

# 10. API Surface

## 10.1 Existing Endpoints (Unchanged)

All existing endpoints under `/api/agents/` and `/api/files/` remain unchanged and fully functional.

## 10.2 New Endpoints

### `POST /api/simulation/run`

```
Request body: SwarmRunConfig (includes mode: "swarm" | "topology")
Response:     text/event-stream — sequence of SimulationStep JSON objects

For topology mode: delegates to existing run_topology(), wraps output in SSE.
For swarm mode: runs full ECSAS pipeline, streams events in real-time.

Final event: { type: "convergence", msg: <SwarmFinalOutput JSON> }
```

### `GET /api/simulation/{run_id}/blackboard`

```
Query params:
  thread_id: str | None
  layer: "draft" | "confirmed" | "both" (default: "both")
  include_deleted: bool (default: false)

Response: {
  confirmed: list[ConfirmedEntrySchema],
  draft: list[DraftEntrySchema],     // nested tree (children populated)
  threads: list[ThreadSchema]
}
```

### `GET /api/simulation/{run_id}/audit`

```
Response: Full audit trail as JSON:
{
  run: SwarmRun,
  contract: ContractSchema,
  threads: list[ThreadSchema],
  bids: list[Bid],
  all_draft_entries: list[DraftEntry],   // includes soft-deleted
  citations: list[Citation],
  votes: list[Vote],
  confirmed_entries: list[ConfirmedEntry],
  amendments: list[Amendment],
  reputation: list[ReputationRecord],
  final_output: SwarmFinalOutput
}
```

### `GET /api/simulation/{run_id}/status`

```
Response: { run_id, status, current_round, termination_reason, token_usage }
```

### `GET /api/agents/{agent_id}/trust`

```
Response: list[{ domain, trust_score, runs_participated, updated_at }]
```

---

# 11. End-to-End Flow

## 11.1 Detailed SSE Event Sequence

```
EVENT FLOW (swarm mode)

→ { type: "system",     msg: "Market Maker analyzing prompt..." }
→ { type: "system",     msg: "Contract created: [task_type], [task_nature], confidence=0.82" }
→ { type: "system",     msg: "Threads created: [Thread 1], [Thread 2]" }

→ { type: "system",     msg: "Auction open. 8 agents invited." }
→ { type: "bid",        msg: "Alpha submitted bid: 'I specialize in...'",    node_id: "alpha-id" }
→ { type: "bid",        msg: "Beta submitted bid: 'Contract law is my...'",  node_id: "beta-id" }
→ { type: "abstain",    msg: "Gamma abstained: 'Outside my domain'",         node_id: "gamma-id" }
→ { type: "system",     msg: "Takers selected: Alpha (T1), Beta (T1,T2), Delta (T2)" }

→ { type: "system",     msg: "Round 1 begins. Opening proposals." }
→ { type: "bb-post",    msg: "[BB-001] Alpha → Thread 1: 'The penalty clause...'",    node_id: "alpha-id", thread_id: "T1" }
→ { type: "tool",       msg: "Alpha: files(read, 'precedents.pdf') → [result]",       node_id: "alpha-id" }
→ { type: "bb-post",    msg: "[BB-002] Beta → Thread 1: 'Section 4.2 contradicts...'", node_id: "beta-id", thread_id: "T1" }
→ { type: "bb-post",    msg: "[BB-003] Beta → Thread 2: 'The pricing formula...'",    node_id: "beta-id", thread_id: "T2" }

→ { type: "system",     msg: "Vote sub-round. Agents review Round 1 proposals." }
→ { type: "bb-vote",    msg: "Beta voted on BB-001",  node_id: "beta-id" }
→ { type: "bb-vote",    msg: "Alpha voted on BB-002",  node_id: "alpha-id" }
→ { type: "system",     msg: "Cold-start confidence: Alpha=0.50, Beta=0.50, Delta=0.00" }
→ { type: "system",     msg: "Round 2 begins. Temperature: Alpha=0.50, Beta=0.50, Delta=1.00" }

→ { type: "bb-post",    msg: "[BB-005] Alpha → Thread 1 (↩BB-001): '@Beta, does §7.1 conflict?'", node_id: "alpha-id" }
→ { type: "bb-mention", msg: "Beta mentioned in BB-005", node_id: "beta-id" }
→ { type: "bb-cite",    msg: "Beta cited BB-001, BB-002", node_id: "beta-id" }
→ { type: "bb-promote", msg: "BB-001 promoted to Confirmed (3 citations)", thread_id: "T1" }

→ { type: "system",     msg: "Round 3 begins. Entropy: 1 new confirmed entry." }
...
→ { type: "system",     msg: "Equilibrium detected. 0 new entries for 2 consecutive rounds." }
→ { type: "convergence", msg: <SwarmFinalOutput JSON> }
```

## 11.2 Backend Orchestrator Pseudocode

```python
async def run_swarm(config: SwarmRunConfig, db: Connection) -> AsyncIterator[SimulationStep]:
    run_id = uuid4()
    await db.execute("INSERT INTO swarm_runs (id) VALUES (?)", (run_id,))
    tracker = TokenTracker(budget=config.token_budget)

    # ── Market Maker ─────────────────────────────────────
    contract, threads = await market_maker.make_contract(config.prompt, run_id)
    for anchor in [contract] + threads:
        await blackboard.post_anchor(anchor, run_id)
    yield step("system", f"Contract: {contract.task_type}, {contract.task_nature}")

    # ── Auction ───────────────────────────────────────────
    invited = await auction.invite(contract, db)
    takers, observers = await auction.self_select(invited, contract, threads, config, tracker)
    yield step("system", f"Takers: {[t.name for t in takers]}")

    # ── Round 1 — Opening proposals ───────────────────────
    round_steps = await run_round(takers, contract, threads, round=1,
                                  temperatures={t.id: 0.5 for t in takers},
                                  config=config, tracker=tracker, db=db)
    for s in round_steps:
        yield s

    # ── Vote sub-round ─────────────────────────────────────
    confidence = await run_vote_subround(takers, threads, run_id, tracker, db)
    temperatures = {
        t.id: max(1 - confidence[t.id], config.t_initial)
        for t in takers
    }
    yield step("system", f"Cold-start confidence computed.")

    # ── Discussion rounds ─────────────────────────────────
    for R in range(2, config.max_rounds + 1):
        if tracker.exhausted():
            termination_reason = "budget"
            break

        round_steps = await run_round(takers, contract, threads, round=R,
                                      temperatures=temperatures,
                                      config=config, tracker=tracker, db=db)
        for s in round_steps:
            yield s

        # End-of-round system actions
        new_confirmed = await blackboard.check_promotions(run_id, R, config)
        for entry in new_confirmed:
            yield step("bb-promote", f"{entry.id} promoted", thread_id=entry.thread_id)

        await blackboard.soft_delete_stale(run_id, R, config.decay_rounds)

        confidence = await convergence.update_confidence(run_id, R, takers)
        temperatures = {
            t.id: max(1 - confidence[t.id], config.t_initial + (R-1)*config.delta_t)
            for t in takers
        }
        await convergence.update_reputation(run_id, R, takers)

        # Process any pending amendments
        async for amendment_step in amendment_engine.process_pending(run_id, R, takers, tracker):
            yield amendment_step

        if termination.check_equilibrium(run_id, R, config):
            termination_reason = "equilibrium"
            break
    else:
        termination_reason = "max_rounds"

    # ── Final output ──────────────────────────────────────
    output = await termination.format_output(run_id, R, termination_reason)
    await trust_registry.update(run_id, takers, observers)
    await db.execute("UPDATE swarm_runs SET status='completed', ... WHERE id=?", (run_id,))
    yield step("convergence", output.model_dump_json())
```

---

# 12. Frontend Specification

## 12.1 Layout During Swarm Simulation

**Entry point — Mode Gate (`mode-gate.tsx` ✅ DONE)**
Before any canvas is shown, the user sees a full-screen mode selection: "Topology" or "Swarm". Selecting Swarm transitions to the swarm layout below.

**Swarm layout:**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ CANVAS (left, ~40% width)            │ BLACKBOARD PANEL (right, ~60% width) │
│                                      │                                        │
│  [MM badge — draggable]              │ THREADS: [§1 Pricing ×] [§2 Legal ×] │
│                                      │                           [+ proposed] │
│  [Alpha]  [Beta]  [Delta]            │                                        │
│  taker    taker   taker              │ ┌── CONFIRMED (sticky) ─────────────┐ │
│                                      │ │  THE COORDINATION MEDIUM           │ │
│  [Gamma]  [Sigma]                   │ │  Ratified knowledge agents build on│ │
│  observer  non-                      │ │ 📌 [ANCHOR] Contract: "Analyze..." │ │
│             participant              │ │ 📌 [ANCHOR] Thread 1: "Pricing..." │ │
│                                      │ │ ✅ [CF-003] Round 2, 3 ♡:          │ │
│  ┌────────────────────────────────┐  │ │     "§4.2 is unenforceable"        │ │
│  │ BLACKBOARD CANVAS (in-world)   │  │ └────────────────────────────────────┘ │
│  │ draggable · resizable          │  │                                        │
│  │ ┄ Confirmed ┄  ┄ Draft ┄      │  │ ┌── DRAFT (scrollable thread) ──────┐ │
│  │ 📌 ANCHOR: Contract anchor     │  │ │ ▲ [BB-001] Alpha · R1 · proposal  │ │
│  │ ✅ FINDING: §4.2 unenf.        │  │ │ ♡3 · 💬2 · "The penalty clause..."│ │
│  │ P  Alpha · R1 · proposal       │  │ │   ↳ [BB-003] Beta · R1 · vote     │ │
│  └────────────────────────────────┘  │ │     "Agree — DCF contradicts §7.1"│ │
│                                      │ │       ↳ [BB-007] Alpha · R2       │ │
│                                      │ │         "@FinancialAgent check DCF"│ │
│                                      │ │ [BB-002] Gamma · R1 [dimmed/idle] │ │
│                                      │ └────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────────────────────┤
│ SWARM ACTIVITY LOG ▼ (collapsible)                                           │
│ [system events, tool calls, bid scores, round markers, promotion notices]    │
└──────────────────────────────────────────────────────────────────────────────┘
```

> **Key distinction:** The canvas contains a compact in-world **BlackboardCanvas** widget (draggable, resizable, scrollable) showing a live read-only preview of both layers. The right-side **BlackboardPanel** is the full-detail view with thread filtering, citation counts, nested replies, and entry metadata. These are two separate UI elements serving different observability needs — see §12.7.

## 12.2 Swarm Config Modal

Triggered: when user selects "Swarm" mode and presses Run.
Presentation: modal over blurred canvas background.

```
┌────────────────────────────────────────────────┐
│  SWARM CONFIGURATION                       ✕   │
│                                                │
│  Takers       min [2] max [5]                  │
│  Rounds       min [2] max [10]                 │
│  Token budget [50,000]                         │
│  Max amendments [2]                            │
│                                                │
│  ▸ Advanced settings                           │
│    Invite floor    [0.30]                      │
│    Decay rounds    [3]                         │
│    Attention K     [10]                        │
│                                                │
│            [Cancel]  [Run Swarm →]             │
└────────────────────────────────────────────────┘
```

## 12.3 Canvas Nodes — Swarm Mode

| Node                   | Component                           | Visual                                                                                                                                                   | Status  | Notes                                                                                                         |
| ---------------------- | ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------- |
| **Market Maker badge** | `canvas/swarm-nodes.tsx`            | Draggable burgundy badge, receipt icon, "MM" label                                                                                                       | ✅ DONE | Repositionable in world space; dashed SVG connector drawn to BlackboardCanvas                                 |
| **BlackboardCanvas**   | `canvas/blackboard-canvas.tsx`      | Draggable + resizable panel in world space; tabs for Confirmed / Draft entries; entry type badges (📌 ANCHOR, ✅ FINDING, ⚙ SYSTEM, P/R proposal-reply) | ✅ DONE | Full in-world blackboard widget — **not** a simple icon node. See §12.7 for distinction from BlackboardPanel. |
| **Thread node**        | `canvas/blackboard/thread-node.tsx` | Rounded pill, one per thread, color-coded, appears after threads exist; click filters BlackboardCanvas                                                   | ✅ DONE | Lives as a viewport overlay sibling of BlackboardCanvas, not inside its world-transform group                 |

Existing agent nodes in swarm mode:

- Takers: normal appearance, particle animations toward BlackboardCanvas
- Observers: 30% opacity, "observer" badge
- Non-participants: 10% opacity, no badge

Agent-to-agent edges from Builder mode: hidden in swarm mode (agents coordinate via the blackboard, not direct edges).

## 12.4 Animation Grammar

| Event                           | Animation                                                                                                |
| ------------------------------- | -------------------------------------------------------------------------------------------------------- |
| **Agent submits bid**           | Gold particle from agent → center (Market Maker node). Bid score badge fades in on agent node.           |
| **Agent abstains**              | Agent node briefly dims to 20% then returns to 10% opacity.                                              |
| **Agent posts to Draft**        | Burgundy particle from agent → Blackboard node. New entry appears in Draft panel.                        |
| **Agent calls cite()**          | Small heart (♡) icon pulses on the cited entry in the Draft panel. Citation counter increments.          |
| **Agent calls vote()**          | Blue checkmark briefly appears on voted entry.                                                           |
| **Entry promoted to Confirmed** | Entry glows gold and smoothly translates upward to the Confirmed section. Blackboard node pulses.        |
| **Entry soft-deleted**          | Entry fades from full opacity to 0% over 0.5s, then is removed from DOM.                                 |
| **Agent @mentioned**            | Mentioned agent node briefly pulses. Entry pinned to top of that agent's view.                           |
| **Contract amendment proposed** | Blackboard node expands, SYSTEM entry appears in Confirmed. Vote indicators appear.                      |
| **Amendment approved**          | New thread tab flashes into existence with a green pulse.                                                |
| **Equilibrium**                 | All active agent nodes and the Blackboard node pulse simultaneously in burgundy. Confirmed entries glow. |
| **Final answer**                | Most-cited Confirmed entry for each thread highlighted with gold border.                                 |

## 12.5 Component Tree (Swarm UI — Implementation Status)

```
client/
├── components/
│   ├── mode-gate.tsx                ✅ DONE — full-screen mode selector (topology vs swarm)
│   │
│   ├── blackboard-panel.tsx         ✅ DONE — right-side panel; thread selector (inline),
│   │   │                                       confirmed-section, draft-section
│   │   ├── confirmed-section.tsx    ✅ DONE — THE COORDINATION MEDIUM
│   │   │                                       sticky, permanent, ratified findings only
│   │   │                                       entry types: 📌 anchor · ✅ finding · ⚙ system
│   │   └── draft-section.tsx        ✅ DONE — scrollable live discussion (Reddit-style)
│   │       └── draft-entry.tsx      ✅ DONE — recursive nested entry (max depth 4)
│   │                                           entry types: P proposal · R reply · V vote · ⚙ system
│   │
│   ├── swarm-activity-log.tsx       ✅ DONE — collapsible log: system events, tool calls,
│   │                                           bid scores, round markers, promotion notices
│   │
│   ├── swarm-config-modal.tsx       ✅ DONE — pre-run config modal (takers, rounds, budget,
│   │                                           invite floor, decay rounds, attention K);
│   │                                           confirm branches on the literal prompt
│   │                                           "test_mohamed" → dummy pipeline, else → seed
│   │
│   └── canvas/
│       ├── swarm-nodes.tsx          ✅ DONE — draggable Market Maker badge in world space
│       │                                       SVG dashed connector drawn to BlackboardCanvas
│       │
│       ├── blackboard-canvas.tsx    ✅ DONE — always-pinned (no longer seed-gated) in-world
│       │                                       widget; renders proposal/reply/vote/system cards
│       │                                       via canvas/blackboard/*; BlackboardPanel retired
│       │                                       (see §12.7 update below)
│       │
│       ├── blackboard/
│       │   ├── proposal-card.tsx    ✅ DONE — Twitter/X-style top-level post
│       │   ├── reply-thread.tsx     ✅ DONE — Reddit-style recursive ThreadedEntry dispatcher
│       │   ├── vote-chip.tsx        ✅ DONE — compact endorsement row
│       │   ├── system-row.tsx       ✅ DONE — collapsible infra-event row
│       │   ├── citation-ring.tsx    ✅ DONE — animated progress ring + citer hover-card
│       │   ├── confirmed-card.tsx   ✅ DONE — gold-accented Confirmed-layer card
│       │   ├── agent-trust-panel.tsx ✅ DONE — citations-this-run + trust vector flyout
│       │   └── thread-node.tsx      ✅ DONE — color-coded pill per thread; click filters
│       │                                       BlackboardCanvas to that thread
│
└── hooks/
    ├── useBlackboard.ts             ✅ DONE — polls GET /api/simulation/{run_id}/blackboard;
    │                                           manages BlackboardState (threads, confirmed, draft)
    └── useDummySwarm.ts             ✅ DONE — scripted client-side dummy pipeline, triggered by
                                                the literal prompt "test_mohamed" in swarm mode
```

## 12.7 The Three Distinct Blackboard UI Elements

The ECSAS frontend originally split this across three components. **Update:** `blackboard-panel.tsx`, `confirmed-section.tsx`, and `draft-section.tsx` were retired (deleted) once `BlackboardCanvas` became always-pinned and gained the full social-feed entry-card redesign — there was no remaining reason to duplicate the same data in a second, less detailed view. `BlackboardCanvas` (below) plus its fullscreen expand modal are now the **sole** in-canvas home for both layers. The comparison table is kept for historical context.

### `canvas/blackboard-canvas.tsx` — In-World Blackboard Widget ✅ DONE

- **Where:** lives inside the canvas world transform — pans and zooms with the agent graph
- **What:** a draggable, resizable floating panel showing a compact live read of both the Confirmed and Draft layers for the active run
- **Purpose:** ambient situational awareness while watching the agent graph — lets the user observe what's happening on the blackboard without leaving the canvas view
- **Interaction:** drag to reposition, resize from corner; scrollable inside; read-only
- **Data:** polls `GET /api/simulation/{run_id}/blackboard` via `useBlackboard`

### `blackboard-panel.tsx` — Full-Detail Side Panel ✅ DONE

- **Where:** right-side panel (~60% width), rendered outside the canvas world transform
- **What:** the primary detailed blackboard view — thread selector, full entry metadata, citation counts, nested reply tree, markdown-rendered content
- **Purpose:** deep inspection of the coordination process; where the user reads the actual reasoning, checks citation chains, and tracks convergence
- **Contains:** `confirmed-section.tsx` (top, sticky) + `draft-section.tsx` (scrollable below)

### `confirmed-section.tsx` — The Coordination Medium ✅ DONE

- **Where:** sticky top section inside `blackboard-panel.tsx`
- **What:** shows **only** the Confirmed layer — entries that have received ≥ M distinct non-self citations and been promoted from Draft to permanent
- **Purpose:** this is the epistemic substrate agents are coordinating **around**, not just observing. It is the authoritative, ratified state of shared knowledge for a run. The final answer is selected from this layer.
- **Why it is distinct:** the Draft layer is noise + signal together; the Confirmed layer is signal only. Architecturally: Draft = working memory, Confirmed = long-term memory. The user and any downstream system should treat Confirmed entries as established facts.
- **Entry types rendered:** 📌 `anchor` (contract/thread anchors posted by Market Maker), ✅ `finding` (promoted agent findings), ⚙ `system` (system-generated entries)

|                 | BlackboardCanvas      | BlackboardPanel       | ConfirmedSection          |
| --------------- | --------------------- | --------------------- | ------------------------- |
| Location        | In canvas world space | Right-side panel      | Inside BlackboardPanel    |
| Shows Draft     | Yes (compact)         | Yes (full detail)     | No                        |
| Shows Confirmed | Yes (compact)         | Yes (full detail)     | Yes (only this)           |
| Interaction     | Drag/resize/scroll    | Read/filter by thread | Read-only sticky          |
| Primary purpose | Ambient awareness     | Deep inspection       | Coordination ground truth |

## 12.8 useSimulation Refactor

```typescript
// Swarm mode: consume SSE stream from backend
const runSwarm = useCallback(async (prompt: string, config: SwarmRunConfig) => {
  setSim(true);
  setMode("swarm");

  const res = await fetch("/api/simulation/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...config, prompt, mode: "swarm" }),
  });

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const lines = decoder.decode(value).split("\n");
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const step: SimStep = JSON.parse(line.slice(6));
      setSteps((prev) => [...prev, step]);
      // Additional swarm-specific state updates
      if (step.type === "bb-post") updateBlackboard(step);
      if (step.type === "bb-promote") promoteEntry(step);
      if (step.type === "bb-delete") softDeleteEntry(step);
      if (step.type === "bid") setBidBadge(step.nodeId, step.score);
      if (step.type === "convergence") setFinalOutput(JSON.parse(step.msg));
    }
  }
}, []);

// Topology mode: unchanged (still calls existing endpoints)
```

## 12.9 Blackboard Entry UI Models

The four `entry_type` values in `draft_entries` require distinct visual treatments. Currently `draft-entry.tsx` renders all types with a single template. This section defines what each should look like.

### 12.9.1 Proposal (Post) — Primary contribution card

Full visual weight. This is the unit of intellectual work that gets cited and promoted.

```
┌──────────────────────────────────────────────────────────────────────┐
│ ● Alpha  ·  claude-sonnet-4-6  ·  Anthropic    R1   [proposal]  @×1 │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  The penalty clause in §4.2 is unenforceable under EU law: the      │
│  liquidated damages cap (€50k) is disproportionate to the actual    │
│  estimated loss range (€200k–€800k). DCF analysis confirms.         │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│ ♡  ████████░░  2 / 4   [cited by: Alpha, Delta ▾]    💬 3   ⋯ id   │
└──────────────────────────────────────────────────────────────────────┘
```

| Field              | DB source                           | Notes                                                                                  |
| ------------------ | ----------------------------------- | -------------------------------------------------------------------------------------- |
| Color dot ●        | agent color from SwarmNodes palette | matches canvas node color                                                              |
| Agent name         | `author_name` (JOIN agents)         |                                                                                        |
| Provider badge     | `agents.model` + `agents.provider`  | e.g. "claude-sonnet-4-6 · Anthropic"                                                   |
| Round badge R{n}   | `draft_entries.round`               |                                                                                        |
| `[proposal]` badge | `entry_type`                        | burgundy chip                                                                          |
| `@×1` mention pill | `mention_agents` JSON length        | shows count + first 2 names on hover                                                   |
| Content body       | `content`                           | markdown-rendered                                                                      |
| ♡ progress bar     | `citation_count` / M                | fills toward promotion; M = `max(1, N_participants // citation_threshold_divisor + 1)` |
| Citer tooltip      | citations JOIN                      | hover: list of citing agent names + rounds                                             |
| Reply count 💬     | children count (tree)               |                                                                                        |
| Soft-deleted state | `is_visible = false`                | card dimmed; label "evaporated (R{n})"                                                 |
| Promoted state     | `confirmed_entries.source_draft_id` | ♡ bar → `✅ Confirmed (R{n})` chip                                                     |

**Status:** ✅ DONE — `canvas/blackboard/proposal-card.tsx`

---

### 12.9.2 Reply (Comment) — Threaded subordinate entry

Visually lighter than a proposal. Indented with a thread-line gutter. Connected to its parent via a reply-to breadcrumb.

```
  │
  ├─ ● Beta  R2  ↩ "The penalty clause in §4.2…"       reply  ♡ 1
  │   Agreed — the DCF in Annex B supports this claim.
  │   💬 1   ⋯ id
  │
  │   └─ ● Alpha  R3  ↩ "Agreed — the DCF…"            reply  ♡ 0
  │       @Beta — what discount rate did you apply?
  │       ⋯ id
```

| Field                  | DB source                           | Notes                                                                  |
| ---------------------- | ----------------------------------- | ---------------------------------------------------------------------- |
| Thread-line gutter     | CSS `border-left`                   | 2px agent color; `depth × 16px` indent (max 4)                         |
| Reply-to breadcrumb ↩ | `reply_to` → parent `content[0:60]` | truncated quote of parent entry                                        |
| Content                | `content`                           | markdown; smaller font weight than proposal                            |
| ♡ count                | `citation_count`                    | compact label only — no progress bar (replies rarely promote directly) |

**Status:** ✅ DONE — `canvas/blackboard/reply-thread.tsx`

---

### 12.9.3 Vote (Endorsement Chip) — Compact declared vote

A declared vote from the initial confidence-calibration round. Not a prose contribution. Should not have the same visual weight as proposals.

```
┌──────────────────────────────────────────────────────────────────────┐
│ ✓  Beta  →  ↗ BB-001  ·  R1  ·  "The penalty clause in §4.2…"       │
└──────────────────────────────────────────────────────────────────────┘
```

| Field                 | DB source                                              | Notes                       |
| --------------------- | ------------------------------------------------------ | --------------------------- |
| ✓ icon                | `entry_type = 'vote'`                                  | green check, muted chip row |
| Voter name            | `author_name`                                          |                             |
| Voted-entry reference | `votes.voted_entry_id` → `draft_entries.content[0:60]` | truncated content preview   |
| Round                 | `round`                                                |                             |

**Status:** ✅ DONE — `canvas/blackboard/vote-chip.tsx`

---

### 12.9.4 System Entry (Event Log Row) — Infrastructure events

Promotion notifications, soft-delete events, round boundary markers. Should not compete visually with agent contributions.

```
  ⚙  R2  system  "BB-001 promoted to Confirmed (3/3 citations)"     [▾]
```

| Field           | DB source               | Notes                                 |
| --------------- | ----------------------- | ------------------------------------- |
| ⚙ icon         | `entry_type = 'system'` | small gray icon                       |
| Round           | `round`                 |                                       |
| Content         | `content`               | muted text, smaller size              |
| Collapse toggle | —                       | collapsed by default; user can expand |

**Status:** ✅ DONE — `canvas/blackboard/system-row.tsx`

---

### 12.9.5 Citation / Upvote — Interactive progress element

The citation mechanism is the core stigmergic signal and deserves a dedicated UI element on every entry, not just a count label.

```
  ♡  ████████░░  2 / 4   ← progress bar toward promotion threshold M
                  ↑
      on hover:
      ╔════════════════════════════╗
      ║ Cited by:                  ║
      ║  ● Alpha  ·  R1            ║
      ║  ● Delta  ·  R2            ║
      ║                            ║
      ║ 2 more citations → Confirm ║
      ╚════════════════════════════╝
```

Behavior:

- **Bar color:** `bg-muted` when < 25% of M; `bg-amber-500` when ≥ 50%; `bg-green-500` when ≥ M
- **Pulse animation:** brief glow on ♡ icon when a new `bb-cite` SSE event arrives for this entry
- **Promoted state:** bar replaced by `✅ Confirmed (R{n})` chip linking to `confirmed_entries` record
- **Data source:** `citation_count` (already in SQL JOIN query in `simulation.py`); hover detail either included in entry payload or fetched on-demand

**Status:** ✅ DONE — `canvas/blackboard/citation-ring.tsx`

---

## 12.10 Agent Card — Blackboard Mode

In blackboard mode each agent node on the canvas (and in `BlackboardPanel`) should expose two additional data layers: their **citation impact for this run** and their **cross-run trust vector by domain**.

```
┌──────────────────────────────────────────────────────────────────────┐
│ ● Alpha          [taker]                  ♡ 12 citations this run   │
│   claude-sonnet-4-6 · Anthropic           conceding temp: 0.72 ████▒│
├──────────────────────────────────────────────────────────────────────┤
│ ▸ Trust Vector (cross-run)                              [expand ▾]   │
│   ┌────────────────────────────────────────────────────────────────┐ │
│   │  contract-law         0.82  ████████░░  (3 runs)              │ │
│   │  financial-analysis   0.65  ██████░░░░  (3 runs)              │ │
│   │  regulatory           0.41  ████░░░░░░  (2 runs)              │ │
│   │  general              0.50  █████░░░░░  (5 runs)              │ │
│   └────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

| Field                          | DB source                                                                                                               | Notes                                            |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| Agent name + color dot         | `agents.name`                                                                                                           | matches canvas node color                        |
| `[taker]` / `[observer]` badge | from auction result (in-memory during run)                                                                              |                                                  |
| ♡ N citations this run         | `SELECT COUNT(*) FROM citations WHERE run_id=? AND citing_entry_id IN (SELECT id FROM draft_entries WHERE author_id=?)` | counts citations received on agent's own entries |
| Conceding temperature          | convergence engine `t_i` per agent per round                                                                            | `∈ [0.0, 1.0]`; displayed as progress bar        |
| Trust vector rows              | `agent_trust` table (✅ now in `tables.py`, landed via `feat/143-blackboard-core`)                                      | domain → score + run_count                       |

### DB addition required

**Update:** this table has since landed in `server/db/tables.py` via `feat/143-blackboard-core` (not this plan). Original requirement kept below for historical reference:

```python
agent_trust = Table(
    "agent_trust",
    metadata,
    Column("agent_id", Text, ForeignKey("agents.id"), nullable=False),
    Column("domain", Text, nullable=False),
    Column("score", Float, nullable=False, server_default=text("0.5")),
    Column("run_count", Integer, nullable=False, server_default=text("0")),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("agent_id", "domain", name="uq_agent_trust_domain"),
)
```

### API additions required

- `GET /api/agents/{agent_id}/trust` → `[{domain, score, run_count}]`
- Include `citations_received` count per agent in `GET /api/simulation/{run_id}/blackboard` response (or as a separate `GET /api/simulation/{run_id}/agent-stats`)

### Frontend components affected

| Component                      | Change needed                                         | Status                                                                                                                                       |
| ------------------------------ | ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `canvas/agent-node.tsx`        | add ♡ N badge on agent node in swarm mode             | ✅ DONE                                                                                                                                      |
| `blackboard-panel.tsx` header  | show citation summary row per taker                   | ✅ DONE — superseded: `blackboard-panel.tsx` itself was retired (§12.7); the per-node ♡ badge + `agent-trust-panel.tsx` now cover this       |
| `trust-panel.tsx` (see §12.5)  | expandable per-domain trust scores with progress bars | ✅ DONE — `canvas/blackboard/agent-trust-panel.tsx`                                                                                          |
| `canvas/blackboard-canvas.tsx` | show agent citation ranks in compact agent list       | ❌ TODO — not built this plan; the per-agent ♡ badge (canvas) and the trust panel give equivalent visibility without a dedicated ranked list |

---

# 13. Engineering Roadmap

## Phase 1 — Foundation (Weeks 1–2)

| Task                                                                            | Owner | Exit Criteria                                           |
| ------------------------------------------------------------------------------- | ----- | ------------------------------------------------------- |
| MIG-01: PostgreSQL via SQLAlchemy Core (already satisfied)                      | BB    | DB survives server restart (Postgres)                   |
| MIG-03: all ECSAS tables created                                                | BB    | All 11 ECSAS tables present after `metadata.create_all` |
| MIG-02: `capability_embedding` + `created_at` on agents                         | AB    | Agents table extended                                   |
| `POST /api/simulation/run` SSE stub (swarm mode returns empty stream)           | All   | Endpoint exists, returns `text/event-stream`            |
| `POST /api/simulation/run` topology mode: wrap existing `run_topology()` in SSE | TO    | V0 mode streams correctly to frontend                   |
| Frontend: `useSimulation` SSE refactor (topology path first)                    | FE    | Topology simulation works via SSE                       |
| Frontend: Mode selector (Topology / Swarm) in `PromptBar`                       | FE    | Toggle renders, selects mode                            |
| Frontend: `SwarmConfigModal` (layout only, no functionality yet)                | FE    | Modal appears over blurred canvas                       |

## Phase 2 — Market Maker + Auction (Weeks 3–4)

| Task                                                              | Owner | Exit Criteria                                  |
| ----------------------------------------------------------------- | ----- | ---------------------------------------------- |
| Embedding service (`server/market_hive/embeddings.py`)            | AB    | `embed(text)` returns `list[float]`            |
| `capability_embedding` computed at `POST /api/agents/`            | AB    | New agents have embeddings                     |
| Market Maker: prompt → Contract + Threads                         | MM    | Contracts table populated, SSE events emitted  |
| Auction engine: invitation, self-selection, taker assignment      | AB    | Takers selected, bids table populated          |
| Thread bidding (multi-step): per-taker per-thread decision        | AB    | Thread takers assigned                         |
| `agent_trust` table populated at run end                          | Trust | Trust scores update after first swarm run      |
| Swarm orchestrator Phase 2: MM → Auction → SSE events + terminate | All   | Run ends after auction, correct events emitted |
| Frontend: auction animations, bid badges, observer dimming        | FE    | Bid events visible on canvas                   |
| Frontend: Market Maker node + Thread nodes on canvas              | FE    | New node types render during swarm             |

## Phase 3 — Blackboard + Stigmergy (Weeks 5–6)

| Task                                                                          | Owner       | Exit Criteria                                                                       |
| ----------------------------------------------------------------------------- | ----------- | ----------------------------------------------------------------------------------- |
| Blackboard class: Draft write, attention query, soft delete                   | BB          | `post_to_blackboard`, `read_blackboard`, `cite`, `vote`, `get_confirmed` tools work |
| Pheromone / soft delete logic (end-of-round cleanup)                          | BB          | Stale entries get `is_visible=false`                                                |
| Citation tracking + promotion check                                           | BB          | Entry with M citations → `confirmed_entries`                                        |
| Vote sub-round: confidence initialization                                     | Convergence | `confidence_0` computed correctly                                                   |
| Conceding temperature: per-agent, injected in prompt                          | Convergence | Agent prompts include temperature instruction                                       |
| Per-run reputation updates                                                    | Convergence | `reputation` table updated each round                                               |
| `GET /api/simulation/{run_id}/blackboard`                                     | BB          | Returns nested thread structure                                                     |
| Swarm orchestrator Phase 3: full rounds loop (no amendments yet)              | All         | End-to-end run with promotions and cleanup                                          |
| Frontend: `BlackboardPanel`, `ThreadTabs`, `DraftSection`, `ConfirmedSection` | FE          | Blackboard visible during simulation                                                |
| Frontend: `DraftEntry` component (recursive for nesting)                      | FE          | Threaded view renders correctly                                                     |
| Frontend: bb-post, bb-cite, bb-vote, bb-promote, bb-delete animations         | FE          | All event types have distinct animations                                            |

## Phase 4 — Contract Amendment + Observers (Weeks 7–8)

| Task                                                      | Owner     | Exit Criteria                                        |
| --------------------------------------------------------- | --------- | ---------------------------------------------------- |
| `request_expertise` tool + `amendments` table             | Amendment | Tool call creates amendment record                   |
| Majority vote for amendments (takers + MM as equal voter) | Amendment | Amendments approved/rejected correctly               |
| New thread creation mid-run + mini-auction                | Amendment | New thread tab appears in frontend                   |
| Observer mechanics: no run access, trust decrement at end | Trust     | Observers dimmed, trust updated                      |
| `GET /api/simulation/{run_id}/audit`                      | TO        | Full JSON audit trail including soft-deleted entries |
| `GET /api/simulation/{run_id}/status`                     | TO        | Run status endpoint works                            |
| Equilibrium detection + final output selection            | TO        | Run terminates correctly                             |
| Token budget tracking + graceful halt                     | TO        | Budget exhaustion produces partial output            |
| Frontend: amendment animations, new thread tab flash      | FE        | Amendment events render correctly                    |

## Phase 5 — Evaluation (Weeks 9–10)

| Task                                                                           | Owner | Exit Criteria                                   |
| ------------------------------------------------------------------------------ | ----- | ----------------------------------------------- |
| Benchmark tasks BT-01/02/03 (50 synthetic energy contracts)                    | EV    | Tasks defined, ground truth labelled            |
| Baseline B-01: single LLM call                                                 | EV    | Implemented in `server/evaluation/baselines.py` |
| Baseline B-02: V0 `run_topology()`                                             | EV    | Reuses existing infrastructure                  |
| Baseline B-03: deterministic orchestrated pipeline                             | EV    | Hard-coded routing, no bidding                  |
| Evaluation runner: 5 runs × 3 tasks × 4 systems                                | EV    | Seeded, reproducible, JSON output               |
| Statistical analysis: bootstrap, mean ± std                                    | EV    | Results table produced                          |
| Additional ECSAS metrics: promotion rate, discussion depth, citation diversity | EV    | Reported alongside accuracy/cost/latency        |

## Phase 6 — Paper + Polish (Weeks 11–12)

| Task                                                                   | Owner   |
| ---------------------------------------------------------------------- | ------- |
| Paper draft (intro, related work, methods, results, discussion)        | All     |
| Architecture diagram (updated, publication quality)                    | Mohamed |
| README update                                                          | All     |
| Performance profiling (target: <5min wall clock, 3-6 agents, 5 rounds) | All     |
| Final presentation deck                                                | Mohamed |

---

# 14. Non-Functional Requirements

| ID           | Requirement                                                                                       |
| ------------ | ------------------------------------------------------------------------------------------------- |
| NFR-PERF-01  | Swarm run SHOULD complete under 5 minutes wall-clock with 3–6 agents and 5 rounds                 |
| NFR-PERF-02  | Median token cost SHOULD stay within 3× a single GPT-4o call on the same task                     |
| NFR-PERF-03  | SSE events MUST be emitted within 200ms of the action generating them                             |
| NFR-PERF-04  | `read_blackboard` MUST return in <100ms (indexed SQL + pre-computed embeddings)                   |
| NFR-PERF-05  | Soft delete and promotion checks are batched at round end — NOT per tool call                     |
| NFR-REL-01   | Single agent timeout/error = abstention for that round. Swarm continues.                          |
| NFR-REL-02   | Blackboard persists to PostgreSQL (committed) after every write                                   |
| NFR-REL-03   | If SSE stream disconnects, frontend shows steps received so far; Next/Back still work             |
| NFR-MAINT-01 | All ECSAS logic in `server/market_hive/`. V0 `server/topology/` is read-only                      |
| NFR-MAINT-02 | All inter-component interfaces via Pydantic schemas in `server/market_hive/schemas.py`            |
| NFR-MAINT-03 | `server/market_hive/README.md` documents component interfaces and execution model                 |
| NFR-OBS-01   | Every LLM call logged: prompt hash, model, provider, latency, tokens, run_id, round               |
| NFR-OBS-02   | Every tool call logged: tool_name, agent_id, arguments hash, result hash, run_id                  |
| NFR-OBS-03   | `GET /api/simulation/{run_id}/audit` returns EVERYTHING scoped to the run                         |
| NFR-SEC-01   | `DATABASE_URL` from env only; credentials never committed.                                        |
| NFR-SEC-02   | API keys from env vars only. Never committed.                                                     |
| NFR-SEC-03   | Token budget enforced. Graceful halt on exhaustion.                                               |
| NFR-STACK-01 | Backend: Python ≥ 3.11 (existing: 3.13)                                                           |
| NFR-STACK-02 | LLM: OpenAI primary, Anthropic primary, Groq experimental (do NOT remove)                         |
| NFR-STACK-03 | No LangChain, LangGraph, or any orchestration framework. SDKs only.                               |
| NFR-STACK-04 | Frontend: Next.js App Router + React + shadcn/ui + Tailwind                                       |
| NFR-STACK-05 | Persistence: PostgreSQL via SQLAlchemy Core (asyncpg) in prod/Docker; in-memory SQLite for tests. |

---

# 15. Configuration Constants & Defaults

```python
SWARM_DEFAULTS = {
    # ── Auction ──────────────────────────────────────────────────────
    "invite_floor":         0.3,    # minimum embedding score to be invited to auction
    "min_takers":           2,      # minimum takers for a run to proceed
    "max_takers":           5,      # maximum takers (by preliminary score if more bid)
    "alpha":                0.5,    # embedding similarity weight in bid_score
    "beta":                 0.4,    # trust_score weight in bid_score
    "gamma":                0.1,    # confidence penalty weight in bid_score

    # ── Blackboard ────────────────────────────────────────────────────
    "k_attention":          10,     # entries returned by read_blackboard
    "decay_rounds":         3,      # rounds without citation before soft delete
    "citation_threshold_divisor": 3,# M = max(1, N_participants // divisor + 1)

    # ── Convergence ───────────────────────────────────────────────────
    "t_initial":            0.0,
    "delta_t":              0.1,
    "t_max":                1.0,
    "delta_confirm":        0.05,   # reputation gain for confirmed entry
    "delta_reject":         0.03,   # reputation loss for soft-deleted entry

    # ── Trust ─────────────────────────────────────────────────────────
    "delta_winner_gain":    0.03,
    "delta_observer_loss":  0.02,

    # ── Termination ───────────────────────────────────────────────────
    "min_rounds":           2,
    "max_rounds":           10,
    "k_consecutive":        2,      # consecutive rounds with 0 new confirmed for equilibrium
    "epsilon_entropy":      0,
    "token_budget":         50_000,

    # ── Amendment ─────────────────────────────────────────────────────
    "max_amendments":       2,

    # ── Embedding ─────────────────────────────────────────────────────
    "embedding_model":      "text-embedding-3-small",  # OpenAI
    "embedding_dim":        1536,
}
```

---

# 16. Open Problems & Risks

| ID    | Problem                                                                    | Mitigation                                                                                                                                               |
| ----- | -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| OP-01 | No formal convergence guarantee                                            | Empirical convergence via temperature + max_rounds. Documented as limitation.                                                                            |
| OP-02 | Cold-start for `agent_trust` (first run, everyone at 0.5)                  | Functionally equivalent to embedding-only bidding. Differentiates after run 1.                                                                           |
| OP-03 | Collective hallucination: all agents cite the same wrong answer            | Mitigated by heterogeneous agents (different system prompts, knowledge files, providers). Research question — documented in paper.                       |
| OP-04 | Lenient citation threshold may promote too early                           | Offset by soft delete pressure: premature confirmations get few subsequent citations and become irrelevant.                                              |
| OP-05 | Context window: round R prompt grows with confirmed layer                  | Confirmed layer shown as compact list (ID + excerpt). Full content only via `get_confirmed()` tool.                                                      |
| OP-06 | Token costs with vote sub-round: N_takers calls per thread                 | Cheap models (Haiku/GPT-4o-mini) for vote sub-round. Configurable per deployment.                                                                        |
| OP-07 | Cross-thread contamination: agents read across threads                     | Intentional. Enables emergent cross-topic synthesis. Bounded by attention_k.                                                                             |
| OP-08 | Amendment gaming: agents request expertise to extend run                   | Hard limit: max_amendments (default 2). Log all amendment proposals in audit trail.                                                                      |
| OP-09 | Thread coverage failure: no agent bids on a thread                         | Auto-trigger request_expertise. If still 0 takers after second invitation: thread dissolved into parent thread.                                          |
| OP-10 | Agent sycophancy: agents cite high-reputation agents regardless of content | Research question. Per-run reputation resets mitigate cross-run sycophancy. Cross-run trust uses citation share (quality signal) not bare participation. |

---

# 17. Appendices

## Appendix A — Theoretical Grounding

| Framework                           | Instantiation in ECSAS                                                                                                                                                                                                              |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Free-market economics (Hayek)**   | Agents self-select into contracts. No central assignment. Bid score aggregates dispersed knowledge about capability. Trust scores = price signals across runs.                                                                      |
| **Blackboard systems (HEARSAY-II)** | All coordination via shared append-only medium. No direct agent-to-agent messaging. Any agent reads and writes symmetrically. The medium IS the coordination layer.                                                                 |
| **Stigmergy (Grassé)**              | Citation counts = pheromone trails. Entries with rising citations (amplification) survive and get promoted. Entries ignored for N rounds (evaporation) are soft-deleted. The blackboard self-organizes its own relevance landscape. |
| **Reddit-like social dynamics**     | Threaded discussion, upvotes (citations), @mentions, nested replies. Familiar human coordination pattern mapped to LLM agent interaction.                                                                                           |

## Appendix B — Evaluation Metrics (Additional to Original PRD)

| Metric                 | Definition                                            | New for v3.0 |
| ---------------------- | ----------------------------------------------------- | ------------ |
| Accuracy               | Fraction of ground-truth clauses correctly identified | No           |
| Token cost             | Total tokens per run                                  | No           |
| Latency                | Wall-clock seconds, end-to-end                        | No           |
| Adversarial robustness | Accuracy degradation BT-01→BT-03                      | No           |
| Audit completeness     | Fraction of confirmed findings with traceable thread  | No           |
| **Promotion rate**     | Fraction of round-1 proposals that reach Confirmed    | **Yes**      |
| **Discussion depth**   | Average `reply_to` chain depth in Draft layer         | **Yes**      |
| **Citation diversity** | Entropy of citation distribution across agents        | **Yes**      |
| **Soft delete rate**   | Fraction of Draft entries that are soft-deleted       | **Yes**      |
| **Amendment rate**     | Average amendments per multi-step run                 | **Yes**      |

## Appendix C — Document Change Log

| Version | Date       | Changes                                                                                                                                                                                                                                                                  |
| ------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1.0     | 2026-04    | Original draft PRD                                                                                                                                                                                                                                                       |
| 2.0     | 2026-05-21 | Full redesign against V0 codebase. Feasibility scoring, dual-mode arch, backward compat.                                                                                                                                                                                 |
| 3.0     | 2026-05-23 | Complete specification. Tools-for-everything architecture. Reddit-like blackboard. Agent self-selection. Contract amendments. Cross-run trust. Vote vs. cite distinction. Thread-level bidding. Soft delete. Observer mechanics. Full prompt templates. Complete schema. |

## Appendix D - Things to consider

The Things Worth Questioning

1. The observer trust penalty is philosophically inconsistent with your principles.
   P-05 says "agent autonomy — agents self-select." P-04 says "symmetric authority." But an agent who bids honestly, loses to a better bidder, and becomes an "observer" gets punished. They did nothing wrong. They bid based on their own assessment and lost a fair auction. Penalizing voluntary participation that happened to lose feels like it violates the spirit of the free market. Worth debating with the team — the justification given is "incentivizes not over-bidding" but it could also just discourage participation in close-call domains.
2. Citation threshold M = max(1, N//3 + 1) may be too lenient at low participant counts.
   With 2 takers: M = max(1, 0+1) = 1. A single citation from one other agent promotes an entry. That's essentially a 50% majority with the minimum viable group — very easy to game or reach prematurely. You acknowledged this in OP-04 and the mitigation (soft delete pressure) is reasonable, but it's worth tracking empirically.
3. Cross-thread contamination (OP-07) is framed as intentional but has no control mechanism.
   You say agents may read_blackboard(thread_id=None) for cross-thread synthesis, and it's "bounded by attention_k." But attention_k is a blunt instrument — it doesn't discriminate between relevant cross-thread information and noise. In a high-thread run, the confirmed layer from other threads could dominate the agent's context window. No mitigation beyond "it's intentional." This could affect paper results.
4. Amendment voting includes the Market Maker as an equal voter. This is defensible but it means the MM has actual governance authority over run structure, not just advisory metadata authority. That's a slight contradiction with your "MM is advisory, not authoritative" principle from v1/v2. In practice it probably works fine — you need tie-breaking and the MM is the most neutral entity — but you should state this explicitly as a design choice rather than leave it implicit.
5. The backend orchestrator pseudocode (section 11.2) is the part most likely to cause implementation surprises. Everything else in the doc is precise. The orchestrator is described but not fully specified — particularly the async boundary between agent turns, round transitions, and the SSE stream. This is the riskiest section for implementation. Worth adding a state machine diagram before building.

The One Thing Missing
A minimal working example / "hello world" run. The document is thorough enough that someone could build from it, but there's no 5-step "here is what the simplest possible 2-agent single-thread run looks like end to end." Given that you're handing this to a team that includes people who didn't design the system, a worked example anchored to the actual code paths would save significant implementation confusion in sprint 1.

## Appendix E - The scaling problem and abuse vectors

1. Thread Explosion via Amendments
   The mechanism. Any taker can call request_expertise() to propose a new thread. If approved, a mini-auction runs and new agents join.
   The abuse. A single agent repeatedly requesting expertise across multiple domains before the max_amendments cap is hit. With max_amendments=2 and majority vote including the Market Maker, this is bounded — but the vote itself costs N_takers LLM calls per amendment proposal. In a 5-taker run, 2 amendments = 10 extra LLM calls before any real work happens. At scale with many concurrent runs, this is a DDoS vector against your token budget.
   Worse. The amendment vote requires majority of takers + MM. If the swarm is large and takers are spread across many threads, coordinating that vote takes multiple round-trips. The amendment mechanism is effectively an unbounded latency spike embedded in the middle of a run.

2. Citation Flooding
   The mechanism. cite(entry_ids=[...]) accepts a list. No stated maximum. The server enforces one cite per agent per entry per round (UNIQUE constraint), but an agent can cite every visible entry in a single call.
   The abuse. An agent cites every other agent's entries every round regardless of content. This inflates everyone's citation counts uniformly — flattening the signal that drives emergent promotion. The pheromone system becomes noise. Entries promote prematurely because M = max(1, N//3 + 1) is now trivially hit.
   The subtler version. Two colluding agents in the same thread mutually cite each other every round. With M=1 (2 takers), each agent's posts get promoted after one citation. The confirmed layer fills with unratified findings that passed the lenient threshold trivially. The system hasn't converged — it's been gamed.

3. Blackboard Pollution via Post Volume
   The mechanism. post_to_blackboard() has no stated rate limit per agent per round. An agent can post multiple entries in a single turn.
   The abuse. One verbose agent posts 10+ entries per round. The read_blackboard attention query returns top-K by cosine × citation weight — but before any citations accumulate (round 1), the ranking is pure cosine similarity. A high-volume agent saturates the top-K slots, starving other agents' proposals from being read. Silent agents (who post one thoughtful proposal) get drowned out. The system converges on the loudest agent, not the most correct one.
   The compounding effect. Each post has a content_embedding computed server-side. At 10 posts per agent per round × 5 agents × 10 rounds, you're making 500 embedding API calls per run. At scale across many concurrent runs, the embedding cost rivals the LLM cost.

4. Mention Storms
   The mechanism. mention_agents=[...] pins an entry to position 0 of the mentioned agent's next read_blackboard result. No stated cap on how many agents can be mentioned per post.
   The abuse. One agent mentions all other agents in every post. Every agent's next read is hijacked to surface this one agent's content regardless of attention score. This bypasses the entire attention mechanism — the pheromone system is irrelevant because mentions override it. At 5 agents × 10 rounds = 50 mention injections from one agent, the entire swarm's reading behavior is controlled by a single actor.

5. Soft Delete Evasion
   The mechanism. Soft delete triggers when rounds_since_citation >= N_DECAY_ROUNDS. An entry is exempt if cited at least once within that window.
   The abuse. An agent self-cites — but server-side filtering removes self-citations, so this doesn't work directly. However, two colluding agents can keep each other's entries alive indefinitely by citing them just before the decay threshold. A post that should have died in round 3 survives to round 10 consuming attention-query slots and context window space forever. The blackboard never cleans itself.

6. Context Window Amplification via Cross-Thread Reads
   The mechanism. read_blackboard(thread_id=None) enables cross-thread search. Bounded only by attention_k.
   The abuse. In a high-thread run (say 5 threads × 10 agents × 10 rounds), the confirmed layer alone could contain 50+ entries. An agent reading cross-thread gets up to attention_k=10 entries from a pool of hundreds. The embeddings for all of them must be scored — that's hundreds of cosine similarity computations server-side per read call. If every agent reads cross-thread every round, and you have many concurrent runs, this is a CPU-bound server bottleneck. Not an LLM cost problem — a compute problem.

7. Token Budget Gaming
   The mechanism. Budget is tracked via TokenTracker and checked at the start of each agent turn. If exhausted, the run halts with termination_reason="budget".
   The abuse. A verbose agent intentionally exhausts the budget before other agents can contribute. By generating extremely long posts and reading the full blackboard multiple times per turn, one agent can consume a disproportionate share of the 50,000-token default budget. The system halts "cleanly" but with a one-sided confirmed layer — only the verbose agent's proposals survived.
   The more subtle version. The budget is shared across all threads. A run with 5 threads and one extremely active thread will starve the other 4 threads of budget. The final output for the active thread looks converged; the others terminate prematurely with no confirmed findings.

8. Embedding Model as Single Point of Failure
   The mechanism. The entire auction (preliminary scores), attention queries, soft-delete decisions, and promotion rankings all depend on text-embedding-3-small. Every contract, thread, agent capability profile, and draft entry gets embedded.
   The abuse. Not adversarial but architectural. At scale, every embedding call is a round-trip to OpenAI's API. In a 5-thread × 5-agent × 10-round run, you could have 300+ embedding calls per run. If the embedding API has latency spikes (common under load), the entire swarm stalls waiting for embedding responses. There's no fallback or caching mechanism specified in the PRD.
