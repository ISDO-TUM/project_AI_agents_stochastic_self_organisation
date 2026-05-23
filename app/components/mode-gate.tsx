"use client";

import { useState } from "react";
import {
  Network,
  Layers,
  ArrowRight,
  Cpu,
  GitBranch,
  Sparkles,
} from "lucide-react";
import { getTheme } from "@/lib/theme";
import { BURG, BURG_LT, BURG_DIM, BURG_GLOW } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";

export type AppMode = "topology" | "swarm";

interface ModeGateProps {
  onSelect: (mode: AppMode) => void;
}

interface ModeCardProps {
  mode: AppMode;
  selected: boolean;
  onHover: (m: AppMode | null) => void;
  onClick: () => void;
  dark: boolean;
}

function ModeCard({ mode, selected, onHover, onClick, dark }: ModeCardProps) {
  const t = getTheme(dark);
  const isTopology = mode === "topology";

  const icon = isTopology ? (
    <Network size={40} strokeWidth={1.4} color={selected ? BURG_LT : t.textSub} />
  ) : (
    <Layers size={40} strokeWidth={1.4} color={selected ? BURG_LT : t.textSub} />
  );

  const badge = isTopology ? (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: t.textDim,
        background: t.pill,
        border: `1px solid ${t.border}`,
        borderRadius: 20,
        padding: "2px 8px",
      }}
    >
      <GitBranch size={9} strokeWidth={2} />
      Deterministic
    </span>
  ) : (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: selected ? BURG_LT : t.textDim,
        background: selected ? `rgba(139,26,47,0.10)` : t.pill,
        border: `1px solid ${selected ? "rgba(139,26,47,0.35)" : t.border}`,
        borderRadius: 20,
        padding: "2px 8px",
      }}
    >
      <Sparkles size={9} strokeWidth={2} />
      Experimental
    </span>
  );

  const bullets = isTopology
    ? [
        { icon: <Network size={12} strokeWidth={1.7} />, text: "Graph-topology routing" },
        { icon: <Cpu size={12} strokeWidth={1.7} />, text: "Deterministic multi-round consensus" },
        { icon: <GitBranch size={12} strokeWidth={1.7} />, text: "Weighted pooling & plurality voting" },
      ]
    : [
        { icon: <Layers size={12} strokeWidth={1.7} />, text: "Free-market agent self-selection" },
        { icon: <Sparkles size={12} strokeWidth={1.7} />, text: "Shared append-only blackboard" },
        { icon: <Cpu size={12} strokeWidth={1.7} />, text: "Citation-based stigmergic consensus" },
      ];

  return (
    <button
      onClick={onClick}
      onMouseEnter={() => onHover(mode)}
      onMouseLeave={() => onHover(null)}
      style={{
        position: "relative",
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        gap: 20,
        width: 300,
        padding: "32px 28px",
        background: selected
          ? dark
            ? "rgba(139,26,47,0.10)"
            : "rgba(139,26,47,0.06)"
          : t.surface,
        border: `1.5px solid ${selected ? "rgba(139,26,47,0.45)" : t.border}`,
        borderRadius: 16,
        cursor: "pointer",
        textAlign: "left",
        boxShadow: selected
          ? `0 0 0 1px rgba(139,26,47,0.18), 0 8px 32px ${BURG_GLOW}`
          : dark
          ? "0 2px 16px rgba(0,0,0,0.4)"
          : "0 2px 16px rgba(0,0,0,0.06)",
        transition: "all 0.18s ease",
        outline: "none",
      }}
    >
      {/* Top row: icon + badge */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", width: "100%" }}>
        <div
          style={{
            width: 64,
            height: 64,
            borderRadius: 14,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: selected ? BURG_DIM : dark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)",
            border: `1px solid ${selected ? "rgba(139,26,47,0.22)" : t.border}`,
            transition: "all 0.18s ease",
          }}
        >
          {icon}
        </div>
        {badge}
      </div>

      {/* Title + description */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span
          style={{
            fontSize: 18,
            fontWeight: 700,
            color: selected ? (dark ? "#fff" : t.text) : t.text,
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
            letterSpacing: "-0.01em",
          }}
        >
          {isTopology ? "Topology" : "Swarm"}
        </span>
        <span
          style={{
            fontSize: 12.5,
            lineHeight: 1.55,
            color: t.textSub,
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
          }}
        >
          {isTopology
            ? "Route prompts through a directed agent graph. Each agent passes its reply to its neighbours."
            : "Agents bid for contracts, deliberate on a blackboard, and converge through citation mechanics."}
        </span>
      </div>

      {/* Bullets */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {bullets.map(({ icon: bIcon, text }, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              color: selected ? t.textSub : t.textDim,
              transition: "color 0.18s",
            }}
          >
            <span style={{ color: selected ? BURG_LT : t.textDim, flexShrink: 0 }}>{bIcon}</span>
            <span style={{ fontSize: 11.5, fontFamily: "'Space Grotesk', system-ui, sans-serif" }}>
              {text}
            </span>
          </div>
        ))}
      </div>

      {/* Selected indicator */}
      {selected && (
        <div
          style={{
            position: "absolute",
            bottom: 16,
            right: 20,
            display: "flex",
            alignItems: "center",
            gap: 5,
            fontSize: 11,
            fontWeight: 700,
            color: BURG_LT,
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
          }}
        >
          Selected
          <div
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: BURG_LT,
              boxShadow: `0 0 6px ${BURG_LT}`,
            }}
          />
        </div>
      )}
    </button>
  );
}

export function ModeGate({ onSelect }: ModeGateProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [hovered, setHovered] = useState<AppMode | null>(null);
  void hovered; // reserved for future hover animations
  const [chosen, setChosen] = useState<AppMode>("topology");

  const handleConfirm = () => onSelect(chosen);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: t.bg,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 48,
        zIndex: 9999,
      }}
    >
      {/* Subtle grid background */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage: `radial-gradient(circle, ${t.dotColor} 1px, transparent 1px)`,
          backgroundSize: "28px 28px",
          pointerEvents: "none",
          opacity: 0.7,
        }}
      />

      {/* Glow blob */}
      <div
        style={{
          position: "absolute",
          top: "30%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: 480,
          height: 280,
          borderRadius: "50%",
          background: `radial-gradient(ellipse, ${BURG_GLOW} 0%, transparent 70%)`,
          pointerEvents: "none",
          filter: "blur(40px)",
          opacity: 0.5,
        }}
      />

      {/* Header */}
      <div style={{ position: "relative", textAlign: "center", display: "flex", flexDirection: "column", gap: 10 }}>
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: BURG,
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
            marginBottom: 4,
          }}
        >
          <div style={{ width: 16, height: 1, background: BURG, opacity: 0.6 }} />
          ECSAS Agent Platform
          <div style={{ width: 16, height: 1, background: BURG, opacity: 0.6 }} />
        </div>
        <h1
          style={{
            fontSize: 32,
            fontWeight: 800,
            color: t.text,
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
            letterSpacing: "-0.03em",
            margin: 0,
          }}
        >
          Choose simulation mode
        </h1>
        <p
          style={{
            fontSize: 14,
            color: t.textSub,
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
            margin: 0,
          }}
        >
          Select how your agent network will coordinate and reach consensus.
        </p>
      </div>

      {/* Cards */}
      <div style={{ position: "relative", display: "flex", gap: 20 }}>
        <ModeCard
          mode="topology"
          selected={chosen === "topology"}
          onHover={setHovered}
          onClick={() => setChosen("topology")}
          dark={dark}
        />
        <ModeCard
          mode="swarm"
          selected={chosen === "swarm"}
          onHover={setHovered}
          onClick={() => setChosen("swarm")}
          dark={dark}
        />
      </div>

      {/* Confirm button */}
      <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
        <button
          onClick={handleConfirm}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "13px 32px",
            background: BURG,
            color: "#fff",
            border: "none",
            borderRadius: 10,
            cursor: "pointer",
            fontSize: 14,
            fontWeight: 700,
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
            letterSpacing: "-0.01em",
            boxShadow: `0 4px 20px ${BURG_GLOW}`,
            transition: "all 0.15s ease",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = BURG_LT;
            (e.currentTarget as HTMLButtonElement).style.transform = "translateY(-1px)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = BURG;
            (e.currentTarget as HTMLButtonElement).style.transform = "translateY(0)";
          }}
        >
          Enter{" "}
          {chosen === "topology" ? "Topology" : "Swarm"} mode
          <ArrowRight size={16} strokeWidth={2} />
        </button>
        <span
          style={{
            fontSize: 11,
            color: t.textDim,
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
          }}
        >
          You can switch modes by refreshing the page
        </span>
      </div>
    </div>
  );
}
