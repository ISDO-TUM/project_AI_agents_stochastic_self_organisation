"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  Agent,
  ConsensusMode,
  Edge,
  HistoryMessage,
  SimStep,
  AnimatedParticle,
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

function historyMessageToStep(message: HistoryMessage): SimStep {
  const isSelf = message.fromAgentId === message.toAgentId;
  const isAgentToAgent = Boolean(message.fromAgentId) && !isSelf;
  const type: SimStep["type"] =
    message.messageType === "tool"
      ? "tool"
      : isAgentToAgent
        ? "agent-to-agent"
        : "system";
  return {
    id: String(message.id),
    ts: timeFromIso(message.createdAt),
    label: message.fromAgentName,
    msg: message.message || "",
    type,
    roundIndex: message.roundIndex,
    ...(isAgentToAgent && { target: message.toAgentName }),
    ...(message.fromAgentId && { fromId: message.fromAgentId }),
    ...(message.toAgentId && { toId: message.toAgentId }),
    ...(isSelf && message.toAgentId && { nodeId: message.toAgentId }),
  };
}

export function useSimulation(agents: Agent[], edges: Edge[]) {
  const [steps, setSteps] = useState<SimStep[]>([]);
  const [cur, setCur] = useState(0);
  const [simMode, setSim] = useState(false);
  const [logExp, setLogExp] = useState(false);
  const [activeNode, setActNode] = useState<string | null>(null);
  const [activeEdge, setActEdge] = useState<string | null>(null);
  const [activeEdgeReversed, setActEdgeReversed] = useState(false);
  const [particles, setParticles] = useState<AnimatedParticle[]>([]);
  const [outcome, setOutcome] = useState<SimulationResult | null>(null);
  const particleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const runSeqRef = useRef(0);

  useEffect(() => {
    return () => {
      if (particleTimerRef.current) clearTimeout(particleTimerRef.current);
    };
  }, []);

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
      const e = edges.find(
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
  }, [cur, simMode, steps, edges]);

  const runSim = useCallback(
    async (
      prompt: string,
      mode: ConsensusMode = "broadcast_no_consensus",
      ruleset?: string,
    ) => {
      if (agents.length === 0) return;

      setSim(true);
      setLogExp(false);
      setSteps([]);
      setCur(0);
      setOutcome(null);
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

      try {
        const result = await runSimulation(prompt, { mode, ruleset });
        setOutcome(result);
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
            const newSteps = messages.map(historyMessageToStep);
            setSteps((prev) => {
              const next = [...prev, ...newSteps];
              setCur(Math.max(0, next.length - 1));
              return next;
            });
          }
          const trial = await fetchHistoryTrial(result.trialId);
          setOutcome({ trialId: trial.id, status: trial.status });
          complete = trial.status === "completed" || trial.status === "failed";
          if (!complete) {
            await new Promise<void>((r) => setTimeout(r, 750));
          }
        }
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
      }
    },
    [agents, edges],
  );

  const stopSim = useCallback(() => {
    runSeqRef.current += 1;
    if (particleTimerRef.current) clearTimeout(particleTimerRef.current);
    setSim(false);
    setSteps([]);
    setCur(0);
    setActNode(null);
    setActEdge(null);
    setActEdgeReversed(false);
    setParticles([]);
    setOutcome(null);
  }, []);

  return {
    steps,
    cur,
    setCur,
    simMode,
    logExp,
    setLogExp,
    activeNode,
    activeEdge,
    activeEdgeReversed,
    particles,
    runSim,
    stopSim,
    outcome,
  };
}
