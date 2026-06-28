"use client";

import { useCallback, useReducer, useRef } from "react";
import {
  BlackboardState,
  ConfirmedEntry,
  DraftEntry,
  ThreadInfo,
} from "@/lib/types";

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
  error: string | null;
}

const IDLE: SwarmRunState = {
  active: false,
  done: false,
  runId: null,
  blackboard: EMPTY_BOARD,
  error: null,
};

type Action =
  | { type: "BEGIN" }
  | { type: "RUN_ID"; runId: string }
  | { type: "THREADS"; threads: ThreadInfo[] }
  | { type: "POST"; entry: DraftEntry }
  | { type: "CITE"; entryId: string; citerName: string; round: number }
  | { type: "PROMOTE"; confirmed: ConfirmedEntry }
  | { type: "DELETE"; entryId: string }
  | { type: "DONE" }
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
    case "DONE":
      return { ...state, active: false, done: true };
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
  start: (prompt: string) => void;
  reset: () => void;
} {
  const [state, dispatch] = useReducer(reducer, IDLE);
  const seqRef = useRef(0);

  const start = useCallback((prompt: string) => {
    const seq = seqRef.current + 1;
    seqRef.current = seq;
    dispatch({ type: "BEGIN" });

    void (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/simulation/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ engine: "swarm", prompt }),
        });
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

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
  }, []);

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
    case "convergence":
      dispatch({ type: "DONE" });
      break;
  }
}
