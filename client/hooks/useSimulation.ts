"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import {
  Agent,
  ConsensusMode,
  ConversationTurn,
  Edge,
  HistoryMessage,
  SimStep,
  AnimatedParticle,
  TopologyMode,
} from "@/lib/types";
import { uuid } from "@/lib/utils";
import {
  fetchHistoryMessages,
  fetchHistoryTrial,
  runSimulation,
  SimulationResult,
} from "@/lib/api";

function timeFromIso(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", { hour12: false });
}

// Coordinator / meta events carry no agent sender. Map their raw message_type to
// a readable label + a distinct icon so the activity log reads as something
// richer than a wall of identical "SYSTEM" lines.
const META_EVENTS: Record<string, { label: string; icon: string }> = {
  system_broadcast: { label: "Broadcast", icon: "Radio" },
  agent_output: { label: "", icon: "MessageSquare" }, // label filled from agent name
  agent_error: { label: "", icon: "TriangleAlert" },
  vote_tally: { label: "Vote tally", icon: "ListChecks" },
  voting_tally: { label: "Tally delivered", icon: "ListChecks" },
  trust_update: { label: "Trust update", icon: "Scale" },
  trust_evolution: { label: "Trust vector", icon: "Scale" },
  consensus: { label: "Consensus", icon: "CircleCheckBig" },
  convergence: { label: "Converged", icon: "CircleCheckBig" },
  topology_converged: { label: "Topology settled", icon: "Network" },
  // Bidding consensus
  system_blackboard: { label: "Gap board", icon: "ClipboardList" },
  bidding_bid: { label: "", icon: "Gavel" },
  bidding_rejection: { label: "", icon: "ShieldAlert" },
  bidding_yield: { label: "", icon: "Flag" },
  bidding_match: { label: "", icon: "Link2" },
  bidding_decision: { label: "", icon: "CheckCircle2" },
  bidding_convergence: { label: "Converged", icon: "CircleCheckBig" },
  bidding_collaborators: { label: "Bidding Board updated", icon: "Users" },
  bidding_final_output: { label: "Final answer", icon: "Sparkles" },
};

function historyMessageToStep(
  message: HistoryMessage,
  seedKeys?: Set<string>,
): SimStep {
  const isSelf = message.fromAgentId === message.toAgentId;
  const isAgentToAgent = Boolean(message.fromAgentId) && !isSelf;

  // A "phone-book" connection: an agent-to-agent edge that the user never drew —
  // it was discovered at runtime via the registry in dynamic topology.
  const dynamic =
    isAgentToAgent &&
    seedKeys != null &&
    Boolean(message.fromAgentId) &&
    Boolean(message.toAgentId) &&
    !seedKeys.has(`${message.fromAgentId}->${message.toAgentId}`) &&
    !seedKeys.has(`${message.toAgentId}->${message.fromAgentId}`);

  // A coordinator note delivered to one specific agent (e.g. an isolated agent's
  // tally in static mode). Highlight the recipient node so the delivery is visible.
  const isDirectedToAgent =
    !message.fromAgentId &&
    Boolean(message.toAgentId) &&
    message.messageType !== "system_broadcast";

  const meta = META_EVENTS[message.messageType];

  let type: SimStep["type"];
  let icon: string | undefined;
  let label = message.fromAgentName;
  if (message.messageType === "tool") {
    type = "tool";
  } else if (isAgentToAgent) {
    type = "agent-to-agent";
    if (dynamic) icon = "Phone";
  } else {
    type = "system";
    if (meta) {
      icon = meta.icon;
      if (meta.label) label = meta.label;
    }
  }

  return {
    id: String(message.id),
    ts: timeFromIso(message.createdAt),
    label,
    msg: message.message || "",
    type,
    messageType: message.messageType,
    roundIndex: message.roundIndex,
    ...(icon && { icon }),
    ...(dynamic && { dynamic: true }),
    ...((isAgentToAgent || isDirectedToAgent) && {
      target: message.toAgentName,
    }),
    ...(message.fromAgentId && { fromId: message.fromAgentId }),
    ...(message.toAgentId && { toId: message.toAgentId }),
    ...(isSelf && message.toAgentId && { nodeId: message.toAgentId }),
    ...(isDirectedToAgent &&
      message.toAgentId && { nodeId: message.toAgentId }),
  };
}

// ── Swarm (ECSAS) SSE stream ────────────────────────────────────────────────
// One Server-Sent Event from `POST /api/simulation/run` (engine="swarm").
type SwarmStreamStep = {
  type: string;
  msg: string;
  node_id?: string | null;
  thread_id?: string | null;
  entry_id?: string | null;
  data?: Record<string, unknown> | null;
};

// Step types after which the persisted blackboard has changed → re-fetch it.
const BOARD_CHANGING_STEPS = new Set<string>([
  "bb-post",
  "bb-cite",
  "bb-vote",
  "bb-promote",
  "bb-delete",
  "amendment-approved",
  "convergence",
]);

function swarmStepToSimStep(step: SwarmStreamStep): SimStep {
  // Swarm types aren't part of SimStepType, so they ride along in messageType
  // (the log themes off it); the base type stays "system".
  return {
    id: uuid(),
    ts: new Date().toLocaleTimeString("en-GB", { hour12: false }),
    label: "Swarm",
    msg: step.msg,
    type: "system",
    messageType: step.type,
    ...(step.node_id ? { nodeId: step.node_id } : {}),
  };
}

export interface SwarmRunHandlers {
  /** Called once, with the run_id from the first system step (drives polling). */
  onRunId?: (runId: string) => void;
  /** Called after each step that mutated the persisted blackboard. */
  onBoardChange?: () => void;
}

export function useSimulation(agents: Agent[], edges: Edge[]) {
  const [steps, setSteps] = useState<SimStep[]>([]);
  const [cur, setCur] = useState(0);
  // simMode = the log/run view is open. running = a run is in flight.
  // Splitting them keeps the input bar usable after a run completes,
  // which is what enables multi-turn follow-ups.
  const [simMode, setSim] = useState(false);
  const [running, setRunning] = useState(false);
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [logExp, setLogExp] = useState(false);
  const [activeNode, setActNode] = useState<string | null>(null);
  const [activeEdge, setActEdge] = useState<string | null>(null);
  const [activeEdgeReversed, setActEdgeReversed] = useState(false);
  const [particles, setParticles] = useState<AnimatedParticle[]>([]);
  const [outcome, setOutcome] = useState<SimulationResult | null>(null);
  const [batchProgress, setBatchProgress] = useState<{
    completed: number;
    total: number;
  } | null>(null);
  const particleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const runSeqRef = useRef(0);

  useEffect(() => {
    return () => {
      if (particleTimerRef.current) clearTimeout(particleTimerRef.current);
    };
  }, []);

  // Edges formed at runtime: agent-to-agent steps played back so far whose
  // (from,to) pair is NOT one of the static seed edges. Deduped by from->to.
  const dynamicEdges = useMemo((): Edge[] => {
    const seedKeys = new Set<string>();
    for (const e of edges) {
      seedKeys.add(`${e.from}->${e.to}`);
      seedKeys.add(`${e.to}->${e.from}`);
    }
    const seen = new Set<string>();
    const out: Edge[] = [];
    for (let i = 0; i <= cur && i < steps.length; i++) {
      const s = steps[i];
      if (s.type !== "agent-to-agent" || !s.fromId || !s.toId) continue;
      const key = `${s.fromId}->${s.toId}`;
      if (seedKeys.has(key) || seen.has(key)) continue;
      seen.add(key);
      out.push({ id: `dyn-${key}`, from: s.fromId, to: s.toId });
    }
    return out;
  }, [cur, steps, edges]);

  useEffect(() => {
    if (!simMode || !steps.length) return;
    const s = steps[cur];
    if (!s) return;
    if (s.nodeId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setActNode(s.nodeId);
      setActEdge(null);
      setActEdgeReversed(false);
    } else if (s.fromId && s.toId) {
      // Search static edges first; fall back to runtime-formed dynamic edges so
      // that phone-book connections also receive the directional pulse.
      const allEdges = [...edges, ...dynamicEdges];
      const e = allEdges.find(
        (e) =>
          (e.from === s.fromId && e.to === s.toId) ||
          (e.from === s.toId && e.to === s.fromId),
      );
      setActEdge(e ? e.id : null);
      setActEdgeReversed(e ? e.from === s.toId && e.to === s.fromId : false);
      setActNode(s.fromId ?? null);
    } else {
      setActNode(null);
      setActEdge(null);
      setActEdgeReversed(false);
    }
  }, [cur, simMode, steps, edges, dynamicEdges]);

  const runSim = useCallback(
    async (
      prompt: string,
      mode: ConsensusMode = "broadcast_no_consensus",
      ruleset?: string,
      topology: TopologyMode = "static",
      fanout: number = 3,
      iterations: number = 1,
    ) => {
      if (agents.length === 0) return;

      setSim(true);
      setRunning(true);
      setLogExp(false);
      setSteps([]);
      setCur(0);
      setOutcome(null);
      setBatchProgress(null);
      const runSeq = runSeqRef.current + 1;
      runSeqRef.current = runSeq;

      // Animate particles along all edges during the run
      const pts: AnimatedParticle[] = edges.map((e, i) => ({
        id: uuid(),
        from: e.from,
        to: e.to,
        dur: 0.55 + Math.random() * 0.3,
        delay: i * 0.09,
      }));
      setParticles(pts);
      if (particleTimerRef.current) clearTimeout(particleTimerRef.current);
      particleTimerRef.current = setTimeout(() => setParticles([]), 3500);

      // Keys of the user-drawn seed graph (both directions) — used to flag
      // phone-book connections formed at runtime in the activity log.
      const seedKeys = new Set<string>();
      for (const e of edges) {
        seedKeys.add(`${e.from}->${e.to}`);
        seedKeys.add(`${e.to}->${e.from}`);
      }

      try {
        const result = await runSimulation(prompt, {
          mode,
          ruleset,
          topology,
          fanout,
          iterations,
        });
        window.localStorage.setItem("latestExperimentId", result.experimentId);
        setOutcome(result);
        const isBatch = result.trialIds.length > 1;
        if (isBatch)
          setBatchProgress({ completed: 0, total: result.trialIds.length });
        let lastMessageId = 0;
        let complete = false;
        while (!complete && runSeqRef.current === runSeq) {
          const messages = await fetchHistoryMessages({
            trialId: result.trialId,
            afterId: lastMessageId,
          });
          if (messages.length) {
            lastMessageId = Math.max(
              ...messages.map((m) => m.id),
              lastMessageId,
            );
            const newSteps = messages.map((m) =>
              historyMessageToStep(m, seedKeys),
            );
            setSteps((prev) => {
              const next = [...prev, ...newSteps];
              setCur(Math.max(0, next.length - 1));
              return next;
            });
          }
          if (isBatch) {
            const allTrials = await Promise.all(
              result.trialIds.map((tid) => fetchHistoryTrial(tid)),
            );
            const doneCount = allTrials.filter(
              (t) => t.status === "completed" || t.status === "failed",
            ).length;
            setBatchProgress({
              completed: doneCount,
              total: result.trialIds.length,
            });
            setOutcome({
              experimentId: result.experimentId,
              trialId: result.trialId,
              trialIds: result.trialIds,
              status: allTrials[0].status,
            });
            complete = doneCount === result.trialIds.length;
          } else {
            const trial = await fetchHistoryTrial(result.trialId);
            setOutcome({
              experimentId: result.experimentId,
              trialId: trial.id,
              trialIds: result.trialIds,
              status: trial.status,
            });
            complete =
              trial.status === "completed" || trial.status === "failed";
          }
          if (!complete) {
            await new Promise<void>((r) => setTimeout(r, 750));
          }
        }
        if (isBatch) setBatchProgress(null);
        setTurns((prev) => [
          ...prev,
          { prompt, mode, answer: result.consensus ?? null },
        ]);
      } catch (err) {
        setSteps([
          {
            id: uuid(),
            ts: new Date().toLocaleTimeString("en-GB", { hour12: false }),
            label: "SYSTEM",
            msg: `Simulation failed: ${
              err instanceof Error ? err.message : String(err)
            }`,
            type: "system",
          },
        ]);
        setCur(0);
      } finally {
        setRunning(false);
      }
    },
    [agents, edges],
  );

  // Swarm (ECSAS) run: stream SimulationStep events over SSE and feed the
  // activity log. The blackboard board itself is re-fetched via onBoardChange
  // (GET /blackboard is authoritative); SSE drives the log + run lifecycle.
  const runSwarm = useCallback(
    async (prompt: string, handlers?: SwarmRunHandlers) => {
      if (agents.length === 0) return;

      setSim(true);
      setRunning(true);
      setLogExp(false);
      setSteps([]);
      setCur(0);
      setOutcome(null);
      setBatchProgress(null);
      const runSeq = runSeqRef.current + 1;
      runSeqRef.current = runSeq;

      try {
        const res = await fetch("/api/simulation/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ engine: "swarm", prompt }),
        });
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let runIdAnnounced = false;

        while (runSeqRef.current === runSeq) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // SSE frames are separated by a blank line; each frame is "data: <json>".
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

            if (
              !runIdAnnounced &&
              step.data &&
              typeof step.data.run_id === "string"
            ) {
              runIdAnnounced = true;
              handlers?.onRunId?.(step.data.run_id);
            }

            setSteps((prev) => {
              const next = [...prev, swarmStepToSimStep(step)];
              setCur(Math.max(0, next.length - 1));
              return next;
            });

            if (BOARD_CHANGING_STEPS.has(step.type))
              handlers?.onBoardChange?.();
          }
        }
      } catch (err) {
        setSteps((prev) => [
          ...prev,
          {
            id: uuid(),
            ts: new Date().toLocaleTimeString("en-GB", { hour12: false }),
            label: "SYSTEM",
            msg: `Swarm run failed: ${
              err instanceof Error ? err.message : String(err)
            }`,
            type: "system",
          },
        ]);
      } finally {
        if (runSeqRef.current === runSeq) setRunning(false);
      }
    },
    [agents],
  );

  const stopSim = useCallback(() => {
    runSeqRef.current += 1;
    if (particleTimerRef.current) clearTimeout(particleTimerRef.current);
    setSim(false);
    setRunning(false);
    setSteps([]);
    setCur(0);
    setActNode(null);
    setActEdge(null);
    setActEdgeReversed(false);
    setParticles([]);
    setOutcome(null);
    setBatchProgress(null);
  }, []);

  // Reset the conversation — drop accumulated turns and exit the run view
  // so the next prompt starts from a clean slate.
  const resetContext = useCallback(() => {
    setTurns([]);
    stopSim();
  }, [stopSim]);

  return {
    steps,
    cur,
    setCur,
    simMode,
    running,
    turns,
    logExp,
    setLogExp,
    activeNode,
    activeEdge,
    activeEdgeReversed,
    particles,
    runSim,
    runSwarm,
    stopSim,
    resetContext,
    outcome,
    batchProgress,
    dynamicEdges,
  };
}
