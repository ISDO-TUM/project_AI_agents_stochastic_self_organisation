"use client";

import { Rule } from "@/lib/types";
import { BURG, BURG_DIM, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import { LIcon } from "@/lib/icons";
import { Checkbox } from "./panels/panel-primitives";

interface TweaksPanelProps {
  rules: Rule[];
  selectedRules: Set<string>;
  onToggleRule: (id: string) => void;
  onClose: () => void;
  onOpenKeys: () => void;
}

export function TweaksPanel({
  rules,
  selectedRules,
  onToggleRule,
  onClose,
  onOpenKeys,
}: TweaksPanelProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  return (
    <div
      style={{
        position: "fixed",
        bottom: 96,
        left: 16,
        width: 320,
        background: dark ? "rgba(8,6,16,0.97)" : "rgba(255,253,255,0.98)",
        backdropFilter: "blur(28px)",
        border: `1px solid ${t.borderHi}`,
        borderRadius: 18,
        zIndex: 300,
        boxShadow: dark
          ? "0 0 0 1px rgba(139,26,47,0.16), 0 20px 60px rgba(0,0,0,0.7)"
          : "0 0 0 1px rgba(139,26,47,0.10), 0 12px 40px rgba(0,0,0,0.12)",
        animation: "tweakSlide 0.22s cubic-bezier(0.22,1,0.36,1)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 18px 10px",
          borderBottom: `1px solid ${t.border}`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <LIcon name="ScrollText" size={14} color={BURG} />
          <span style={{ fontSize: 12, fontWeight: 700, color: t.text }}>
            Ruleset
          </span>
        </div>
        <button
          onClick={onClose}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: t.textDim,
            display: "flex",
            padding: 4,
            borderRadius: 5,
          }}
          onMouseEnter={(e) =>
            ((e.currentTarget as HTMLButtonElement).style.color = t.text)
          }
          onMouseLeave={(e) =>
            ((e.currentTarget as HTMLButtonElement).style.color = t.textDim)
          }
        >
          <LIcon name="X" size={14} color="currentColor" />
        </button>
      </div>

      <div
        style={{
          padding: "12px 18px 18px",
          maxHeight: 480,
          overflowY: "auto",
        }}
      >
        <p
          style={{
            fontSize: 11,
            color: t.textDim,
            lineHeight: 1.5,
            margin: "0 0 14px",
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          Checked rules are joined as bullet points and prepended to every
          agent&apos;s system prompt.
        </p>

        {rules.length === 0 && (
          <div
            style={{
              fontSize: 12,
              color: t.textDim,
              padding: "20px 0",
              textAlign: "center",
            }}
          >
            No rules available.
          </div>
        )}

        <button
          onClick={onOpenKeys}
          style={{
            width: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: t.inputBg,
            border: `1.5px solid ${t.border}`,
            borderRadius: 10,
            padding: "10px 14px",
            color: t.text,
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
            transition: "all 0.15s",
            marginBottom: 14,
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = BURG;
            (e.currentTarget as HTMLButtonElement).style.borderColor = BURG;
            (e.currentTarget as HTMLButtonElement).style.color = "#fff";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = t.inputBg;
            (e.currentTarget as HTMLButtonElement).style.borderColor = t.border;
            (e.currentTarget as HTMLButtonElement).style.color = t.text;
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <LIcon name="KeyRound" size={14} color="currentColor" />
            API Keys
          </div>
          <LIcon name="ChevronRight" size={14} color="currentColor" />
        </button>

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {rules.map((rule) => {
            const active = selectedRules.has(rule.id);
            return (
              <div
                key={rule.id}
                role="checkbox"
                aria-checked={active}
                tabIndex={0}
                onClick={() => onToggleRule(rule.id)}
                onKeyDown={(e) =>
                  (e.key === " " || e.key === "Enter") && onToggleRule(rule.id)
                }
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 10,
                  cursor: "pointer",
                  padding: "10px 12px",
                  borderRadius: 10,
                  border: `1.5px solid ${
                    active ? "rgba(139,26,47,0.38)" : t.border
                  }`,
                  background: active ? BURG_DIM : t.inputBg,
                  transition: "all 0.15s",
                }}
              >
                <div style={{ paddingTop: 1, flexShrink: 0 }}>
                  <Checkbox
                    checked={active}
                    onChange={() => onToggleRule(rule.id)}
                  />
                </div>
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 4,
                    minWidth: 0,
                  }}
                >
                  <span
                    style={{
                      fontSize: 13,
                      color: t.text,
                      fontWeight: active ? 600 : 500,
                    }}
                  >
                    {rule.label}
                  </span>
                  <span
                    style={{
                      fontSize: 11,
                      color: t.textSub,
                      lineHeight: 1.5,
                    }}
                  >
                    {rule.instruction}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
