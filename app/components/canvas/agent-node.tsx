"use client";

import { useCallback } from "react";
import { Agent, Tweaks } from "@/lib/types";
import { TOOL_ICON, LIcon } from "@/lib/icons";
import { BURG_LT, BURG_GLOW, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";

import { useDraggable } from "@/hooks/useDraggable";

interface AgentNodeProps {
  agent: Agent;
  selected: boolean;
  active: boolean;
  simMode: boolean;
  onSelect: (id: string, e: React.MouseEvent) => void;
  onDragEnd: (id: string, position: { x: number; y: number }) => void;
  onConnectStart: (id: string, e: React.MouseEvent) => void;
  tweaks: Tweaks;
}

export function AgentNode({
  agent,
  selected,
  active,
  simMode,
  onSelect,
  onDragEnd,
  onConnectStart,
  tweaks,
}: AgentNodeProps) {
  const { onMouseDown: handleMouseDown } = useDraggable(
    agent.id,
    agent.position,
    onSelect,
    onDragEnd,
    simMode,
  );

  const handleConnectMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      e.preventDefault();
      onConnectStart(agent.id, e);
    },
    [agent.id, onConnectStart],
  );

  const { dark } = useTheme();
  const t = getTheme(dark);
  const accent = tweaks.accentColor;
  const ns = tweaks.nodeSize;
  const half = ns / 2;
  const initial = (agent.name || "A")[0].toUpperCase();
  const provider = agent.provider === "anthropic" ? "Anthropic" : "OpenAI";

  const glow = active
    ? `0 0 0 2px ${accent}, 0 0 30px 8px rgba(139,26,47,0.38), 0 0 60px 16px rgba(139,26,47,0.12)`
    : selected
      ? `0 0 0 2px ${accent}, 0 0 16px 4px rgba(139,26,47,0.2)`
      : dark
        ? "0 4px 24px rgba(0,0,0,0.55)"
        : "0 4px 20px rgba(0,0,0,0.1)";

  const nodeBg = dark
    ? "radial-gradient(circle at 35% 35%, rgba(255,255,255,0.06) 0%, rgba(0,0,0,0.2) 100%)"
    : "radial-gradient(circle at 35% 35%, rgba(255,255,255,0.95) 0%, rgba(235,232,248,0.85) 100%)";

  return (
    <div
      data-node-id={agent.id}
      style={{
        position: "absolute",
        left: agent.position.x - half,
        top: agent.position.y - half,
        width: ns,
        height: ns,
        cursor: simMode ? "default" : "grab",
        userSelect: "none",
        zIndex: selected ? 10 : 5,
      }}
      onMouseDown={handleMouseDown}
    >
      {active && tweaks.showPulse && (
        <>
          <div
            style={{
              position: "absolute",
              inset: -10,
              borderRadius: "50%",
              border: `1.5px solid ${accent}`,
              animation: "pulseRing 1.1s ease-out infinite",
              pointerEvents: "none",
              opacity: 0.7,
            }}
          />
          <div
            style={{
              position: "absolute",
              inset: -22,
              borderRadius: "50%",
              border: `1px solid ${accent}`,
              animation: "pulseRing2 1.4s ease-out infinite 0.2s",
              pointerEvents: "none",
              opacity: 0.4,
            }}
          />
        </>
      )}
      <div
        style={{
          width: ns,
          height: ns,
          borderRadius: "50%",
          background: nodeBg,
          border: `1px solid ${selected || active ? accent : t.borderHi}`,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          position: "relative",
          transition: "box-shadow 0.2s, border-color 0.2s",
          boxShadow: glow,
          backdropFilter: "blur(14px)",
        }}
      >
        <span
          style={{
            fontSize: ns * 0.33,
            fontWeight: 700,
            color: accent,
            lineHeight: 1,
            letterSpacing: -1,
          }}
        >
          {initial}
        </span>
        {agent.tools.length > 0 && (
          <div
            style={{
              display: "flex",
              gap: 3,
              marginTop: 3,
              justifyContent: "center",
            }}
          >
            {agent.tools.slice(0, 4).map((tool) => (
              <LIcon
                key={tool}
                name={TOOL_ICON[tool] || "Wrench"}
                size={9}
                color={dark ? "rgba(255,255,255,0.3)" : "rgba(0,0,0,0.25)"}
              />
            ))}
          </div>
        )}
        {!simMode && (
          <div
            className="connect-handle"
            onMouseDown={handleConnectMouseDown}
            style={{
              position: "absolute",
              right: -9,
              top: "50%",
              transform: "translateY(-50%)",
              width: 16,
              height: 16,
              borderRadius: "50%",
              background: accent,
              border: `2.5px solid ${BURG_LT}`,
              cursor: "crosshair",
              zIndex: 20,
              boxShadow: `0 0 10px ${BURG_GLOW}`,
            }}
            data-connect-handle="true"
          />
        )}
      </div>
      <div
        style={{
          position: "absolute",
          top: ns + 8,
          left: "50%",
          transform: "translateX(-50%)",
          whiteSpace: "nowrap",
          textAlign: "center",
          pointerEvents: "none",
        }}
      >
        <div style={{ fontSize: 12, fontWeight: 600, color: t.text }}>
          {agent.name}
        </div>
        <div
          style={{
            fontSize: 10,
            color: t.textDim,
            marginTop: 1,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {provider} · {agent.model}
        </div>
      </div>
    </div>
  );
}
