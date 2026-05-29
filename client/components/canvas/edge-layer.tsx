"use client";

import { Agent, Source, Edge, AnimatedParticle, Tweaks } from "@/lib/types";
import { BURG_LT } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";

interface EdgeLayerProps {
  edges: Edge[];
  dynamicEdges: Edge[];
  agents: Agent[];
  sources: Source[];
  selectedEdge: string | null;
  onSelectEdge: (id: string) => void;
  onDeleteEdge: (id: string) => void;
  activeEdgeId: string | null;
  activeEdgeReversed: boolean;
  animatedParticles: AnimatedParticle[];
  tweaks: Tweaks;
}

function buildPositionMap(
  agents: Agent[],
  sources: Source[],
): Map<string, { x: number; y: number }> {
  const map = new Map<string, { x: number; y: number }>();
  for (const a of agents) map.set(a.id, a.position);
  for (const s of sources) map.set(s.id, s.position);
  return map;
}

function bezierPath(
  from: { x: number; y: number },
  to: { x: number; y: number },
): string {
  const dx = to.x - from.x;
  return `M${from.x} ${from.y} C${from.x + dx * 0.55} ${from.y} ${
    to.x - dx * 0.55
  } ${to.y} ${to.x} ${to.y}`;
}

function midpoint(
  from: { x: number; y: number },
  to: { x: number; y: number },
): { x: number; y: number } {
  return { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
}

export function EdgeLayer({
  edges,
  dynamicEdges,
  agents,
  sources,
  selectedEdge,
  onSelectEdge,
  onDeleteEdge,
  activeEdgeId,
  activeEdgeReversed,
  animatedParticles,
  tweaks,
}: EdgeLayerProps) {
  const { dark } = useTheme();
  const accent = tweaks.accentColor;
  const ew = tweaks.edgeWidth;
  const base = dark ? "rgba(255,255,255,0.09)" : "rgba(0,0,0,0.13)";
  const posMap = buildPositionMap(agents, sources);

  return (
    <svg
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        overflow: "visible",
        pointerEvents: "none",
        zIndex: 2,
      }}
    >
      <defs>
        <marker
          id="arr"
          markerWidth="7"
          markerHeight="7"
          refX="5"
          refY="3.5"
          orient="auto"
        >
          <path d="M0,0 L0,7 L7,3.5z" fill={base} />
        </marker>
        <marker
          id="arr-a"
          markerWidth="7"
          markerHeight="7"
          refX="5"
          refY="3.5"
          orient="auto"
        >
          <path d="M0,0 L0,7 L7,3.5z" fill={accent} />
        </marker>
        <marker
          id="arr-s"
          markerWidth="7"
          markerHeight="7"
          refX="5"
          refY="3.5"
          orient="auto"
        >
          <path d="M0,0 L0,7 L7,3.5z" fill={BURG_LT} />
        </marker>
        <filter id="eGlow">
          <feGaussianBlur stdDeviation="3" result="b" />
          <feComposite in="SourceGraphic" in2="b" operator="over" />
        </filter>
      </defs>

      {edges.map((edge) => {
        const from = posMap.get(edge.from) ?? null;
        const to = posMap.get(edge.to) ?? null;
        if (!from || !to) return null;
        const isSelected = selectedEdge === edge.id;
        const isActive = activeEdgeId === edge.id;
        const reversed = isActive && activeEdgeReversed;
        const pathFrom = reversed ? to : from;
        const pathTo = reversed ? from : to;
        const path = bezierPath(pathFrom, pathTo);
        const mid = midpoint(from, to);

        return (
          <g key={edge.id}>
            <path
              d={path}
              stroke="transparent"
              strokeWidth={22}
              fill="none"
              style={{ pointerEvents: "stroke", cursor: "pointer" }}
              onClick={(e) => {
                e.stopPropagation();
                onSelectEdge(edge.id);
              }}
            />
            {isActive && (
              <path
                d={path}
                stroke={accent}
                strokeWidth={ew * 3}
                fill="none"
                opacity={0.2}
                filter="url(#eGlow)"
              />
            )}
            <path
              d={path}
              stroke={isActive ? accent : isSelected ? BURG_LT : base}
              strokeWidth={isActive ? ew * 1.5 : isSelected ? ew * 1.2 : ew}
              fill="none"
              markerEnd={
                isActive
                  ? "url(#arr-a)"
                  : isSelected
                    ? "url(#arr-s)"
                    : "url(#arr)"
              }
              style={{ transition: "stroke 0.2s" }}
            />
            {isActive && (
              <circle r="4.5" fill={accent} opacity={0.95}>
                <animateMotion
                  dur={`${tweaks.particleSpeed}s`}
                  repeatCount="indefinite"
                  path={path}
                />
              </circle>
            )}
            {isSelected && (
              <g
                style={{ pointerEvents: "all", cursor: "pointer" }}
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteEdge(edge.id);
                }}
              >
                <circle cx={mid.x} cy={mid.y} r={11} fill={BURG_LT} />
                <text
                  x={mid.x}
                  y={mid.y + 4.5}
                  textAnchor="middle"
                  fontSize="13"
                  fill="white"
                  style={{ userSelect: "none", fontFamily: "monospace" }}
                >
                  ✕
                </text>
              </g>
            )}
          </g>
        );
      })}

      {/* Edges formed at runtime in dynamic topology — rendered dashed so they
          read as "freshly rewired" and distinct from the static seed graph. */}
      {dynamicEdges.map((edge) => {
        const from = posMap.get(edge.from) ?? null;
        const to = posMap.get(edge.to) ?? null;
        if (!from || !to) return null;
        return (
          <path
            key={edge.id}
            d={bezierPath(from, to)}
            stroke={accent}
            strokeWidth={ew * 1.4}
            strokeDasharray="6 5"
            fill="none"
            opacity={0.8}
            markerEnd="url(#arr-a)"
            style={{ transition: "opacity 0.2s" }}
          />
        );
      })}

      {animatedParticles.map((p) => {
        const from = posMap.get(p.from) ?? null;
        const to = posMap.get(p.to) ?? null;
        if (!from || !to) return null;
        const path = bezierPath(from, to);
        return (
          <circle key={p.id} r="5" fill={BURG_LT} opacity={0.9}>
            <animateMotion
              dur={`${p.dur}s`}
              begin={`${p.delay}s`}
              repeatCount="1"
              fill="freeze"
              path={path}
            />
          </circle>
        );
      })}
    </svg>
  );
}
