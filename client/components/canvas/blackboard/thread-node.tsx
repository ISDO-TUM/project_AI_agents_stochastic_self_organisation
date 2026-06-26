"use client";

import { agentColor } from "@/lib/agent-color";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";

interface ThreadNodeProps {
  thread: { id: string; title: string };
  active: boolean;
  pos: { x: number; y: number };
  onClick: () => void;
}

export function ThreadNode({ thread, active, pos, onClick }: ThreadNodeProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const color = agentColor(thread.id);

  return (
    <button
      onClick={onClick}
      style={{
        position: "absolute",
        left: pos.x,
        top: pos.y,
        zIndex: 19,
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "5px 12px",
        borderRadius: 100,
        border: `1.5px solid ${active ? color : t.border}`,
        background: active ? `${color}22` : t.pill,
        color: active ? color : t.textSub,
        fontSize: 10.5,
        fontWeight: 700,
        fontFamily: "'Space Grotesk', system-ui, sans-serif",
        cursor: "pointer",
        whiteSpace: "nowrap",
        backdropFilter: "blur(10px)",
        boxShadow: active ? `0 0 12px ${color}44` : "none",
        transition: "all 0.15s",
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: color,
          flexShrink: 0,
        }}
      />
      {thread.title}
    </button>
  );
}
