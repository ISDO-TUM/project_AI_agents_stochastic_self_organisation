import { Agent, Source, SimStep } from "./types";
import { uuid, timestamp } from "./utils";
import { TrialDetail } from "./api";

/**
 * Build SimSteps from a backend trial. Each round produces one SYSTEM step
 * (round header), one TOOL step per agent proposal, and one SYSTEM step
 * with the round's aggregate answer + agreement %.
 */
export function buildStepsFromTrial(
  trial: TrialDetail,
  canvasAgents: Agent[],
  backendIdByCanvasId: Record<string, string>,
): SimStep[] {
  const canvasIdByBackendId: Record<string, string> = {};
  for (const [canvasId, backendId] of Object.entries(backendIdByCanvasId)) {
    canvasIdByBackendId[backendId] = canvasId;
  }
  const nameByBackendId: Record<string, string> = {};
  for (const a of canvasAgents) {
    const backendId = backendIdByCanvasId[a.id];
    if (backendId) nameByBackendId[backendId] = a.name || "Agent";
  }

  const steps: SimStep[] = [];
  const ts = () => timestamp();

  steps.push({
    id: uuid(),
    ts: ts(),
    label: "SYSTEM",
    msg: `Trial started — ${trial.protocol_name}: "${trial.task_prompt}"`,
    type: "system",
  });

  for (const round of trial.rounds) {
    steps.push({
      id: uuid(),
      ts: ts(),
      label: "SYSTEM",
      msg: `Round ${round.round_index + 1} — collecting proposals from ${
        round.proposals.length
      } agents`,
      type: "system",
    });

    for (const p of round.proposals) {
      const canvasId = canvasIdByBackendId[p.agent_id];
      const name = nameByBackendId[p.agent_id] ?? p.agent_id.slice(0, 8);
      steps.push({
        id: uuid(),
        ts: ts(),
        label: name,
        msg: p.content,
        type: "tool",
        nodeId: canvasId,
      });
    }

    const pct = Math.round(round.agreement * 100);
    steps.push({
      id: uuid(),
      ts: ts(),
      label: "SYSTEM",
      msg: `Round ${round.round_index + 1} aggregate (${pct}% agreement): ${
        round.aggregate
      }`,
      type: "system",
    });
  }

  steps.push({
    id: uuid(),
    ts: ts(),
    label: "SYSTEM",
    msg: `Consensus reached (${trial.stopped_reason}) — final answer: ${trial.final_answer}`,
    type: "system",
  });

  return steps;
}

/** Used when the user clicks Run with no agents on the canvas. */
export function emptyCanvasSteps(
  _agents: Agent[],
  _sources: Source[],
): SimStep[] {
  return [
    {
      id: uuid(),
      ts: timestamp(),
      label: "SYSTEM",
      msg: "Add at least one agent to the canvas, then click Run again.",
      type: "system",
    },
  ];
}
