"use client";

import { MONO, StatCard, labelStyle } from "@/components/statistics/primitives";
import { LIcon } from "@/lib/icons";
import { getTheme } from "@/lib/theme";
import type { AgentStat, EdgeStat } from "@/lib/types";

const SIZE = 420;
const RADIUS = 148;
const NODE_R = 17;
const BOARD_ID = "__bidding_board__";
const BOARD_R = 25;

interface Node {
  id: string;
  name: string;
  x: number;
  y: number;
  kind: "agent" | "board";
}

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0][0] ?? "?";
  const second = parts[1]?.[0] ?? parts[0][1] ?? "";
  return (first + second).toUpperCase();
}

function truncate(name: string, max = 17) {
  return name.length > max ? `${name.slice(0, max - 1)}…` : name;
}

export function CommunicationGraph({
  agents,
  edges,
  dark,
  delay = 0,
}: {
  agents: AgentStat[];
  edges: EdgeStat[];
  dark: boolean;
  delay?: number;
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
      kind: "agent",
    };
  });
  if (
    edges.some((e) => e.toAgentId === BOARD_ID || e.fromAgentId === BOARD_ID)
  ) {
    nodes.push({ id: BOARD_ID, name: "Board", x: cx, y: cy, kind: "board" });
  }
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const byIdName = new Map(nodes.map((n) => [n.id, n.name]));
  const maxCount = Math.max(1, ...edges.map((e) => e.messageCount));

  return (
    <StatCard
      title="Communication network"
      icon="Waypoints"
      dark={dark}
      delay={delay}
      minHeight={300}
      meta={
        <span style={{ color: t.textDim, fontSize: 11, fontFamily: MONO }}>
          {edges.length} routes
        </span>
      }
    >
      {agents.length === 0 ? (
        <div
          style={{
            height: "100%",
            minHeight: 220,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            color: t.textSub,
          }}
        >
          <LIcon name="Unplug" size={22} color={t.textDim} />
          <span style={{ ...labelStyle(dark), letterSpacing: 1 }}>
            No communication recorded
          </span>
        </div>
      ) : (
        <svg
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          width="100%"
          style={{ display: "block", maxWidth: SIZE + 20, margin: "0 auto" }}
          role="img"
          aria-label="Agent communication network"
        >
          <defs>
            <marker
              id="stat-arrow"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="5.5"
              markerHeight="5.5"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#a83048" />
            </marker>
            <radialGradient id="stat-node-grad" cx="35%" cy="30%" r="85%">
              <stop offset="0%" stopColor="#c4374f" />
              <stop offset="100%" stopColor="#8b1a2f" />
            </radialGradient>
            <linearGradient
              id="stat-board-grad"
              x1="0%"
              y1="0%"
              x2="100%"
              y2="100%"
            >
              <stop offset="0%" stopColor="#3d4657" />
              <stop offset="100%" stopColor="#1d2430" />
            </linearGradient>
          </defs>

          {/* faint orbit ring behind the nodes */}
          <circle
            cx={cx}
            cy={cy}
            r={RADIUS}
            fill="none"
            stroke={t.border}
            strokeDasharray="2 6"
          />

          {edges.map((e) => {
            const a = byId.get(e.fromAgentId);
            const b = byId.get(e.toAgentId);
            if (!a || !b) return null;
            const w = e.messageCount / maxCount;
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const dist = Math.hypot(dx, dy) || 1;
            const ux = dx / dist;
            const uy = dy / dist;
            const fromR = a.kind === "board" ? BOARD_R : NODE_R;
            const toR = b.kind === "board" ? BOARD_R : NODE_R;
            // Trim ends so strokes and arrowheads stop at the node circles,
            // and bow each direction to its own side so A→B and B→A never
            // overlap.
            const sx = a.x + ux * (fromR + 3);
            const sy = a.y + uy * (fromR + 3);
            const ex = b.x - ux * (toR + 7);
            const ey = b.y - uy * (toR + 7);
            const bow = Math.min(22, dist * 0.12);
            const qx = (sx + ex) / 2 - uy * bow;
            const qy = (sy + ey) / 2 + ux * bow;
            return (
              <path
                key={`${e.fromAgentId}-${e.toAgentId}`}
                d={`M ${sx} ${sy} Q ${qx} ${qy} ${ex} ${ey}`}
                fill="none"
                stroke="#8b1a2f"
                strokeOpacity={0.3 + w * 0.55}
                strokeWidth={1 + w * 4.5}
                strokeLinecap="round"
                markerEnd="url(#stat-arrow)"
              >
                <title>
                  {`${byIdName.get(e.fromAgentId) ?? "?"} → ${
                    byIdName.get(e.toAgentId) ?? "?"
                  } · ${e.messageCount} message${
                    e.messageCount === 1 ? "" : "s"
                  }`}
                </title>
              </path>
            );
          })}

          {nodes
            .filter((n) => n.kind === "board")
            .map((n) => (
              <g key={n.id}>
                <rect
                  x={n.x - 36}
                  y={n.y - 25}
                  width={72}
                  height={50}
                  rx={8}
                  fill="#1d2430"
                  opacity={0.18}
                />
                <rect
                  x={n.x - 30}
                  y={n.y - 21}
                  width={60}
                  height={42}
                  rx={7}
                  fill="url(#stat-board-grad)"
                  stroke="rgba(255,255,255,0.28)"
                  strokeWidth={1}
                >
                  <title>{n.name}</title>
                </rect>
                <path
                  d={`M ${n.x - 18} ${n.y - 6} H ${n.x + 18} M ${n.x - 18} ${
                    n.y + 3
                  } H ${n.x + 14} M ${n.x - 18} ${n.y + 12} H ${n.x + 8}`}
                  stroke="rgba(255,255,255,0.78)"
                  strokeWidth={2}
                  strokeLinecap="round"
                />
                <text
                  x={n.x}
                  y={n.y - 30}
                  textAnchor="middle"
                  fontSize={10}
                  fontWeight={700}
                  fill={t.textSub}
                >
                  Board
                </text>
              </g>
            ))}

          {nodes
            .filter((n) => n.kind === "agent")
            .map((n) => (
              <g key={n.id}>
                <circle
                  cx={n.x}
                  cy={n.y}
                  r={NODE_R + 6}
                  fill="#8b1a2f"
                  opacity={0.16}
                />
                <circle
                  cx={n.x}
                  cy={n.y}
                  r={NODE_R}
                  fill="url(#stat-node-grad)"
                  stroke="rgba(255,255,255,0.28)"
                  strokeWidth={1}
                >
                  <title>{n.name}</title>
                </circle>
                <text
                  x={n.x}
                  y={n.y + 4}
                  textAnchor="middle"
                  fontSize={11}
                  fontWeight={700}
                  fill="#fff"
                  style={{ pointerEvents: "none", userSelect: "none" }}
                >
                  {initials(n.name)}
                </text>
                <text
                  x={n.x}
                  y={n.y + NODE_R + 17}
                  textAnchor="middle"
                  fontSize={10}
                  fontWeight={600}
                  fill={t.textSub}
                >
                  {truncate(n.name)}
                  <title>{n.name}</title>
                </text>
              </g>
            ))}
        </svg>
      )}
    </StatCard>
  );
}
