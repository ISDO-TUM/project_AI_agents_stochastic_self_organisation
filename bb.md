# ECSAS v3 — Implementation Task Groups

Pulled from `docs/PRD-ECSAS-v3.md` (§5.2 backend components + §12 frontend + §13 roadmap). Not forced into exactly 6 — sizes vary a lot, so see the pairing notes at the bottom.

| # | Block | Scope | Key files/modules | Depends on |
|---|---|---|---|---|
| 1 | **Foundation / Data layer** | File-backed SQLite, all new tables (contracts, threads, bids, draft_entries, citations, votes, confirmed_entries, reputation, agent_trust, amendments), Pydantic schemas | `server/db/__init__.py`, new migration, `server/swarm/schemas.py` | None — must land first |
| 2 | **Market Maker** | Prompt → Contract + Threads via structured LLM call; casts 1 vote on amendments; fallback contract on failure | `server/swarm/market_maker.py` | Block 1 |
| 3 | **Auction Engine** | Embedding service, invitation by cosine floor, self-selection (`submit_bid`/`abstain`), bid scoring, thread-level bidding, observer designation | `server/swarm/auction.py`, `server/swarm/embeddings.py` | Block 1, 2 |
| 4 | **Blackboard Core** | Append-only Draft/Confirmed storage, `read_blackboard`/`post_to_blackboard`/`cite`/`vote`/`get_confirmed` tools, attention query, soft-delete, promotion check, mentions | `server/swarm/blackboard.py` | Block 1 |
| 5 | **Convergence Engine** | Confidence score (cold-start vote + per-round citation share), conceding temperature, per-run reputation updates | `server/swarm/convergence.py` | Block 4 |
| 6 | **Contract Amendment Engine** | `request_expertise` tool, majority vote (takers + MM), new thread creation, mini-auction, hard cap | `server/swarm/amendment.py` | Block 2, 3, 4 |
| 7 | **Termination Engine + Orchestrator glue** | Equilibrium detection, token budget tracking, final-output selection, `run_swarm()` stitching every component together + SSE event emission | `server/swarm/termination.py`, orchestrator pseudocode in §11.2 | All of 2–6 |
| 8 | **Trust Registry** | Cross-run trust update at run end (winner gain / observer loss) | `server/swarm/trust.py` | Block 3, 7 — small, natural pairing with Auction or Termination |
| 9 | **API surface** | `POST /api/simulation/run` (SSE), `GET .../blackboard`, `GET .../audit`, `GET .../status`, `GET /api/agents/{id}/trust` | `server/routes/simulation.py` | Blocks 4, 7, 8 |
| 10 | **Frontend — Canvas & config** | Mode gate, SwarmConfigModal, Market Maker/Thread canvas nodes, bid/abstain/promotion/soft-delete animations, `useSimulation` SSE refactor | `client/components/canvas/swarm-nodes.tsx`, `thread-node.tsx`, `swarm-config-modal.tsx`, `hooks/useSimulation.ts` | Block 9 (needs SSE shape) |
| 11 | **Frontend — Blackboard UI** | BlackboardPanel/ThreadTabs/DraftSection/ConfirmedSection, the 4 distinct entry-type visual treatments (proposal/reply/vote/system), citation progress bar, trust panel, agent citation/trust card | `client/components/blackboard-panel.tsx`, `draft-entry.tsx`, `confirmed-section.tsx`, `trust-panel.tsx` | Block 9 |
| 12 | **Evaluation harness** | BT-01/02/03 benchmark tasks, baselines B-01/02/03, evaluation runner (5×3×4), stats analysis, new ECSAS metrics (promotion rate, discussion depth, citation diversity, etc.) | `server/evaluation/` (new) | Block 7 (needs a working run to evaluate) |

## Notes for splitting across 6 people

- Blocks **1+4** (Foundation + Blackboard) pair naturally — same person/pair owns the schema they're built on.
- Block **8** (Trust Registry) is tiny (~one function) — fold into whoever owns Auction (3) or Termination (7).
- Block **9** (API surface) is thin glue — usually falls to whoever owns Termination/Orchestrator (7).
- Frontend (10+11) is the single biggest chunk of work in the PRD (§12) — worth being 2 people, not 1.
- Evaluation (12) only becomes possible once Block 7 produces a working end-to-end run, so it's naturally a later-phase / parallel-track assignment rather than week-1 work.

**Suggested 6-owner split:** (1+4) Data/Blackboard · (2) Market Maker · (3+8) Auction/Trust · (5) Convergence · (6+7+9) Amendment/Termination/Orchestrator/API · (10+11) Frontend — with Evaluation (12) picked up by whoever frees up first once a run works end-to-end.