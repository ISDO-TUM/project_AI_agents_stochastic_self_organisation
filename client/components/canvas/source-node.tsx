"use client";

import { useCallback } from "react";
import { Source, Tweaks } from "@/lib/types";
import { LIcon } from "@/lib/icons";
import { BURG_LT, BURG_GLOW, BURG_DIM, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";

import { useDraggable } from "@/hooks/useDraggable";

interface SourceNodeProps {
  source: Source;
  selected: boolean;
  active: boolean;
  simMode: boolean;
  swarmMode?: boolean;
  zoom: number;
  onSelect: (id: string, e: React.MouseEvent) => void;
  onDragEnd: (id: string, position: { x: number; y: number }) => void;
  onConnectStart: (id: string, e: React.MouseEvent) => void;
  tweaks: Tweaks;
}

export function SourceNode({
  source,
  selected,
  active,
  simMode,
  swarmMode = false,
  zoom,
  onSelect,
  onDragEnd,
  onConnectStart,
  tweaks,
}: SourceNodeProps) {
  const { onMouseDown: handleMouseDown } = useDraggable(
    source.id,
    source.position,
    onSelect,
    onDragEnd,
    simMode,
    zoom,
  );

  const handleConnectMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      e.preventDefault();
      onConnectStart(source.id, e);
    },
    [source.id, onConnectStart],
  );

  const { dark } = useTheme();
  const t = getTheme(dark);
  const accent = tweaks.accentColor;

  const glow = active
    ? `0 0 0 2px ${accent}, 0 0 24px 6px ${BURG_GLOW}`
    : selected
      ? `0 0 0 2px ${accent}`
      : dark
        ? "0 4px 20px rgba(0,0,0,0.5)"
        : "0 4px 16px rgba(0,0,0,0.08)";

  return (
    <div
      data-node-id={source.id}
      style={{
        position: "absolute",
        left: source.position.x - 64,
        top: source.position.y - 38,
        width: 128,
        height: 76,
        cursor: simMode ? "default" : "grab",
        userSelect: "none",
        zIndex: selected ? 10 : 5,
      }}
      onMouseDown={handleMouseDown}
    >
      <div
        style={{
          width: 128,
          height: 76,
          borderRadius: 12,
          background: dark ? "rgba(22,18,38,0.92)" : "rgba(255,255,255,0.92)",
          border: `1px solid ${selected || active ? accent : t.borderHi}`,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          position: "relative",
          boxShadow: glow,
          backdropFilter: "blur(12px)",
          transition: "box-shadow 0.2s, border-color 0.2s",
        }}
      >
        <LIcon
          name={source.type === "dataset" ? "Table2" : "FileText"}
          size={20}
          color={dark ? "rgba(255,255,255,0.35)" : "rgba(0,0,0,0.28)"}
        />
        <div
          style={{ fontSize: 12, fontWeight: 600, color: t.text, marginTop: 5 }}
        >
          {source.name}
        </div>
        <div
          style={{
            fontSize: 9,
            color: accent,
            background: BURG_DIM,
            borderRadius: 4,
            padding: "2px 7px",
            marginTop: 3,
            textTransform: "uppercase",
            letterSpacing: 1,
            fontWeight: 700,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {source.type}
        </div>
        {!simMode && !swarmMode && (
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
    </div>
  );
}
