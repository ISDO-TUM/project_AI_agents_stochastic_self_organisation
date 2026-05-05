"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Agent, Source, Edge, SimStep, AnimatedParticle } from "@/lib/types";
import { uuid } from "@/lib/utils";
import { generateSimSteps } from "@/lib/simulation";

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
    (prompt: string) => {
      const s = generateSimSteps(agents, sources, prompt);
      if (!s.length) return;
      setSteps(s);
      setCur(0);
      setSim(true);
      setLogExp(false);
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
    },
    [agents, sources, edges],
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
