"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Agent, Source, Edge, SimStep, AnimatedParticle } from "@/lib/types";
import { uuid, timestamp } from "@/lib/utils";
import { runAgent } from "@/lib/api";

export function useSimulation(
  agents: Agent[],
  _sources: Source[],
  edges: Edge[],
) {
  const [steps, setSteps] = useState<SimStep[]>([]);
  const [cur, setCur] = useState(0);
  const [simMode, setSim] = useState(false);
  const [logExp, setLogExp] = useState(false);
  const [activeNode, setActNode] = useState<string | null>(null);
  const [activeEdge, setActEdge] = useState<string | null>(null);
  const [particles, setParticles] = useState<AnimatedParticle[]>([]);
  const particleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (particleTimerRef.current) clearTimeout(particleTimerRef.current);
    };
  }, []);

  // Highlight the active node/edge whenever the current step changes.
  useEffect(() => {
    if (!simMode || !steps.length) return;
    const s = steps[cur];
    if (!s) return;
    if (s.nodeId) {
      setActNode(s.nodeId);
      setActEdge(null);
    } else if (s.fromId && s.toId) {
      const e = edges.find(
        (e) =>
          (e.from === s.fromId && e.to === s.toId) ||
          (e.from === s.toId && e.to === s.fromId),
      );
      setActEdge(e ? e.id : null);
      setActNode(s.fromId ?? null);
    } else {
      setActNode(null);
      setActEdge(null);
    }
  }, [cur, simMode, steps, edges]);

  const runSim = useCallback(
    async (prompt: string) => {
      if (agents.length === 0) return;

      // Open the log wall immediately with a status step.
      setSteps([
        {
          id: uuid(),
          ts: timestamp(),
          label: "SYSTEM",
          msg: `Sending to ${agents.length} agent${
            agents.length !== 1 ? "s" : ""
          }…`,
          type: "system",
        },
      ]);
      setCur(0);
      setSim(true);
      setLogExp(false);

      // Animate particles on all edges.
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

      // Run all agents in parallel; append a step as each one completes.
      await Promise.allSettled(
        agents.map(async (agent) => {
          let step: SimStep;
          try {
            const { response } = await runAgent(agent.id, prompt);
            step = {
              id: uuid(),
              ts: timestamp(),
              label: agent.name,
              msg: response,
              type: "system",
              nodeId: agent.id,
            };
          } catch (err) {
            step = {
              id: uuid(),
              ts: timestamp(),
              label: agent.name,
              msg: `Error: ${
                err instanceof Error ? err.message : "run failed"
              }`,
              type: "system",
              nodeId: agent.id,
            };
          }
          setSteps((prev) => [...prev, step]);
          setCur((c) => c + 1);
        }),
      );
    },
    [agents, edges],
  );

  const stopSim = useCallback(() => {
    if (particleTimerRef.current) clearTimeout(particleTimerRef.current);
    setSim(false);
    setSteps([]);
    setCur(0);
    setActNode(null);
    setActEdge(null);
    setParticles([]);
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
    particles,
    runSim,
    stopSim,
  };
}
