"use client";

import { useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, X } from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { getTheme, BURG, BURG_LT } from "@/lib/theme";

export interface SwarmRunConfig {
  takersMin: number;
  takersMax: number;
  roundsMin: number;
  roundsMax: number;
  tokenBudget: number;
  maxAmendments: number;
  inviteFloor: number;
  decayRounds: number;
  attentionK: number;
}

export const DEFAULT_SWARM_CONFIG: SwarmRunConfig = {
  takersMin: 2,
  takersMax: 5,
  roundsMin: 2,
  roundsMax: 10,
  tokenBudget: 50000,
  maxAmendments: 2,
  inviteFloor: 0.3,
  decayRounds: 3,
  attentionK: 10,
};

interface SwarmConfigModalProps {
  onCancel: () => void;
  onConfirm: (config: SwarmRunConfig) => void;
}

export function SwarmConfigModal({
  onCancel,
  onConfirm,
}: SwarmConfigModalProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [config, setConfig] = useState<SwarmRunConfig>(DEFAULT_SWARM_CONFIG);
  const [advanced, setAdvanced] = useState(false);

  const field = (
    label: string,
    value: number,
    onChange: (n: number) => void,
    step = 1,
  ) => (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        marginBottom: 10,
      }}
    >
      <span style={{ fontSize: 12, color: t.textSub }}>{label}</span>
      <input
        type="number"
        value={value}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{
          width: 84,
          padding: "5px 8px",
          borderRadius: 6,
          border: `1px solid ${t.border}`,
          background: t.inputBg,
          color: t.text,
          fontSize: 12,
          textAlign: "right",
        }}
      />
    </div>
  );

  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      onClick={(e) => e.target === e.currentTarget && onCancel()}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        backdropFilter: "blur(14px)",
        background: dark ? "rgba(0,0,0,0.6)" : "rgba(255,255,255,0.45)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          width: 360,
          background: dark ? "rgba(6,5,12,0.97)" : "rgba(248,246,255,0.99)",
          border: "1px solid rgba(139,26,47,0.35)",
          borderRadius: 16,
          padding: 22,
          boxShadow: "0 28px 90px rgba(0,0,0,0.5)",
        }}
      >
        <div
          style={{ display: "flex", alignItems: "center", marginBottom: 16 }}
        >
          <span
            style={{
              fontSize: 12,
              fontWeight: 800,
              color: BURG_LT,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
            }}
          >
            Swarm Configuration
          </span>
          <button
            onClick={onCancel}
            style={{
              marginLeft: "auto",
              background: "none",
              border: "none",
              cursor: "pointer",
              color: t.textDim,
            }}
          >
            <X size={16} strokeWidth={2} />
          </button>
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <div style={{ flex: 1 }}>
            {field("Takers min", config.takersMin, (n) =>
              setConfig((c) => ({ ...c, takersMin: n })),
            )}
          </div>
          <div style={{ flex: 1 }}>
            {field("max", config.takersMax, (n) =>
              setConfig((c) => ({ ...c, takersMax: n })),
            )}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <div style={{ flex: 1 }}>
            {field("Rounds min", config.roundsMin, (n) =>
              setConfig((c) => ({ ...c, roundsMin: n })),
            )}
          </div>
          <div style={{ flex: 1 }}>
            {field("max", config.roundsMax, (n) =>
              setConfig((c) => ({ ...c, roundsMax: n })),
            )}
          </div>
        </div>
        {field(
          "Token budget",
          config.tokenBudget,
          (n) => setConfig((c) => ({ ...c, tokenBudget: n })),
          1000,
        )}
        {field("Max amendments", config.maxAmendments, (n) =>
          setConfig((c) => ({ ...c, maxAmendments: n })),
        )}

        <button
          onClick={() => setAdvanced((a) => !a)}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 5,
            background: "none",
            border: "none",
            cursor: "pointer",
            padding: "4px 0",
            fontSize: 11,
            fontWeight: 700,
            color: t.textDim,
            marginBottom: 8,
          }}
        >
          <ChevronDown
            size={11}
            style={{
              transform: advanced ? "rotate(180deg)" : "none",
              transition: "transform 0.15s",
            }}
          />
          Advanced settings
        </button>
        {advanced && (
          <div style={{ paddingLeft: 4 }}>
            {field(
              "Invite floor",
              config.inviteFloor,
              (n) => setConfig((c) => ({ ...c, inviteFloor: n })),
              0.05,
            )}
            {field("Decay rounds", config.decayRounds, (n) =>
              setConfig((c) => ({ ...c, decayRounds: n })),
            )}
            {field("Attention K", config.attentionK, (n) =>
              setConfig((c) => ({ ...c, attentionK: n })),
            )}
          </div>
        )}

        <div
          style={{
            display: "flex",
            gap: 8,
            justifyContent: "flex-end",
            marginTop: 16,
          }}
        >
          <button
            onClick={onCancel}
            style={{
              padding: "7px 16px",
              borderRadius: 100,
              border: `1px solid ${t.border}`,
              background: "none",
              color: t.textSub,
              fontSize: 12.5,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm(config)}
            style={{
              padding: "7px 18px",
              borderRadius: 100,
              border: "none",
              background: BURG,
              color: "#fff",
              fontSize: 12.5,
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            Run Swarm →
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
