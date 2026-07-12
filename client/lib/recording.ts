import { Agent, Source, Edge } from "@/lib/types";
import type { SwarmRunConfig } from "@/components/swarm-config";

/**
 * A recorded swarm run: the verbatim SSE step stream plus the canvas setup it
 * ran against. Replaying `steps` through the same reducer that drives a live run
 * (see `useSwarmRun`'s `applyStep`) reproduces the board — and every popup —
 * exactly, offline and deterministically. This is what the standalone
 * single-file player embeds and plays back.
 */
export const RECORDING_VERSION = 1 as const;

// One Server-Sent Event frame from `POST /api/simulation/run` (engine="swarm").
// Shared with `useSwarmRun` so the capture and replay paths agree on the shape.
export interface SwarmStreamStep {
  type: string;
  msg: string;
  node_id?: string | null;
  thread_id?: string | null;
  entry_id?: string | null;
  data?: Record<string, unknown> | null;
}

// A captured frame plus its offset (ms) from the run's first frame, so replay
// can honour the original pacing.
export interface RecordedStep {
  t: number;
  step: SwarmStreamStep;
}

export interface SwarmRecording {
  version: typeof RECORDING_VERSION;
  meta: { name: string; prompt: string; createdAt: string };
  config: SwarmRunConfig;
  canvas: { agents: Agent[]; sources: Source[]; edges: Edge[] };
  steps: RecordedStep[];
  finalAnswer?: string | null;
}

/** Assemble a downloadable recording from a completed run's captured stream. */
export function buildRecording(args: {
  name: string;
  prompt: string;
  config: SwarmRunConfig;
  canvas: { agents: Agent[]; sources: Source[]; edges: Edge[] };
  steps: RecordedStep[];
  finalAnswer?: string | null;
}): SwarmRecording {
  return {
    version: RECORDING_VERSION,
    meta: {
      name: args.name,
      prompt: args.prompt,
      createdAt: new Date().toISOString(),
    },
    config: args.config,
    canvas: {
      agents: args.canvas.agents,
      sources: args.canvas.sources,
      edges: args.canvas.edges,
    },
    steps: args.steps,
    finalAnswer: args.finalAnswer ?? null,
  };
}

/** A filesystem-safe slug for a recording's download filename. */
export function slugifyName(name: string): string {
  return (
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40) || "swarm-run"
  );
}

/**
 * Inject a recording into the pre-built standalone player template as
 * `window.__RECORDING__`, producing a finished self-contained HTML document.
 * This is the browser-side equivalent of the Vite `injectRecording` plugin, so
 * the toolbar can turn a run into a shareable `.html` with no build step. `<` is
 * escaped so a value containing "</script>" can't break out of the tag.
 */
export const RECORDING_SLOT = "<!--RECORDING-SLOT-->";

export type PlayerMode = "replay" | "snapshot";

export function injectRecordingIntoTemplate(
  template: string,
  rec: SwarmRecording,
  mode: PlayerMode = "replay",
): string {
  const safe = JSON.stringify(rec).replace(/</g, "\\u003c");
  const tag = `<script>window.__RECORDING__ = ${safe};window.__PLAYER_MODE__ = ${JSON.stringify(
    mode,
  )};</script>`;
  // Replace the placeholder (see standalone/index.html). Never key off "</head>":
  // the inlined app bundle contains that string, so a naive replace could land
  // inside the JS and corrupt it. Fall back to prepending if the slot is absent.
  return template.includes(RECORDING_SLOT)
    ? template.replace(RECORDING_SLOT, tag)
    : tag + template;
}

/** Narrowly validate a parsed object is a usable recording before replaying it. */
export function isSwarmRecording(v: unknown): v is SwarmRecording {
  if (typeof v !== "object" || v === null) return false;
  const r = v as Record<string, unknown>;
  return (
    r.version === RECORDING_VERSION &&
    Array.isArray(r.steps) &&
    typeof r.canvas === "object" &&
    r.canvas !== null &&
    Array.isArray((r.canvas as Record<string, unknown>).agents)
  );
}
