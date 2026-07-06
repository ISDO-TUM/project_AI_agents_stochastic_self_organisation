import { Position } from "@/lib/types";

// The canvas is a client-side view over the agent/file database: which nodes
// are on it (and where) lives here in localStorage, while the DB stays the
// full library. No stored state (first run) means "show everything".
//
// Known limitation: simulation runs are still executed by the backend against
// ALL agents in the DB, not just the ones on the canvas — see
// server/routes/simulation.py. Until the run endpoint accepts a participant
// list, agents removed from the canvas still take part in simulations.

export interface StoredCanvas {
  agentIds: string[];
  sourceIds: string[];
  positions: Record<string, Position>;
}

const KEY = "canvas-state-v1";

function isStringArray(x: unknown): x is string[] {
  return Array.isArray(x) && x.every((v) => typeof v === "string");
}

export function loadCanvasStore(): StoredCanvas | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredCanvas>;
    if (!isStringArray(parsed.agentIds) || !isStringArray(parsed.sourceIds))
      return null;
    return {
      agentIds: parsed.agentIds,
      sourceIds: parsed.sourceIds,
      positions:
        parsed.positions && typeof parsed.positions === "object"
          ? parsed.positions
          : {},
    };
  } catch {
    return null;
  }
}

export function saveCanvasStore(state: StoredCanvas) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Storage unavailable (private mode, quota) — canvas stays session-local.
  }
}
