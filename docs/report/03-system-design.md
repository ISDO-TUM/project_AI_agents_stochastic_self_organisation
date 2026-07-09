# 3. System Design

The previous chapter argued that fixing the orchestrator's failure modes requires more than a better prompt; it requires a system in which coordination strategies can be built, observed, and compared. This chapter describes that system: *Stochastic Agents*, a full-stack platform for running groups of LLM-backed agents and studying how they organise. The chapter deliberately stays at the platform level. The execution engines that run *inside* the platform (the broadcast baseline, its topology and consensus refinements, and finally the Market-Hive engine) are the subject of Chapters 4 through 6; here we describe the vessel they all share.

We first walk through the design decisions that shaped the platform (Section 3.1) and the resulting architecture (Section 3.2). Section 3.3 then tours the application from the user's perspective, Section 3.4 follows a run through the system's internals, and Section 3.5 covers how the project is developed, tested, and deployed.

## 3.1. Design Decisions

Six decisions, made early, determined most of what follows. We present them with their rationale rather than as a formal requirements list: in a project of this size, the decisions *are* the requirements.

**One platform, pluggable engines.** The central bet of the project is that we would not get the coordination mechanism right on the first attempt; Chapters 4 to 6 confirm this. We therefore built a single run interface, `POST /api/simulation/run`, behind which execution engines are interchangeable: a `mode` field selects the engine, and everything else (the agent roster, the knowledge files, the persistence layer, the live-streaming channel, the history views) is shared infrastructure that does not care which engine is running. This is the seam that let us evolve from a broadcast baseline to a market-based swarm without ever rebuilding the application around it.

**A modular monolith, not microservices.** The backend is one FastAPI process. Each engine lives in its own self-contained package (`server/topology/`, `server/market_hive/`) with its own logic, routes, and tools, so the two systems read as independent at a glance; yet they deploy as one unit, share one database schema, and call each other with function calls rather than network hops. For a six-person team building a research prototype, the operational simplicity of a single deployable outweighed any scaling argument for splitting services.

**Every run is a persisted record.** Nothing about a run lives only in UI memory. Each execution creates a *trial*, decomposed into rounds, connections, and messages, written to the database as it happens. Replay, debugging, the history views, and the entire evaluation of Chapter 7 read from this same persisted trace. The rule is absolute by design: if an interaction between agents is not in the record, it did not happen. This is what turns the application from a demo into an instrument.

**Live streaming over Server-Sent Events.** A multi-agent run takes minutes (dozens of sequential LLM calls), and a spinner for five minutes is indistinguishable from a crash. Every run therefore streams its progress to the browser as it executes, one event per meaningful step (an agent responding, a message posted, a decision made), over Server-Sent Events (SSE). We chose SSE over WebSockets because the channel is strictly one-directional (the client only listens), and SSE gives us that with plain HTTP, no connection-upgrade machinery, and trivial proxying.

**Provider-agnostic agents, keys supplied by the user.** An agent declares *which* provider and model it runs on (OpenAI, Anthropic, Groq, or Gemini) as part of its profile, and the model layer resolves credentials at request time: from per-request headers supplied by the browser (a bring-your-own-key scheme, so the deployed instance stores no secrets) or from server environment variables as a fallback. Mixed-provider teams, such as a Claude analyst debating a GPT-4o counsel, are consequently a configuration choice, not an engineering effort.

**Behaviour the system depends on must not rely on model compliance.** LLM output is treated as untrusted input everywhere. Every action an agent can take is a *tool call* against a registered, schema-validated tool; guardrails validate inputs and outputs around each model call; and rules the coordination logic depends on (length limits, uniqueness of votes, referential integrity of replies) are enforced server-side by validation and database constraints, never merely requested in a prompt. Prompts steer behaviour; the platform *enforces* it. Later chapters invoke this rule repeatedly, because in a system whose participants are stochastic, any invariant that is only politely asked for will eventually be violated.

## 3.2. Architectural Overview

The platform is a classic three-tier web application with one external dependency class: the LLM providers.

> **[Figure 3.1: Architecture overview.** Block diagram: Next.js client (canvas, run controls, SSE consumer) ↔ FastAPI server (shared platform: routes, LLM layer, tools, guardrails, persistence; two engine packages: Topology, Market-Hive) ↔ PostgreSQL; arrows from the server to external model providers. Adapt from `docs/architecture.md` sections 2 to 4.]

**Client.** A Next.js 16 / React 19 single-page application (TypeScript, Tailwind CSS, Framer Motion for animation). Its centrepiece is an infinite canvas on which users author their agent team; around it sit the run controls, the live activity surfaces, and the history and statistics views. The client holds no authoritative state: it renders what the API tells it, either via REST for configuration data or via the SSE stream during a run.

**Server.** A Python 3.12 / FastAPI application. The shared platform code sits flat under `server/`: `db/` (persistence via SQLAlchemy Core), `llm/` (the multi-provider model layer), `tools/` (the shared tool registry: every capability an agent can invoke during a turn is a registered tool with a validated input schema, and both engines draw their per-phase tool sets from this registry), `guardrails/` (input/output validation), `schemas/` (request/response models), and `routes/` (agent and file CRUD, model listing, and the mode-dispatched run endpoint). The two engine packages sit alongside and contain everything specific to their coordination strategy. A deliberate design rule keeps this boundary clean: engine *behaviour* lives in the engine packages; everything both engines need lives in the shared platform and is owned by neither.

**Database.** PostgreSQL, accessed asynchronously (asyncpg). The schema for both engines is defined in a single module and created on startup, which keeps the two engines honest about sharing one data model. The test suite points the identical schema at an in-memory SQLite database, so tests run with no external services at all, a property Section 3.5 returns to.

| Layer | Technology | Role |
|---|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS | Canvas authoring UI, live run views, history |
| Backend | Python 3.12, FastAPI, Uvicorn | REST + SSE API, execution engines, guardrails |
| Persistence | PostgreSQL (SQLAlchemy Core, asyncpg) | Agents, knowledge files, full run history |
| Model access | OpenAI, Anthropic, Groq, Gemini SDKs | Agent turns, embeddings, structured calls |
| Observability | Langfuse | Per-call LLM traces linked to runs |

*Table 3.1: Technology stack.*

The one architectural element worth singling out is the **engine dispatch**. When a run request arrives, the endpoint inspects `mode` and hands the request to the corresponding engine, together with the shared services it needs. Each engine returns the same thing: an asynchronous stream of typed simulation steps. Everything downstream (streaming, persistence, the UI) consumes that one step format. Adding the Market-Hive engine in Chapter 6 required no changes to this contract.

## 3.3. Guided Tour

This section walks through the application as a user experiences it, using the energy-contract scenario that recurs throughout this report: a team of five specialists (contract counsel, financial risk, energy markets, regulatory compliance, and ESG) assembled to assess a supplier contract. The tour deliberately stays on the surfaces every mode shares; the engine-specific views, in particular the Market-Hive boards, are presented with their engine in Chapter 6. The goal here is orientation; the mechanics behind each screen follow in Section 3.4.

**The canvas.** The application opens onto a free-form canvas, the workspace where a team is assembled. Agents appear as nodes; knowledge files as attachable documents; edges express which agent can read which document. A toolbar offers creation, import and export, and the run controls. Ready-made team configurations can be imported from a JSON file in one click, which is how the demo scenarios ship.

> **[Figure 3.2: The canvas with the energy-contract team loaded.** Five agent nodes, three knowledge-file nodes, attachment edges visible. Capture in the standard (topology-mode) canvas so the edges show; the swarm-mode canvas, which replaces the wired graph with the blackboard panels, is shown in Chapter 6. Consistent window size; this state is the base for all remaining screenshots.]

**Authoring an agent.** Creating or editing an agent opens its profile: a name, a role description, the system prompt that defines its expertise and behaviour, and the provider and model it runs on. This profile is all an agent *is* from the platform's perspective: a persisted, reusable specialist that exists independently of any particular run.

> **[Figure 3.3: The agent editor.** Show the Contract Counsel agent: system prompt visible, provider/model selector open to show the multi-provider choice.]

**Attaching knowledge.** Knowledge files hold the raw material agents work with: here, the supplier contract itself, market benchmarks, and the applicable regulation. Dragging an edge from a file to an agent grants that agent access; during a run the file's content is made available to the agent's turns. Distributing documents *unevenly* across the team is deliberate and useful: it creates the information asymmetry that makes agent-to-agent communication necessary rather than decorative.

> **[Figure 3.4: Knowledge attachment.** The contract document attached to Counsel and FinRisk but not the others; one edge mid-drag if possible.]

**Configuring and launching a run.** The run dialog asks for the task prompt and the execution parameters: which engine mode to use and its settings (rounds, team-size limits, budgets, depending on the mode). These parameters are exactly the variables the evaluation in Chapter 7 sweeps.

> **[Figure 3.5: Run configuration dialog** with the energy-contract prompt entered and mode selection visible.]

**Watching a run.** Once launched, the run streams live. Agents visibly take turns; their contributions appear as they are produced; the activity surfaces fill event by event. The exact view depends on the engine: the modes of Chapters 4 and 5 render a message log over the communication graph, while the Market-Hive mode renders its shared blackboard (Chapter 6). The delivery mechanism, however, is identical, and in both cases the user watches the run *happen* rather than waiting for a result. When the run completes, the outcome is presented directly.

> **[Figure 3.6: A run in flight.** Mid-run capture of the tour's run: agents marked as responding, the activity log filling. Capture in a baseline mode; the swarm run surfaces (boards, agent dock, final-answer reveal) belong to Chapter 6's figures. **Figure 3.7: Run completion** with the outcome presented.]

**Looking back.** Because every run is persisted (Section 3.1), the history section lists past trials and opens any of them for inspection: the rounds, who talked to whom, and every message exchanged, alongside aggregate statistics. Nothing on these pages is recomputed from memory: they are views over the same record the run wrote while executing.

> **[Figure 3.8: History and statistics view** of the tour's completed run. Chapter 6 separately shows the archive of a *swarm* run (`ui_history.png`); keep this capture to the baseline run so the two figures don't duplicate.]

## 3.4. Data Flow

We now follow a single run through the system, the machinery behind the tour above. The description is engine-agnostic; the engine-specific behaviour inside step two is precisely what Chapters 4 to 6 elaborate.

> **[Figure 3.9: Sequence diagram of a run.** Client → run endpoint → engine; loop of agent turns hitting the LLM providers; each step both persisted to the database and yielded to the SSE stream; final answer closes the stream. Adapt from `docs/architecture.md` section 5.]

**1. Request and dispatch.** The client sends the prompt and settings to the run endpoint, attaching the user's provider keys as request headers. The endpoint creates the trial record, selects the engine by `mode`, and opens the response as an SSE stream.

**2. Execution as a stream of steps.** The engine runs its coordination logic, whatever that is for the mode at hand, and *yields typed steps* as it goes: an agent starting a turn, a message produced, a phase completed, a final answer reached. Each agent turn is ultimately a call through the shared LLM layer, which resolves the provider, applies guardrails to inputs and outputs, and traces the call in Langfuse under the trial's identifier, so every model interaction in a run can be audited later at token level.

**3. Persistence in stride.** Steps are recorded as they are yielded, not at the end: rounds, connections, and messages are inserted while the run executes. A run that crashes or is interrupted mid-flight therefore still leaves a valid, inspectable prefix of its history. For a system whose runs take minutes and burn real API budget, partial records are far more useful than all-or-nothing ones.

**4. Streaming to the client.** The same steps are serialised as SSE events. Long gaps between events are bridged by keepalive comments so intermediaries do not drop the connection, an unglamorous detail that proved essential in deployment, where a proxy silently cut any stream that stayed quiet for thirty seconds. On the client, a reducer folds the incoming events into UI state; the live view is therefore a pure function of the event stream, which makes it trivially consistent with what the server persisted.

The data these steps land in is deliberately simple: four tables in a strict hierarchy.

> **[Figure 3.10: Entity-relationship sketch.** trials → rounds → connections → messages, with agents and knowledge_files as independent, reusable entities referenced from connections. Adapt from `docs/data-model.md`.]

A **trial** is one end-to-end run of the system on one prompt. It contains ordered **rounds**; each round contains **connections**, directed edges recording who communicated with whom in that round, and each connection carries the **messages** exchanged along it. Two choices in this schema matter more than they look. First, connections are stored *per round* rather than on the agents: the communication graph is thereby allowed to change between rounds, and its full evolution is preserved. That is not incidental, since round-by-round rewiring is one of the central mechanisms this project studies. Second, message payloads are stored as plain text rather than a rigid schema, which let the same four tables absorb three generations of engines (the Market-Hive engine adds tables of its own for its market structures, but mirrors its activity into this hierarchy so that history and statistics remain uniform across modes). Agents and knowledge files live outside the hierarchy entirely: they are reusable assets referenced by runs, not owned by them.

## 3.5. From Local to Cloud

The platform is a pnpm monorepo with the client and server as workspaces. A single setup script installs the toolchain (`uv` for Python, `pnpm` for Node) and all dependencies; `pnpm dev` then starts both halves (the UI on port 3000, the API on port 8000) against a bundled PostgreSQL. A Docker Compose configuration provides the same stack in containers for anyone who prefers not to install toolchains at all.

Two properties of the development workflow are worth recording, because they shaped how quickly the engine iterations of Chapters 4 to 6 could happen.

**The test suite runs offline.** Over 600 backend tests execute against in-memory SQLite with the LLM layer replaced at well-defined seams: the engines accept injectable agent runners, contract sources, and embedders precisely so tests can drive full multi-round runs deterministically, with no API keys and no network. A complete run of the suite takes seconds, which means the coordination logic, the hardest code in the project to get right, could be developed against fast, reproducible end-to-end tests rather than against live (and paid) model calls.

**Quality gates are automatic.** Every pull request passes lint and type checks on both halves (ruff and mypy on the server; ESLint and the TypeScript compiler on the client) plus the full test suite in GitHub Actions before it can merge. Formatting is enforced by git hooks, so none of it depends on discipline.

For deployment, the same two Dockerfiles that serve local Compose are built and shipped to **Railway** by a deploy workflow on merges to main: a server service, a client service, and a managed PostgreSQL. The server normalises Railway's database URL to its async driver and creates or migrates its schema on startup, so a fresh environment needs no manual database step. Notably, the deployed instance holds no LLM credentials: visitors supply their own provider keys in the UI, which travel as per-request headers (Section 3.1), so the public instance can be shared freely without anyone's API budget attached to it.

The result is that the distance from `git clone` to a running local instance is two commands, and the distance from a merged pull request to the live deployment is zero. For a research prototype whose purpose is to be *demonstrated and experimented with*, we consider this operational lightness a design feature on par with the architecture itself.
