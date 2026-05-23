"use client";

import { Bot } from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { BURG_LT, BURG_GLOW } from "@/lib/theme";

/** Viewport-anchored Market Maker badge — bottom-left of canvas */
export function SwarmNodes() {
  const { dark } = useTheme();

  return (
    <>
      {/* ── Market Maker node — bottom-left corner ── */}
      <div
        style={{
          position: "absolute",
          bottom: 56,
          left: 24,
          width: 88,
          height: 88,
          pointerEvents: "none",
          zIndex: 20,
        }}
      >
        {/* Pulse rings */}
        <div
          style={{
            position: "absolute",
            inset: -10,
            borderRadius: "50%",
            border: `1.5px solid rgba(139,26,47,0.22)`,
            animation: "mmPulse 3s ease-in-out infinite",
          }}
        />
        <div
          style={{
            position: "absolute",
            inset: -22,
            borderRadius: "50%",
            border: `1px solid rgba(139,26,47,0.10)`,
            animation: "mmPulse 3s ease-in-out infinite 0.8s",
          }}
        />

        {/* Core sphere */}
        <div
          style={{
            width: "100%",
            height: "100%",
            borderRadius: "50%",
            background: dark
              ? `radial-gradient(circle at 35% 35%, rgba(196,55,79,0.22) 0%, rgba(139,26,47,0.12) 60%, rgba(6,5,12,0.92) 100%)`
              : `radial-gradient(circle at 35% 35%, rgba(196,55,79,0.15) 0%, rgba(139,26,47,0.08) 60%, rgba(240,238,248,0.97) 100%)`,
            border: `1.5px solid rgba(139,26,47,0.35)`,
            boxShadow: `0 0 24px ${BURG_GLOW}, inset 0 1px 0 rgba(255,255,255,0.08)`,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 4,
          }}
        >
          <Bot size={22} strokeWidth={1.4} color={BURG_LT} />
          <span
            style={{
              fontSize: 7.5,
              fontWeight: 800,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: BURG_LT,
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
            }}
          >
            Market Maker
          </span>
        </div>
      </div>

      <style>{`
        @keyframes mmPulse {
          0%, 100% { opacity: 0.4; transform: scale(1); }
          50%       { opacity: 0.9; transform: scale(1.05); }
        }
      `}</style>
    </>
  );
}