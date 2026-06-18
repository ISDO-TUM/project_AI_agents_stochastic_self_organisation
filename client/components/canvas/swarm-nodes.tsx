"use client";

import { useRef, useCallback } from "react";
import { ReceiptText } from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { BURG_LT, BURG_GLOW } from "@/lib/theme";

interface SwarmNodesProps {
  pos: { x: number; y: number } | null;
  onPosChange: (pos: { x: number; y: number }) => void;
  zoom?: number;
}

/** Draggable Market Maker badge */
export function SwarmNodes({ pos, onPosChange, zoom = 1 }: SwarmNodesProps) {
  const { dark } = useTheme();
  const dragStart = useRef<{
    mx: number;
    my: number;
    ox: number;
    oy: number;
  } | null>(null);
  const nodeRef = useRef<HTMLDivElement>(null);

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const rect = nodeRef.current!.getBoundingClientRect();
      dragStart.current = {
        mx: e.clientX,
        my: e.clientY,
        ox: rect.left,
        oy: rect.top,
      };
      const onMove = (me: MouseEvent) => {
        if (!dragStart.current) return;
        onPosChange({
          x: dragStart.current.ox + (me.clientX - dragStart.current.mx),
          y: dragStart.current.oy + (me.clientY - dragStart.current.my),
        });
      };
      const onUp = () => {
        dragStart.current = null;
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },
    [onPosChange],
  );

  const posStyle: React.CSSProperties = pos
    ? { left: pos.x, top: pos.y }
    : { bottom: 72, left: 24 };

  return (
    <>
      <div
        ref={nodeRef}
        onMouseDown={onMouseDown}
        style={{
          position: "absolute",
          ...posStyle,
          width: 88,
          height: 88,
          pointerEvents: "all",
          cursor: "grab",
          zIndex: 20,
          transform: `scale(${zoom})`,
          transformOrigin: "top left",
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
            pointerEvents: "none",
          }}
        />
        <div
          style={{
            position: "absolute",
            inset: -22,
            borderRadius: "50%",
            border: `1px solid rgba(139,26,47,0.10)`,
            animation: "mmPulse 3s ease-in-out infinite 0.8s",
            pointerEvents: "none",
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
          <ReceiptText size={22} strokeWidth={1.4} color={BURG_LT} />
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
