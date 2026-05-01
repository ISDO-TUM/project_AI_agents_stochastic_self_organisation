"use client";

import { useState } from "react";
import { LIcon } from "@/lib/icons";
import { BURG, BURG_LT, BURG_GLOW, getTheme } from "@/lib/theme";

interface PromptBarProps {
  simMode: boolean;
  onRun: (prompt: string) => void;
  dark: boolean;
}

export function PromptBar({ simMode, onRun, dark }: PromptBarProps) {
  const [val, setVal] = useState("");
  const t = getTheme(dark);
  const canRun = !simMode && val.trim().length > 0;

  const pillStyle: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "8px 8px 8px 18px",
    background: t.pill,
    backdropFilter: "blur(28px)",
    border: `1px solid ${t.pillBorder}`,
    borderRadius: 100,
    animation: `${
      dark ? "pillPulse" : "pillPulseLight"
    } 4s ease-in-out infinite 2s`,
    width: "min(720px, 90vw)",
    boxShadow: dark
      ? "0 0 0 1px rgba(139,26,47,0.14), 0 4px 20px rgba(139,26,47,0.12), 0 8px 36px rgba(0,0,0,0.35)"
      : "0 0 0 1px rgba(139,26,47,0.10), 0 4px 18px rgba(139,26,47,0.10), 0 6px 24px rgba(0,0,0,0.07)",
    colorScheme: dark ? "dark" : "light",
  };

  return (
    <div
      style={{
        position: "absolute",
        bottom: 24,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 100,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 8,
      }}
    >
      <div style={pillStyle}>
        <input
          type="text"
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && canRun) onRun(val);
          }}
          disabled={simMode}
          placeholder="Analyze market trends and reach a consensus recommendation…"
          style={{
            flex: 1,
            background: "transparent",
            border: "none",
            outline: "none",
            color: simMode ? t.textDim : t.text,
            caretColor: t.text,
            colorScheme: dark ? "dark" : "light",
            fontSize: 13.5,
            opacity: simMode ? 0.5 : 1,
            cursor: simMode ? "not-allowed" : "text",
            minWidth: 0,
          }}
        />
        <button
          onClick={() => canRun && onRun(val)}
          disabled={!canRun}
          style={{
            background: canRun ? BURG : t.inputBg,
            border: "none",
            borderRadius: 100,
            color: canRun ? "#fff" : t.textDim,
            fontSize: 13,
            fontWeight: 700,
            padding: "9px 22px",
            cursor: canRun ? "pointer" : "not-allowed",
            transition: "all 0.18s",
            boxShadow: canRun ? `0 2px 14px ${BURG_GLOW}` : "none",
            display: "flex",
            alignItems: "center",
            gap: 7,
            whiteSpace: "nowrap",
            flexShrink: 0,
          }}
          onMouseEnter={(e) => {
            if (canRun) {
              const el = e.currentTarget as HTMLButtonElement;
              el.style.background = BURG_LT;
              el.style.boxShadow = `0 4px 20px ${BURG_GLOW}`;
            }
          }}
          onMouseLeave={(e) => {
            if (canRun) {
              const el = e.currentTarget as HTMLButtonElement;
              el.style.background = BURG;
              el.style.boxShadow = `0 2px 14px ${BURG_GLOW}`;
            }
          }}
        >
          <LIcon name="Send" size={13} color={canRun ? "#fff" : t.textDim} />
          Run
        </button>
      </div>
      {/* Disclaimer */}
      <div
        style={{ display: "flex", alignItems: "center", gap: 5, opacity: 0.45 }}
      >
        <LIcon
          name="AlertCircle"
          size={10}
          color={dark ? "rgba(255,255,255,0.5)" : "rgba(0,0,0,0.45)"}
        />
        <span
          style={{
            fontSize: 10,
            color: dark ? "rgba(255,255,255,0.45)" : "rgba(0,0,0,0.45)",
            fontFamily: "'JetBrains Mono', monospace",
            letterSpacing: 0.3,
          }}
        >
          This is an AI simulation and may make mistakes. Verify outputs
          independently.
        </span>
      </div>
    </div>
  );
}
