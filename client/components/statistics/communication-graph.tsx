"use client";

import { getTheme } from "@/lib/theme";
import type { AgentStat, EdgeStat } from "@/lib/types";

const SIZE = 420;
const RADIUS = 150;
const NODE_R = 18;

interface Node {
  id: string;
  name: string;
  x: number;
  y: number;
}

export function CommunicationGraph({
  agents,
  edges,
  dark,
}: {
  agents: AgentStat[];
  edges: EdgeStat[];
  dark: boolean;
}) {
  const t = getTheme(dark);
  const cx = SIZE / 2;
  const cy = SIZE / 2;

  const nodes: Node[] = agents.map((a, i) => {
    const angle = (i / Math.max(agents.length, 1)) * 2 * Math.PI - Math.PI / 2;
    return {
      id: a.agentId,
      name: a.agentName,
      x: cx + RADIUS * Math.cos(angle),
      y: cy + RADIUS * Math.sin(angle),
    };
  });
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const maxCount = Math.max(1, ...edges.map((e) => e.messageCount));

  return (
    <div
      style={{
        background: t.surface,
        border: `1px solid ${t.border}`,
        borderRadius: 8,
        padding: 16,
        minHeight: 468,
      }}
    >
      <div
        style={{
          color: t.text,
          fontSize: 13,
          fontWeight: 600,
          marginBottom: 8,
        }}
      >
        Communication graph
      </div>
      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        width="100%"
        style={{ display: "block", maxWidth: SIZE, margin: "0 auto" }}
      >
        <defs>
          <marker
            id="stat-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill={t.textSub} />
          </marker>
        </defs>

        {edges.map((e) => {
          const a = byId.get(e.fromAgentId);
          const b = byId.get(e.toAgentId);
          if (!a || !b) return null;
          const width = 1 + (e.messageCount / maxCount) * 6;
          return (
            <line
              key={`${e.fromAgentId}-${e.toAgentId}`}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke="#8b1a2f"
              strokeOpacity={0.55}
              strokeWidth={width}
              markerEnd="url(#stat-arrow)"
            />
          );
        })}

        {nodes.map((n) => (
          <g key={n.id}>
            <circle cx={n.x} cy={n.y} r={NODE_R} fill="#8b1a2f" />
            <text
              x={n.x}
              y={n.y + NODE_R + 12}
              textAnchor="middle"
              fontSize={10}
              fill={t.text}
            >
              {n.name}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}
