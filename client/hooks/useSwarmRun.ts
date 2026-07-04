"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import {
  BlackboardState,
  ConfirmedEntry,
  DraftEntry,
  Ratification,
  ThreadInfo,
} from "@/lib/types";
import { useApiKeys, apiKeyHeaders } from "@/lib/api-keys-context";
import { loadSession, saveSession } from "@/lib/session-persist";

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
  loading: false,
  error: null,
};

export interface SwarmRunState {
  active: boolean;
  done: boolean;
  runId: string | null;
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
const PERSIST_KEY = "swarm.board.v1";

function loadPersisted(): SwarmRunState {
  const persisted = loadSession<SwarmRunState>(PERSIST_KEY);
  if (!persisted) return IDLE;
  return { ...persisted, active: false, responding: [] };
}

type Action =
  | { type: "BEGIN" }
  | { type: "RUN_ID"; runId: string }
  | { type: "THREADS"; threads: ThreadInfo[] }
  | { type: "POST"; entry: DraftEntry }
  | { type: "CITE"; entryId: string; citerName: string; round: number }
  | { type: "PROMOTE"; confirmed: ConfirmedEntry }
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

function insertEntry(tree: DraftEntry[], entry: DraftEntry): DraftEntry[] {
  if (!entry.reply_to) return [...tree, entry];
  const [next, placed] = insertEntryRec(tree, entry);
  return placed ? next : [...tree, entry];
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
      return { ...state, runId: action.runId };
    case "THREADS":
      return { ...state, blackboard: { ...bb, threads: action.threads } };
    case "POST":
      return {
        ...state,
        // The author has produced its turn → stop pulsing it.
        responding: state.responding.filter(
          (id) => id !== action.entry.author_id,
        ),
        blackboard: { ...bb, draft: insertEntry(bb.draft, action.entry) },
      };
    case "CITE":
      return {
        ...state,
        blackboard: {
          ...bb,
          draft: updateEntry(bb.draft, action.entryId, (e) => ({
            ...e,
            citation_count: e.citation_count + 1,
            citers: [
              ...(e.citers ?? []),
              { agentName: action.citerName, round: action.round },
            ],
          })),
        },
      };
    case "PROMOTE":
      return {
        ...state,
        blackboard: { ...bb, confirmed: [...bb.confirmed, action.confirmed] },
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
  start: (prompt: string, parentRunId?: string) => void;
  reset: () => void;
} {
  const [state, dispatch] = useReducer(reducer, undefined, loadPersisted);
  const seqRef = useRef(0);

  useEffect(() => {
    saveSession(PERSIST_KEY, state);
  }, [state]);

  // BYOK keys are sent as X-LLM-* headers on the run request, mirroring the rest
  // of the API layer (lib/api.ts `request`). Without these, a deployment whose
  // server has no provider env vars (e.g. Railway) can't embed the contract or
  // drive agent turns — the auction aborts and no threads are ever worked.
  const { keys } = useApiKeys();

  const start = useCallback(
    (prompt: string, parentRunId?: string) => {
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
            },
            body: JSON.stringify({
              engine: "swarm",
              prompt,
              // Multi-turn contract sessions: no UI consumes this yet (API +
              // mechanics only) — present so a future session picker can pass it.
              ...(parentRunId ? { parent_run_id: parentRunId } : {}),
            }),
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
  if (typeof d.run_id === "string")
    dispatch({ type: "RUN_ID", runId: d.run_id });
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
