"use client";

import { useCallback, useEffect, useState } from "react";
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
  loading: false,
  error: null,
};

// Wider event type that includes all ECSAS step types
type SwarmSimStep = Omit<SimStep, "type"> & { type: SwarmSimStepType };

function applyBbPost(draft: DraftEntry[], event: SwarmSimStep): DraftEntry[] {
  let newEntry: DraftEntry | null = null;
  try {
    newEntry = JSON.parse(event.msg) as DraftEntry;
  } catch {
    return draft;
  }
  if (newEntry.reply_to) {
    return draft.map((root) => nestEntry(root, newEntry!));
  }
  return [newEntry, ...draft];
}

function nestEntry(root: DraftEntry, newEntry: DraftEntry): DraftEntry {
  if (root.id === newEntry.reply_to) {
    return { ...root, children: [...root.children, newEntry] };
  }
  return { ...root, children: root.children.map((c) => nestEntry(c, newEntry)) };
}

function applyBbPromote(
  draft: DraftEntry[],
  confirmed: ConfirmedEntry[],
  event: SwarmSimStep
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

function applyBbCiteOrVote(draft: DraftEntry[], event: SwarmSimStep): DraftEntry[] {
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

export function useBlackboard(runId: string | null): {
  state: BlackboardState;
  dispatch: (event: SwarmSimStep) => void;
} {
  const [state, setState] = useState<BlackboardState>(EMPTY_STATE);

  useEffect(() => {
    if (!runId) {
      setState(EMPTY_STATE);
      return;
    }

    setState((s) => ({ ...s, loading: true, error: null }));

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
        setState({
          threads: data.threads,
          confirmed: data.confirmed,
          draft: data.draft,
          loading: false,
          error: null,
        });
      })
      .catch((err: Error) => {
        setState((s) => ({ ...s, loading: false, error: err.message }));
      });
  }, [runId]);

  const dispatch = useCallback((event: SwarmSimStep) => {
    setState((prev) => {
      switch (event.type as string) {
        case "bb-post":
          return { ...prev, draft: applyBbPost(prev.draft, event) };
        case "bb-promote": {
          const result = applyBbPromote(prev.draft, prev.confirmed, event);
          return { ...prev, ...result };
        }
        case "bb-delete":
          return { ...prev, draft: applyBbDelete(prev.draft, event) };
        case "bb-cite":
        case "bb-vote":
          return { ...prev, draft: applyBbCiteOrVote(prev.draft, event) };
        default:
          return prev;
      }
    });
  }, []);

  return { state, dispatch };
}
