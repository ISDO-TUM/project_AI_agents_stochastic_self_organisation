# Architecture Design: Multi-Agent Stochastic Self-Organisation

> This document is the architecture source of truth for product, engineering, and review stakeholders.

## 1) Scope and Audience

### Scope

This architecture covers:

- run orchestration from prompt to outcome
- topology behavior (static and dynamic)
- consensus behavior (all supported modes)
- persistence and replay boundaries
- user operating flow and governance checks

### Audience

- **Primary:** engineers and reviewers implementing or validating behavior
- **Secondary:** product and technical stakeholders evaluating system guarantees

### Out of scope

- low-level code organization
- framework-specific implementation details
- deployment vendor specifics

---

## 2) Conceptual Architecture (L1)

This view answers: "What are the core system boundaries and who interacts with whom?"

```mermaid
flowchart LR
    U[User]
    SYS[Multi-Agent Reasoning System]
    EXT1[Model Providers]
    EXT2[Persistent History Store]

    U --> SYS
    SYS --> EXT1
    SYS --> EXT2
    EXT2 --> SYS
```

Key idea: one system boundary, explicit external dependencies, clear ownership of orchestration.

---

## 3) Component Architecture (L2)

This view answers: "Which core modules exist and how they collaborate?"

```mermaid
flowchart TB
    subgraph UX[Experience]
      CFG[Settings + Run Controls]
      CV[Canvas + Topology Authoring]
      LG[Activity Log + History Navigation]
    end

    subgraph CORE[Reasoning Core]
      ORCH[Run Orchestrator]
      TOPO[Topology Controller]
      CONS[Consensus Engine]
      SAFE[Validation + Guardrails]
    end

    subgraph DATA[Trace and State]
      TR[(Trials)]
      RD[(Rounds)]
      CN[(Connections)]
      MS[(Messages)]
    end

    CFG --> ORCH
    CV --> ORCH
    ORCH --> TOPO
    ORCH --> CONS
    ORCH --> SAFE
    ORCH --> TR
    ORCH --> RD
    ORCH --> CN
    ORCH --> MS
    LG --> MS
```

Design rule: each component has one primary responsibility and a stable interface.

---

## 4) Deployment / Runtime Boundary View

This view answers: "Which runtime zones exist and what crosses boundaries?"

```mermaid
flowchart LR
    subgraph Z1[Interaction Zone]
      UI[User Interaction Surface]
    end

    subgraph Z2[Execution Zone]
      API[Run Interface]
      ENG[Reasoning Engine]
    end

    subgraph Z3[Persistence Zone]
      STORE[(Run History)]
    end

    subgraph Z4[External AI Zone]
      LLM[(Model Endpoints)]
    end

    UI --> API
    API --> ENG
    ENG --> STORE
    ENG --> LLM
    UI --> API
    API --> STORE
```

Non-negotiable boundary rule: all replay and observability comes from persisted history, not transient UI memory.

---

## 5) Sequence Diagram (Run Lifecycle)

This view answers: "In what order does execution happen?"

```mermaid
sequenceDiagram
    participant User
    participant Runtime
    participant Topology
    participant Consensus
    participant History

    User->>Runtime: Start run (prompt + settings)
    Runtime->>History: Create trial
    Runtime->>Runtime: Broadcast phase

    loop Discussion rounds
        Runtime->>Topology: Resolve communication graph
        Runtime->>Runtime: Execute agent exchanges
        Runtime->>History: Persist round artifacts
    end

    Runtime->>Consensus: Apply selected mode
    Consensus->>History: Persist decision artifacts
    Runtime->>History: Mark run completed/failed
```

---

## 6) Data Flow Diagram (Execution Data Path)

This view answers: "How does information move and transform?"

```mermaid
flowchart TD
    IN[Prompt + Settings]
    P1[Broadcast Processing]
    P2[Round Exchange Processing]
    P3[Consensus Processing]
    OUT[Outcome]
    DS[(Run Trace Store)]

    IN --> P1 --> P2 --> P3 --> OUT
    P1 --> DS
    P2 --> DS
    P3 --> DS
```

Traceability rule: each transformation stage must emit a corresponding persisted artifact.

---

## 7) Topology Modes

Topology defines the communication graph used during round exchange.

- **Static topology** keeps the graph fixed for the run.
- **Dynamic topology** allows graph rewiring between rounds.

```mermaid
flowchart LR
  T{Topology Mode}
  S[Static]
  D[Dynamic]

  T --> S --> S1[Use predefined edges]
  S1 --> S2[Graph unchanged across rounds]

  T --> D --> D1[Agents declare peers]
  D1 --> D2[Controller rewires graph]
  D2 --> D3[Optional fan-out cap]
```

### 7.1 Static Topology

- **Purpose:** maximize predictability and comparability across runs.
- **Mechanics:** run uses predefined communication edges only; no rewiring occurs.
- **Result profile:** stable interaction structure and easier run-to-run comparison.

### 7.2 Dynamic Topology

- **Purpose:** enable adaptive, relevance-driven communication.
- **Mechanics:** agents declare peers each round, and the controller builds the next graph (with optional fan-out limits).
- **Result profile:** higher self-organization potential with increased structural variance.

| Dimension             | Static Topology       | Dynamic Topology                    |
| --------------------- | --------------------- | ----------------------------------- |
| Graph evolution       | fixed during run      | rewired between rounds              |
| Communication control | predefined links      | discovered links + selection policy |
| Predictability        | higher                | adaptive                            |
| Best fit              | controlled comparison | self-organization experiments       |

### 7.3 Phone Registry (Dynamic) vs. Fully-Connected (Static)

In dynamic mode, instead of wiring every agent to every other agent, each agent
uses a **phone registry** to look up peers on demand: it searches a per-run index
(by meaning, using embeddings) for the agents most relevant to what it needs, then
names them in a `CONNECT:` line. The controller rebuilds the graph from those
choices each round, keeps the most useful peers (a reputation score), and caps how
many each agent may pick (fan-out). Static simply connects everyone, all the time.

**Pros of the registry approach:**

- **Scales better:** each agent talks to a few relevant peers, not all N, so cost
  and context size stay manageable as the number of agents grows.
- **Less noise:** agents hear from peers that actually match their topic, which
  helps reach a clean answer.
- **Self-improving routing:** agents that give well-grounded, agreed-upon answers
  get heard more; weak or off-topic agents drop out over rounds.
- **Can start from nothing:** agents with no initial connections can still find
  peers and organize themselves.

**Cons of the registry approach:**

- **Extra cost and complexity:** it builds an embedding index and makes lookup
  calls each round; static does none of this.
- **Can over-prune:** the graph may split into cliques, so a correct-but-unpopular
  agent might never be heard. Fully-connected guarantees everyone is always heard.
- **Less predictable / slower to settle:** the graph keeps changing until it
  stabilizes, often taking more rounds than static.
- **Depends on good agent descriptions:** discovery is only as good as each
  agent's name, description, and files; thin profiles weaken the matching.

**Rule of thumb:** use the registry/dynamic setup when there are many agents or
noisy context; use static fully-connected for small, controlled runs where you
want every agent heard and results easy to compare.

---

## 8) Consensus Modes

Consensus defines how distributed agent outputs are interpreted into an outcome signal.

```mermaid
flowchart LR
  C{Consensus Mode}
  B[broadcast_no_consensus]
  W[weighted_opinion_pooling]
  P[plurality_voting]

  C --> B --> B1[No reducer]
  B1 --> B2[Parallel outcomes preserved]

  C --> W --> W1[Trust-weighted integration]
  W1 --> W2[Preference stabilizes over rounds]

  C --> P --> P1[Vote normalization + tally]
  P1 --> P2[Plurality winner and rationale]
```

### 8.1 broadcast_no_consensus

- **Purpose:** preserve the diversity of independent agent outcomes.
- **Mechanics:** no global reducer is applied after discussion rounds.
- **Result profile:** parallel outputs, suitable for exploration and analysis.

### 8.2 weighted_opinion_pooling

- **Purpose:** combine outputs through trust-sensitive weighting.
- **Mechanics:** weighted integration reflects evolving confidence/affinity signals.
- **Result profile:** stabilized weighted preference instead of hard-majority decisions.

### 8.3 plurality_voting

- **Purpose:** produce a clear single winner signal.
- **Mechanics:** normalized votes are tallied and resolved by plurality.
- **Result profile:** decisive output with explicit rationale trace.

| Consensus mode           | Core mechanism             | Decision signal                      |
| ------------------------ | -------------------------- | ------------------------------------ |
| broadcast_no_consensus   | no reducer                 | per-agent outputs remain independent |
| weighted_opinion_pooling | trust-weighted integration | stabilized weighted preference       |
| plurality_voting         | normalized vote tally      | plurality winner and reasons         |

---

## 9) Operating Mode Comparison (Topology x Consensus)

```mermaid
flowchart TD
  A[Run Configuration]
  A --> B[Choose Topology]
  A --> C[Choose Consensus]
  B --> D[Communication Pattern]
  C --> E[Decision Pattern]
  D --> F[Observed Run Behavior]
  E --> F
```

| Topology \ Consensus | broadcast_no_consensus                    | weighted_opinion_pooling                 | plurality_voting                        |
| -------------------- | ----------------------------------------- | ---------------------------------------- | --------------------------------------- |
| static               | stable discussion without final reducer   | stable graph with trust-weighted outcome | stable graph with majority-style winner |
| dynamic              | adaptive discussion without final reducer | adaptive graph + trust-weighted outcome  | adaptive graph + majority-style winner  |

---

## 10) User Flow

```mermaid
flowchart TD
  A[Define objective]
  B[Design communication graph]
  C[Define topology mode]
  D[Define consensus mode]
  E[Set rounds fan-out and policy controls]
  F[Execute run]
  G[Monitor live activity]
  H{Need deeper diagnosis?}
  I[Inspect rounds connections and messages]
  J[Evaluate outcome and adjust strategy]

  A --> B --> C --> D --> E --> F --> G --> H
  H -- Yes --> I --> J
  H -- No --> J
  J --> A
```
