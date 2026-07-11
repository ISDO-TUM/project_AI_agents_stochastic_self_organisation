"use client";

import { Agent, Source, Edge } from "@/lib/types";
import { BURG, getTheme, SURFACE_DARK_RGB } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";

interface MinimapProps {
  agents: Agent[];
  sources: Source[];
  edges: Edge[];
}

export function Minimap({ agents, sources, edges }: MinimapProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const W = 160;
  const H = 100;
  const PAD = 12;

  const all = [...agents, ...sources];
  if (!all.length) return null;

  const xs = all.map((n) => n.position.x);
  const ys = all.map((n) => n.position.y);
  const minX = Math.min(...xs) - 40;
  const maxX = Math.max(...xs) + 40;
  const minY = Math.min(...ys) - 40;
  const maxY = Math.max(...ys) + 40;
  const sc = Math.min(
    (W - PAD * 2) / Math.max(maxX - minX, 200),
    (H - PAD * 2) / Math.max(maxY - minY, 150),
  );
  const mx = (x: number) => PAD + (x - minX) * sc;
  const my = (y: number) => PAD + (y - minY) * sc;

  function bz(
    from: { x: number; y: number },
    to: { x: number; y: number },
  ): string {
    const dx = to.x - from.x;
    return `M${mx(from.x)} ${my(from.y)} C${mx(from.x + dx * 0.5)} ${my(
      from.y,
    )} ${mx(to.x - dx * 0.5)} ${my(to.y)} ${mx(to.x)} ${my(to.y)}`;
  }

  const posMap = new Map(all.map((n) => [n.id, n.position]));
  const getPos = (id: string) => posMap.get(id) ?? null;

  return (
    <div
      style={{
        position: "absolute",
        bottom: 16,
        right: 16,
        zIndex: 20,
        animation: "minimapFade 0.3s ease-out",
      }}
    >
      <svg
        width={W}
        height={H}
        style={{
          background: dark
            ? `rgba(${SURFACE_DARK_RGB},0.9)`
            : "rgba(255,255,255,0.82)",
          backdropFilter: "blur(12px)",
          borderRadius: 10,
          border: `1px solid ${t.border}`,
          display: "block",
        }}
      >
        {edges.map((e) => {
          const from = getPos(e.from);
          const to = getPos(e.to);
          if (!from || !to) return null;
          return (
            <path
              key={e.id}
              d={bz(from, to)}
              stroke={dark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)"}
              strokeWidth="1"
              fill="none"
            />
          );
        })}
        {agents.map((a) => (
          <circle
            key={a.id}
            cx={mx(a.position.x)}
            cy={my(a.position.y)}
            r={5}
            fill={BURG}
            opacity={0.85}
          />
        ))}
        {sources.map((s) => (
          <rect
            key={s.id}
            x={mx(s.position.x) - 5}
            y={my(s.position.y) - 3}
            width={10}
            height={7}
            rx={2}
            fill={dark ? "rgba(255,255,255,0.3)" : "rgba(0,0,0,0.2)"}
          />
        ))}
      </svg>
    </div>
  );
}
