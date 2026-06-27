"use client";

import { useCallback, useReducer, useRef } from "react";
import { BlackboardState, ConfirmedEntry, DraftEntry } from "@/lib/types";
import { DummyAgentInfo, DummyEvent, DummyRunFixture } from "@/lib/dummy-swarm";

const EMPTY_STATE: BlackboardState = {
  threads: [],
  confirmed: [],
  draft: [],
  loading: false,
  error: null,
};

export interface DummySwarmState {
  active: boolean;
  done: boolean;
  blackboard: BlackboardState;
  agents: DummyAgentInfo[];
  trustVectors: DummyRunFixture["trustVectors"];
}

type Action =
  | { type: "BEGIN"; fixture: DummyRunFixture }
  | { type: "POST"; entry: DraftEntry }
  | { type: "CITE"; entryId: string; citerName: string; round: number }
  | { type: "PROMOTE"; confirmed: ConfirmedEntry }
  | { type: "DELETE"; entryId: string }
  | { type: "DONE" }
  | { type: "RESET" };

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

const INITIAL: DummySwarmState = {
  active: false,
  done: false,
  blackboard: EMPTY_STATE,
  agents: [],
  trustVectors: {},
};

function reducer(state: DummySwarmState, action: Action): DummySwarmState {
  switch (action.type) {
    case "BEGIN":
      return {
        active: true,
        done: false,
        agents: action.fixture.agents,
        trustVectors: action.fixture.trustVectors,
        blackboard: {
          threads: action.fixture.threads,
          confirmed: [],
          draft: [],
          loading: false,
          error: null,
        },
      };
    case "POST":
      return {
        ...state,
        blackboard: {
          ...state.blackboard,
          draft: insertEntry(state.blackboard.draft, action.entry),
        },
      };
    case "CITE":
      return {
        ...state,
        blackboard: {
          ...state.blackboard,
          draft: updateEntry(state.blackboard.draft, action.entryId, (e) => ({
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
        blackboard: {
          ...state.blackboard,
          confirmed: [...state.blackboard.confirmed, action.confirmed],
        },
      };
    case "DELETE":
      return {
        ...state,
        blackboard: {
          ...state.blackboard,
          draft: updateEntry(state.blackboard.draft, action.entryId, (e) => ({
            ...e,
            is_visible: false,
          })),
        },
      };
    case "DONE":
      return { ...state, done: true };
    case "RESET":
      return INITIAL;
    default:
      return state;
  }
}

export function useDummySwarm(): {
  state: DummySwarmState;
  start: (fixture: DummyRunFixture) => void;
  reset: () => void;
} {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const clearTimers = useCallback(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  }, []);

  const start = useCallback(
    (fixture: DummyRunFixture) => {
      clearTimers();
      dispatch({ type: "BEGIN", fixture });
      const lastDelay =
        fixture.events.length > 0
          ? Math.max(...fixture.events.map((e) => e.delay))
          : 0;
      fixture.events.forEach((event: DummyEvent) => {
        const timer = setTimeout(() => {
          if (event.kind === "post")
            dispatch({ type: "POST", entry: event.entry });
          if (event.kind === "cite")
            dispatch({
              type: "CITE",
              entryId: event.entryId,
              citerName: event.citerName,
              round: event.round,
            });
          if (event.kind === "promote")
            dispatch({ type: "PROMOTE", confirmed: event.confirmed });
          if (event.kind === "delete")
            dispatch({ type: "DELETE", entryId: event.entryId });
        }, event.delay);
        timers.current.push(timer);
      });
      // Signal completion 800 ms after the last event fires
      const doneTimer = setTimeout(
        () => dispatch({ type: "DONE" }),
        lastDelay + 800,
      );
      timers.current.push(doneTimer);
    },
    [clearTimers],
  );

  const reset = useCallback(() => {
    clearTimers();
    dispatch({ type: "RESET" });
  }, [clearTimers]);

  return { state, start, reset };
}
