"use client";

import { Layers, Bot } from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { getTheme, BURG, BURG_LT, BURG_DIM, BURG_GLOW } from "@/lib/theme";

interface SwarmNodesProps {
  boardX?: number;
  boardY?: number;
}

export function SwarmNodes({ boardX = 0, boardY = 0 }: SwarmNodesProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  const mmX = boardX - 380;
  const mmY = boardY;

  return (
    <>
      {/* ── Market Maker node ── */}
      <div
        style={{
          position: "absolute",
          left: mmX - 52,
          top: mmY - 52,
          width: 104,
          height: 104,
          pointerEvents: "none",
          zIndex: 4,
        }}
      >
        {/* Pulse ring */}
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

        {/* Core */}
        <div
          style={{
            width: "100%",
            height: "100%",
            borderRadius: "50%",
            background: dark
              ? `radial-gradient(circle at 35% 35%, rgba(196,55,79,0.22) 0%, rgba(139,26,47,0.12) 60%, rgba(6,5,12,0.9) 100%)`
              : `radial-gradient(circle at 35% 35%, rgba(196,55,79,0.15) 0%, rgba(139,26,47,0.08) 60%, rgba(240,238,248,0.95) 100%)`,
            border: `1.5px solid rgba(139,26,47,0.35)`,
            boxShadow: `0 0 24px ${BURG_GLOW}, inset 0 1px 0 rgba(255,255,255,0.08)`,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 5,
          }}
        >
          <Bot size={26} strokeWidth={1.4} color={BURG_LT} />
          <span
            style={{
              fontSize: 8.5,
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

      {/* ── Connector line from MM to Blackboard ── */}
      <svg
        style={{
          position: "absolute",
          left: Math.min(mmX, boardX - 260) - 10,
          top: Math.min(mmY, boardY) - 10,
          width: Math.abs(boardX - 260 - mmX) + 20,
          height: 20,
          overflow: "visible",
          pointerEvents: "none",
          zIndex: 3,
        }}
      >
        <line
          x1={mmX - Math.min(mmX, boardX - 260) + 10}
          y1={10}
          x2={(boardX - 260) - Math.min(mmX, boardX - 260) + 10}
          y2={10}
          stroke="rgba(139,26,47,0.25)"
          strokeWidth="1"
          strokeDasharray="5,4"
        />
      </svg>

      {/* ── Blackboard anchor node ── */}
      <div
        style={{
          position: "absolute",
          left: boardX - 260 - 44,
          top: boardY - 180 - 60,
          width: 88,
          height: 44,
          pointerEvents: "none",
          zIndex: 6,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 3,
        }}
      >
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 10,
            background: BURG_DIM,
            border: `1.5px solid rgba(139,26,47,0.4)`,
            boxShadow: `0 0 14px ${BURG_GLOW}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Layers size={16} strokeWidth={1.6} color={BURG_LT} />
        </div>
        <span
          style={{
            fontSize: 8.5,
            fontWeight: 800,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: BURG,
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
          }}
        >
          Blackboard
        </span>
      </div>

      <style>{`
        @keyframes mmPulse {
          0%, 100% { opacity: 0.4; transform: scale(1); }
          50% { opacity: 0.9; transform: scale(1.04); }
        }
      `}</style>
    </>
  );
}
