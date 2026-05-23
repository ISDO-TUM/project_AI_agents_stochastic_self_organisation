"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  Agent,
  ConsensusMode,
  Edge,
  SimStep,
  AnimatedParticle,
} from "@/lib/types";
import { uuid } from "@/lib/utils";
import { runSimulation, SimulationResult } from "@/lib/api";

export function useSimulation(agents: Agent[], edges: Edge[]) {
  const [steps, setSteps] = useState<SimStep[]>([]);
  const [cur, setCur] = useState(0);
  const [simMode, setSim] = useState(false);
  const [logExp, setLogExp] = useState(false);
  const [activeNode, setActNode] = useState<string | null>(null);
  const [activeEdge, setActEdge] = useState<string | null>(null);
  const [particles, setParticles] = useState<AnimatedParticle[]>([]);
  const [outcome, setOutcome] = useState<Omit<
    SimulationResult,
    "steps"
  > | null>(null);
  const particleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
    async (
      prompt: string,
      mode: ConsensusMode = "broadcast",
      ruleset?: string,
    ) => {
      if (agents.length === 0) return;

      setSim(true);
      setLogExp(false);
      setSteps([]);
      setCur(0);
      setOutcome(null);

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
        const { steps: simSteps, ...rest } = result;
        setOutcome(rest);
        for (let i = 0; i < simSteps.length; i++) {
          setSteps(simSteps.slice(0, i + 1));
          setCur(i);
          if (i < simSteps.length - 1) {
            await new Promise<void>((r) => setTimeout(r, 350));
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
    if (particleTimerRef.current) clearTimeout(particleTimerRef.current);
    setSim(false);
    setSteps([]);
    setCur(0);
    setActNode(null);
    setActEdge(null);
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
    particles,
    runSim,
    stopSim,
    outcome,
  };
}
