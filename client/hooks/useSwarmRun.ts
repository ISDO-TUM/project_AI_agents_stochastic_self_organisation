"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import {
  BlackboardState,
  ConfirmedEntry,
  ContractInfo,
  DraftEntry,
  Ratification,
  ThreadInfo,
} from "@/lib/types";
import { useApiKeys, apiKeyHeaders } from "@/lib/api-keys-context";
import { loadSession, saveSession } from "@/lib/session-persist";
import { userIdHeaders } from "@/lib/user-id";
import type { SwarmRunConfig } from "../components/swarm-config";

// SSE goes through the Next rewrite proxy by default (relative ""). If that proxy
// buffers the stream, set NEXT_PUBLIC_API_URL (e.g. http://localhost:8000) to hit
// the backend directly — CORS already allows the dev origin.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

// One Server-Sent Event from `POST /api/simulation/run` (engine="swarm").
interface SwarmStreamStep {
  type: string;
  msg: string;
  node_id?: string | null;
  thread_id?: string | null;
  entry_id?: string | null;
  data?: Record<string, unknown> | null;
}

const EMPTY_BOARD: BlackboardState = {
  threads: [],
  confirmed: [],
  draft: [],
  pendingReplies: [],
  loading: false,
  error: null,
};

export interface SwarmRunState {
  active: boolean;
  done: boolean;
  runId: string | null;
  // Shared-history linkage emitted on the run's first frame: the trial row
  // mirroring this run and the experiment grouping it on the statistics page.
  trialId: string | null;
  experimentId: string | null;
  blackboard: BlackboardState;
  // Agent IDs currently producing a turn (their LLM call is in flight). Drives
  // the "is responding…" pulse on the agent dock chips.
  responding: string[];
  // The brief answer synthesised from the confirmed findings at run end, carried
  // on the final `convergence` step. Null until the run completes (or if a run
  // produced no answer).
  finalAnswer: string | null;
  // The takers' vote on `finalAnswer`, carried on the same `convergence` step.
  // Null until the run completes, or if ratification didn't run (no findings).
  ratification: Ratification | null;
  error: string | null;
}

const IDLE: SwarmRunState = {
  active: false,
  done: false,
  runId: null,
  trialId: null,
  experimentId: null,
  blackboard: EMPTY_BOARD,
  responding: [],
  finalAnswer: null,
  ratification: null,
  error: null,
};

// Survives a route navigation (e.g. to /statistics and back), which unmounts
// this hook and would otherwise wipe the board. No live connection survives
// the unmount either way, so a persisted "active" run is rehydrated as
// interrupted rather than resumed.
// v2: BlackboardState gained `pendingReplies` — bumped so a v1 session
// persisted before that field existed doesn't rehydrate into a shape the
// reducer's `settleDraft` (which spreads `bb.pendingReplies`) can't handle.
const PERSIST_KEY = "swarm.board.v2";

function loadPersisted(): SwarmRunState {
  const persisted = loadSession<SwarmRunState>(PERSIST_KEY);
  if (!persisted) return IDLE;
  return { ...persisted, active: false, responding: [] };
}

type Action =
  | { type: "BEGIN" }
  | {
      type: "RUN_ID";
      runId: string;
      trialId?: string | null;
      experimentId?: string | null;
    }
  | { type: "CONTRACT"; contract: ContractInfo }
  | { type: "THREADS"; threads: ThreadInfo[] }
  | { type: "POST"; entry: DraftEntry }
  | { type: "CITE"; entryId: string; citerName: string; round: number }
  | { type: "PROMOTE"; confirmed: ConfirmedEntry }
  | { type: "RECITE"; confirmed: ConfirmedEntry }
  | { type: "DELETE"; entryId: string }
  | { type: "CONTEST"; entryId: string; status: ConfirmedEntry["status"] }
  | { type: "THINKING_RESET" }
  | { type: "THINKING_ADD"; nodeId: string }
  | {
      type: "DONE";
      finalAnswer?: string | null;
      ratification?: Ratification | null;
    }
  | { type: "ERROR"; error: string }
  | { type: "RESET" };

// ── Draft-tree helpers (nest replies under their parent, mutate by id) ─────────

function tryInsertEntry(
  tree: DraftEntry[],
  entry: DraftEntry,
): { tree: DraftEntry[]; placed: boolean } {
  if (!entry.reply_to) return { tree: [...tree, entry], placed: true };
  const [next, placed] = insertEntryRec(tree, entry);
  return placed ? { tree: next, placed: true } : { tree, placed: false };
}

/**
 * Places a newly-arrived entry into the draft tree, then retries any replies
 * that arrived before their own parent did. Concurrent turns stream their
 * steps back in *task*-completion order (see `_run_turns` server-side), not
 * DB-write order — an entry reply-citing something from the same round can
 * legitimately stream in before that something's own `bb-post` event does,
 * even though the reply's `reply_to` was validly resolved against the DB at
 * write time. Treating "parent not in the tree yet" as permanent (the old
 * behavior) rendered those as false top-level orphans; holding them in
 * `pendingReplies` and retrying on every later arrival nests them correctly
 * once the parent does show up, which — since the parent's post_to_blackboard
 * call already completed — it always eventually does within the same stream.
 */
function settleDraft(
  tree: DraftEntry[],
  pendingReplies: DraftEntry[],
  incoming: DraftEntry,
): { tree: DraftEntry[]; pendingReplies: DraftEntry[] } {
  let nextTree = tree;
  let queue = [...pendingReplies, incoming];
  let progressed = true;
  while (progressed) {
    progressed = false;
    const stillPending: DraftEntry[] = [];
    for (const entry of queue) {
      const result = tryInsertEntry(nextTree, entry);
      if (result.placed) {
        nextTree = result.tree;
        progressed = true;
      } else {
        stillPending.push(entry);
      }
    }
    queue = stillPending;
  }
  return { tree: nextTree, pendingReplies: queue };
}

function insertEntryRec(
  tree: DraftEntry[],
  entry: DraftEntry,
): [DraftEntry[], boolean] {
  let placed = false;
  const next = tree.map((node) => {
    if (placed) return node;
    if (node.id === entry.reply_to) {
      placed = true;
      return { ...node, children: [...node.children, entry] };
    }
    if (node.children.length > 0) {
      const [children, childPlaced] = insertEntryRec(node.children, entry);
      if (childPlaced) {
        placed = true;
        return { ...node, children };
      }
    }
    return node;
  });
  return [next, placed];
}

function updateEntry(
  tree: DraftEntry[],
  targetId: string,
  fn: (entry: DraftEntry) => DraftEntry,
): DraftEntry[] {
  return tree.map((node) => {
    if (node.id === targetId) return fn(node);
    if (node.children.length > 0) {
      return { ...node, children: updateEntry(node.children, targetId, fn) };
    }
    return node;
  });
}

function reducer(state: SwarmRunState, action: Action): SwarmRunState {
  const bb = state.blackboard;
  switch (action.type) {
    case "BEGIN":
      return { ...IDLE, active: true };
    case "RUN_ID":
      return {
        ...state,
        runId: action.runId,
        trialId: action.trialId ?? state.trialId,
        experimentId: action.experimentId ?? state.experimentId,
      };
    case "CONTRACT":
      return { ...state, blackboard: { ...bb, contract: action.contract } };
    case "THREADS":
      return { ...state, blackboard: { ...bb, threads: action.threads } };
    case "POST": {
      const { tree, pendingReplies } = settleDraft(
        bb.draft,
        bb.pendingReplies,
        action.entry,
      );
      return {
        ...state,
        // The author has produced its turn → stop pulsing it.
        responding: state.responding.filter(
          (id) => id !== action.entry.author_id,
        ),
        blackboard: { ...bb, draft: tree, pendingReplies },
      };
    }
    case "CITE":
      return {
        ...state,
        blackboard: {
          ...bb,
          draft: updateEntry(bb.draft, action.entryId, (e) => {
            const citers = [
              ...(e.citers ?? []),
              { agentName: action.citerName, round: action.round },
            ];
            // Promotion counts DISTINCT citing agents (citations.round is part
            // of the DB's unique key, so the same agent citing the same entry
            // again in a later round is a real, separate row) — the displayed
            // count must match that, or the ring can show a ratio that looks
            // like it crossed the threshold while the real distinct-citer
            // count backing promotion never did.
            const distinctCiters = new Set(citers.map((c) => c.agentName)).size;
            return { ...e, citation_count: distinctCiters, citers };
          }),
        },
      };
    case "PROMOTE":
      return {
        ...state,
        blackboard: { ...bb, confirmed: [...bb.confirmed, action.confirmed] },
      };
    case "RECITE":
      // Citations keep accruing on a promoted entry's source draft — sync the
      // Confirmed card's count so it doesn't visibly disagree with the Draft
      // board's own citation ring for the same underlying entry.
      return {
        ...state,
        blackboard: {
          ...bb,
          confirmed: bb.confirmed.map((c) =>
            c.id === action.confirmed.id ? action.confirmed : c,
          ),
        },
      };
    case "DELETE":
      return {
        ...state,
        blackboard: {
          ...bb,
          draft: updateEntry(bb.draft, action.entryId, (e) => ({
            ...e,
            is_visible: false,
          })),
        },
      };
    case "CONTEST":
      return {
        ...state,
        blackboard: {
          ...bb,
          confirmed: bb.confirmed.map((e) =>
            e.id === action.entryId ? { ...e, status: action.status } : e,
          ),
        },
      };
    case "THINKING_RESET":
      // A fresh sub-round wave starts: nobody from the previous wave is pulsing.
      return { ...state, responding: [] };
    case "THINKING_ADD":
      return state.responding.includes(action.nodeId)
        ? state
        : { ...state, responding: [...state.responding, action.nodeId] };
    case "DONE":
      return {
        ...state,
        active: false,
        done: true,
        responding: [],
        // The convergence step carries the answer/ratification; the stream-end
        // DONE that follows omits them, so keep whatever was already set.
        finalAnswer: action.finalAnswer ?? state.finalAnswer,
        ratification: action.ratification ?? state.ratification,
        // Safety net: a pending reply's parent already exists in the DB (the
        // backend only ever sets reply_to to a resolved id), so it should
        // always show up somewhere in the same stream — but if the stream
        // ended first (client disconnect, server error) for some reason,
        // render it top-level rather than silently dropping it from view.
        blackboard:
          bb.pendingReplies.length > 0
            ? {
                ...bb,
                draft: [...bb.draft, ...bb.pendingReplies],
                pendingReplies: [],
              }
            : bb,
      };
    case "ERROR":
      return { ...state, error: action.error };
    case "RESET":
      return IDLE;
    default:
      return state;
  }
}

/**
 * Drives a real swarm run for the Market Hive view. It streams the run's events
 * over SSE and builds the blackboard directly from them (draft → confirmed),
 * exactly like the `test_mohamed` dummy pipeline — no REST re-fetch, no activity
 * log, no simulation mode.
 */
export function useSwarmRun(): {
  state: SwarmRunState;
  start: (prompt: string, parentRunId?: string, config?: SwarmRunConfig) => void;
  reset: () => void;
} {
  const [state, dispatch] = useReducer(reducer, undefined, loadPersisted);
  const seqRef = useRef(0);
  // The in-flight run's abort handle. Without this, starting a new run (or
  // resetting) only stopped this hook from *reading* the old stream — the
  // fetch itself, and the swarm run driving it server-side, kept running to
  // completion in the background, each still holding its own DB connection
  // for the run's full duration. Repeated restarts within a session could
  // stack up several of these zombie runs concurrently, starving the DB pool
  // for the run actually being watched.
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    saveSession(PERSIST_KEY, state);
  }, [state]);

  // Abort any in-flight stream on unmount (route navigation) too.
  useEffect(() => () => abortRef.current?.abort(), []);

  // BYOK keys are sent as X-LLM-* headers on the run request, mirroring the rest
  // of the API layer (lib/api.ts `request`). Without these, a deployment whose
  // server has no provider env vars (e.g. Railway) can't embed the contract or
  // drive agent turns — the auction aborts and no threads are ever worked.
  const { keys } = useApiKeys();

  const start = useCallback(
    (prompt: string, parentRunId?: string, config?: SwarmRunConfig) => {
      // Cancel any run still in flight — its SSE connection closing is what
      // lets the backend's own cleanup (task cancellation, connection
      // release) actually run, instead of leaving it to finish unattended.
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      const seq = seqRef.current + 1;
      seqRef.current = seq;
      dispatch({ type: "BEGIN" });

      void (async () => {
        try {
          const res = await fetch(`${API_BASE}/api/simulation/run`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...apiKeyHeaders(keys),
              ...userIdHeaders(),
            },
            body: JSON.stringify({
              engine: "swarm",
              prompt,
              // Multi-turn contract sessions: no UI consumes this yet (API +
              // mechanics only) — present so a future session picker can pass it.
              ...(parentRunId ? { parent_run_id: parentRunId } : {}),
              ...(config
                ? {
                    min_takers: config.takersMin,
                    max_takers: config.takersMax,
                    min_rounds: config.roundsMin,
                    max_rounds: config.roundsMax,
                    token_budget: config.tokenBudget,
                    max_amendments: config.maxAmendments,
                    decay_rounds: config.decayRounds,
                    invite_floor: config.inviteFloor,
                    demo_mode: config.reasoningEffort === "low",
                  }
                : {}),
            }),
            signal: controller.signal,
          });
          if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          // The backend emits all of a sub-round's "agent-thinking" frames in one
          // run before any output; the first one after any other frame opens a new
          // wave and clears the previous responders.
          let prevThinking = false;

          while (seqRef.current === seq) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            // SSE frames are separated by a blank line; each is "data: <json>".
            const frames = buffer.split("\n\n");
            buffer = frames.pop() ?? "";
            for (const frame of frames) {
              const dataLine = frame
                .split("\n")
                .find((l) => l.startsWith("data: "));
              if (!dataLine) continue;
              let step: SwarmStreamStep;
              try {
                step = JSON.parse(dataLine.slice(6)) as SwarmStreamStep;
              } catch {
                continue;
              }
              if (seqRef.current !== seq) break;
              if (step.type === "agent-thinking") {
                if (!prevThinking) dispatch({ type: "THINKING_RESET" });
                prevThinking = true;
                if (step.node_id)
                  dispatch({ type: "THINKING_ADD", nodeId: step.node_id });
                continue;
              }
              prevThinking = false;
              applyStep(dispatch, step);
            }
          }
        } catch (err) {
          if (seqRef.current === seq) {
            dispatch({
              type: "ERROR",
              error: err instanceof Error ? err.message : String(err),
            });
          }
        } finally {
          if (seqRef.current === seq) dispatch({ type: "DONE" });
        }
      })();
    },
    [keys],
  );

  const reset = useCallback(() => {
    abortRef.current?.abort();
    seqRef.current += 1;
    dispatch({ type: "RESET" });
  }, []);

  return { state, start, reset };
}

function applyStep(
  dispatch: React.Dispatch<Action>,
  step: SwarmStreamStep,
): void {
  const d = step.data ?? {};
  if (typeof d.run_id === "string") {
    dispatch({
      type: "RUN_ID",
      runId: d.run_id,
      trialId: typeof d.trial_id === "string" ? d.trial_id : undefined,
      experimentId:
        typeof d.experiment_id === "string" ? d.experiment_id : undefined,
    });
  }
  // Mirror useSimulation: remember the newest experiment so the statistics
  // page opens on this run.
  if (typeof d.experiment_id === "string" && d.experiment_id) {
    try {
      window.localStorage.setItem("latestExperimentId", d.experiment_id);
    } catch {
      // Storage unavailable — the stats page just won't preselect this run.
    }
  }
  // The Market Maker's drafted contract, emitted on the "Contract created"
  // frame (a slim object, no embedding/threads) so the board can show scoping.
  if (d.contract && typeof d.contract === "object") {
    dispatch({ type: "CONTRACT", contract: d.contract as ContractInfo });
  }
  if (Array.isArray(d.threads)) {
    dispatch({ type: "THREADS", threads: d.threads as ThreadInfo[] });
  }
  switch (step.type) {
    case "bb-post":
      if (d.id) dispatch({ type: "POST", entry: d as unknown as DraftEntry });
      break;
    case "bb-cite":
    case "bb-vote":
      if (typeof d.entry_id === "string") {
        dispatch({
          type: "CITE",
          entryId: d.entry_id,
          citerName: typeof d.citer_name === "string" ? d.citer_name : "",
          round: typeof d.round === "number" ? d.round : 0,
        });
      }
      break;
    case "bb-promote":
      if (d.id)
        dispatch({
          type: "PROMOTE",
          confirmed: d as unknown as ConfirmedEntry,
        });
      break;
    case "bb-recite":
      if (d.id)
        dispatch({
          type: "RECITE",
          confirmed: d as unknown as ConfirmedEntry,
        });
      break;
    case "bb-delete":
      if (typeof d.entry_id === "string") {
        dispatch({ type: "DELETE", entryId: d.entry_id });
      }
      break;
    case "bb-contest":
      if (typeof d.id === "string" && typeof d.status === "string") {
        dispatch({
          type: "CONTEST",
          entryId: d.id,
          status: d.status as ConfirmedEntry["status"],
        });
      }
      break;
    case "convergence":
      dispatch({
        type: "DONE",
        finalAnswer: typeof d.final_answer === "string" ? d.final_answer : null,
        ratification:
          d.ratification && typeof d.ratification === "object"
            ? (d.ratification as unknown as Ratification)
            : null,
      });
      break;
  }
}
