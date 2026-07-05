"use client";

import { useCallback, useEffect, useReducer } from "react";
import {
  BlackboardState,
  ConfirmedEntry,
  DraftEntry,
  SimStep,
  SwarmSimStepType,
  ThreadInfo,
} from "@/lib/types";

const EMPTY_STATE: BlackboardState = {
  threads: [],
  confirmed: [],
  draft: [],
  pendingReplies: [],
  loading: false,
  error: null,
};

// Wider event type that includes all ECSAS step types
type SwarmSimStep = Omit<SimStep, "type"> & { type: SwarmSimStepType };

type Action =
  | { type: "RESET" }
  | { type: "FETCH_START" }
  | { type: "FETCH_SUCCESS"; data: Omit<BlackboardState, "loading" | "error"> }
  | { type: "FETCH_ERROR"; error: string }
  | { type: "DISPATCH_STEP"; event: SwarmSimStep };

function findInTree(entries: DraftEntry[], id: string): boolean {
  return entries.some((e) => e.id === id || findInTree(e.children, id));
}

function applyBbPost(draft: DraftEntry[], event: SwarmSimStep): DraftEntry[] {
  let newEntry: DraftEntry | null = null;
  try {
    newEntry = JSON.parse(event.msg) as DraftEntry;
  } catch {
    return draft;
  }
  if (newEntry.reply_to && findInTree(draft, newEntry.reply_to)) {
    return draft.map((root) => nestEntry(root, newEntry!));
  }
  return [newEntry, ...draft];
}

function nestEntry(root: DraftEntry, newEntry: DraftEntry): DraftEntry {
  if (root.id === newEntry.reply_to) {
    return { ...root, children: [...root.children, newEntry] };
  }
  return {
    ...root,
    children: root.children.map((c) => nestEntry(c, newEntry)),
  };
}

function applyBbPromote(
  draft: DraftEntry[],
  confirmed: ConfirmedEntry[],
  event: SwarmSimStep,
): { draft: DraftEntry[]; confirmed: ConfirmedEntry[] } {
  let promoted: ConfirmedEntry | null = null;
  try {
    promoted = JSON.parse(event.msg) as ConfirmedEntry;
  } catch {
    return { draft, confirmed };
  }
  return {
    draft,
    confirmed: [...confirmed, promoted],
  };
}

function applyBbDelete(draft: DraftEntry[], event: SwarmSimStep): DraftEntry[] {
  const entryId: string = event.nodeId ?? "";
  if (!entryId) return draft;
  return markInvisible(draft, entryId);
}

function markInvisible(entries: DraftEntry[], id: string): DraftEntry[] {
  return entries.map((e) => {
    if (e.id === id) return { ...e, is_visible: false };
    return { ...e, children: markInvisible(e.children, id) };
  });
}

function applyBbCiteOrVote(
  draft: DraftEntry[],
  event: SwarmSimStep,
): DraftEntry[] {
  const entryId: string = event.nodeId ?? "";
  if (!entryId) return draft;
  return incrementCitation(draft, entryId);
}

function incrementCitation(entries: DraftEntry[], id: string): DraftEntry[] {
  return entries.map((e) => {
    if (e.id === id) return { ...e, citation_count: e.citation_count + 1 };
    return { ...e, children: incrementCitation(e.children, id) };
  });
}

function reducer(state: BlackboardState, action: Action): BlackboardState {
  switch (action.type) {
    case "RESET":
      return EMPTY_STATE;
    case "FETCH_START":
      return { ...state, loading: true, error: null };
    case "FETCH_SUCCESS":
      return {
        threads: action.data.threads,
        confirmed: action.data.confirmed,
        draft: action.data.draft,
        pendingReplies: [],
        loading: false,
        error: null,
      };
    case "FETCH_ERROR":
      return { ...state, loading: false, error: action.error };
    case "DISPATCH_STEP": {
      const event = action.event;
      switch (event.type as string) {
        case "bb-post":
          return { ...state, draft: applyBbPost(state.draft, event) };
        case "bb-promote": {
          const result = applyBbPromote(state.draft, state.confirmed, event);
          return { ...state, ...result };
        }
        case "bb-delete":
          return { ...state, draft: applyBbDelete(state.draft, event) };
        case "bb-cite":
        case "bb-vote":
          return { ...state, draft: applyBbCiteOrVote(state.draft, event) };
        default:
          return state;
      }
    }
    default:
      return state;
  }
}

export function useBlackboard(
  runId: string | null,
  // Bump this to force a re-fetch while the run is live (e.g. on each SSE step
  // that changed the board). GET /blackboard is the authoritative view.
  refreshKey: number = 0,
): {
  state: BlackboardState;
  dispatch: (event: SwarmSimStep) => void;
} {
  const [state, dispatchReducer] = useReducer(reducer, EMPTY_STATE);

  useEffect(() => {
    if (!runId) {
      dispatchReducer({ type: "RESET" });
      return;
    }

    dispatchReducer({ type: "FETCH_START" });

    let cancelled = false;
    fetch(`/api/simulation/${runId}/blackboard`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<{
          threads: ThreadInfo[];
          confirmed: ConfirmedEntry[];
          draft: DraftEntry[];
        }>;
      })
      .then((data) => {
        if (!cancelled) {
          dispatchReducer({
            type: "FETCH_SUCCESS",
            data: {
              threads: data.threads,
              confirmed: data.confirmed,
              draft: data.draft,
              pendingReplies: [],
            },
          });
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          dispatchReducer({ type: "FETCH_ERROR", error: err.message });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [runId, refreshKey]);

  const dispatch = useCallback((event: SwarmSimStep) => {
    dispatchReducer({ type: "DISPATCH_STEP", event });
  }, []);

  return { state, dispatch };
}
