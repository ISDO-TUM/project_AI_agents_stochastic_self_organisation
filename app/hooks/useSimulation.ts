"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Agent, Source, Edge, SimStep, AnimatedParticle } from "@/lib/types";
import { uuid, timestamp } from "@/lib/utils";
import { buildStepsFromTrial, emptyCanvasSteps } from "@/lib/simulation";
import { runTrial, getTrial } from "@/lib/api";

export function useSimulation(
  agents: Agent[],
  sources: Source[],
  edges: Edge[],
) {
  const [steps, setSteps] = useState<SimStep[]>([]);
  const [cur, setCur] = useState(0);
  const [simMode, setSim] = useState(false);
  const [logExp, setLogExp] = useState(false);
  const [activeNode, setActNode] = useState<string | null>(null);
  const [activeEdge, setActEdge] = useState<string | null>(null);
  const [particles, setParticles] = useState<AnimatedParticle[]>([]);
  const [running, setRunning] = useState(false);
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
    async (prompt: string) => {
      if (running) return;

      if (agents.length === 0) {
        setSteps(emptyCanvasSteps(agents, sources));
        setCur(0);
        setSim(true);
        setLogExp(false);
        return;
      }

      setRunning(true);
      setSim(true);
      setLogExp(false);
      setSteps([
        {
          id: uuid(),
          ts: timestamp(),
          label: "SYSTEM",
          msg: "Running consensus on the backend…",
          type: "system",
        },
      ]);
      setCur(0);

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
        const agentIds = agents.map((a) => a.id);
        const idMap: Record<string, string> = Object.fromEntries(
          agentIds.map((id) => [id, id]),
        );
        const runResp = await runTrial(prompt, agentIds, 2);
        const trial = await getTrial(runResp.trial_id);
        const realSteps = buildStepsFromTrial(trial, agents, idMap);
        setSteps(realSteps);
        setCur(0);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setSteps((prev) => [
          ...prev,
          {
            id: uuid(),
            ts: timestamp(),
            label: "ERROR",
            msg: `Trial failed: ${message}`,
            type: "system",
          },
        ]);
      } finally {
        setRunning(false);
      }
    },
    [agents, sources, edges, running],
  );

  const stopSim = useCallback(() => {
    if (particleTimerRef.current) clearTimeout(particleTimerRef.current);
    setSim(false);
    setSteps([]);
    setCur(0);
    setActNode(null);
    setActEdge(null);
    setParticles([]);
    setRunning(false);
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
    running,
    runSim,
    stopSim,
  };
}
