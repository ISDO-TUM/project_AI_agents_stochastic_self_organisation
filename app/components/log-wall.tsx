"use client";

import { useEffect, useRef } from "react";
import { SimStep } from "@/lib/types";
import { BURG, BURG_LT, BURG_GLOW, getTheme } from "@/lib/theme";
import { LIcon } from "@/lib/icons";

interface LogWallProps {
  steps: SimStep[];
  currentStep: number;
  onNext: () => void;
  onPrev: () => void;
  expanded: boolean;
  onToggleExpand: () => void;
  dark: boolean;
}

function typeIcon(type: SimStep["type"]): string {
  const map: Record<SimStep["type"], string> = {
    system: "Eye",
    "agent-to-agent": "Send",
    tool: "Wrench",
    "agent-to-source": "FileText",
  };
  return map[type] ?? "Eye";
}

function typeColor(
  type: SimStep["type"],
  dark: boolean,
  textDim: string,
): string {
  switch (type) {
    case "system":
      return BURG;
    case "agent-to-agent":
      return dark ? "#7A7ACC" : "#4444AA";
    case "tool":
      return dark ? "#4A9A6A" : "#1A5A3A";
    case "agent-to-source":
      return dark ? "#9A7A4A" : "#5A4012";
    default:
      return textDim;
  }
}

export function LogWall({
  steps,
  currentStep,
  onNext,
  onPrev,
  expanded,
  onToggleExpand,
  dark,
}: LogWallProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const t = getTheme(dark);

  useEffect(() => {
    if (!listRef.current) return;
    const active = listRef.current.querySelector<HTMLElement>(
      '[data-active="true"]',
    );
    if (active) {
      const c = listRef.current;
      c.scrollTop =
        active.offsetTop -
        c.offsetTop -
        c.clientHeight / 2 +
        active.clientHeight / 2;
    }
  }, [currentStep]);

  const width = expanded ? "100vw" : 290;

  return (
    <div
      style={{
        width,
        minWidth: width,
        height: "100%",
        background: dark ? "rgba(5,4,10,0.95)" : "rgba(252,250,255,0.96)",
        backdropFilter: "blur(24px)",
        borderLeft: `1px solid ${t.border}`,
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
        position: expanded ? "absolute" : "relative",
        inset: expanded ? 0 : "auto",
        zIndex: 50,
        animation: "logSlide 0.3s cubic-bezier(0.22,1,0.36,1)",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 18px",
          borderBottom: `1px solid ${t.border}`,
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: BURG,
              boxShadow: `0 0 8px ${BURG_GLOW}`,
            }}
          />
          <span
            style={{
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: 1.5,
              textTransform: "uppercase",
              color: t.textDim,
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            Activity Log
          </span>
        </div>
        <button
          onClick={onToggleExpand}
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
          <LIcon
            name={expanded ? "Minimize2" : "Maximize2"}
            size={13}
            color="currentColor"
          />
        </button>
      </div>

      {/* Steps */}
      <div
        ref={listRef}
        style={{ flex: 1, overflowY: "auto", padding: "4px 0" }}
      >
        {steps.map((step, idx) => {
          const isActive = idx === currentStep;
          const isPast = idx < currentStep;
          const isFuture = idx > currentStep;
          const color = typeColor(step.type, dark, t.textDim);
          return (
            <div
              key={step.id}
              data-active={isActive ? "true" : "false"}
              style={{
                padding: "11px 18px",
                borderLeft: `2.5px solid ${isActive ? BURG : "transparent"}`,
                background: isActive
                  ? dark
                    ? "rgba(139,26,47,0.08)"
                    : "rgba(139,26,47,0.05)"
                  : "transparent",
                opacity: isFuture ? 0.15 : isPast ? 0.45 : 1,
                transition: "all 0.2s",
              }}
            >
              <div
                style={{ display: "flex", alignItems: "flex-start", gap: 10 }}
              >
                <span style={{ marginTop: 2, flexShrink: 0 }}>
                  <LIcon name={typeIcon(step.type)} size={11} color={color} />
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      marginBottom: 3,
                      flexWrap: "wrap",
                    }}
                  >
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 700,
                        color: isActive ? BURG : color,
                      }}
                    >
                      {step.label}
                    </span>
                    {step.target && (
                      <>
                        <span style={{ fontSize: 10, color: t.textDim }}>
                          →
                        </span>
                        <span
                          style={{
                            fontSize: 11,
                            fontWeight: 600,
                            color: dark ? "#8888CC" : "#4444AA",
                          }}
                        >
                          {step.target}
                        </span>
                      </>
                    )}
                    <span
                      style={{
                        fontSize: 9.5,
                        color: t.textDim,
                        marginLeft: "auto",
                        fontFamily: "'JetBrains Mono', monospace",
                        flexShrink: 0,
                      }}
                    >
                      {step.ts}
                    </span>
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      color: isActive ? t.text : t.textSub,
                      lineHeight: 1.45,
                      fontFamily: "'JetBrains Mono', monospace",
                    }}
                  >
                    {step.msg}
                  </div>
                  {isActive && (
                    <div style={{ marginTop: 6 }}>
                      <span
                        style={{
                          fontSize: 9,
                          background: BURG,
                          color: "#fff",
                          borderRadius: 3,
                          padding: "1px 7px",
                          fontFamily: "'JetBrains Mono', monospace",
                          letterSpacing: 0.5,
                        }}
                      >
                        STEP {idx + 1}/{steps.length}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Navigation */}
      <div
        style={{
          display: "flex",
          gap: 8,
          padding: "14px 18px",
          borderTop: `1px solid ${t.border}`,
          flexShrink: 0,
        }}
      >
        <button
          onClick={onPrev}
          disabled={currentStep <= 0}
          style={{
            flex: 1,
            padding: "9px 0",
            background: t.inputBg,
            border: `1px solid ${t.border}`,
            borderRadius: 9,
            color: currentStep <= 0 ? t.textDim : t.text,
            fontSize: 12,
            fontWeight: 600,
            cursor: currentStep <= 0 ? "not-allowed" : "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 5,
          }}
        >
          <LIcon name="ChevronLeft" size={13} color="currentColor" /> Prev
        </button>
        <button
          onClick={onNext}
          disabled={currentStep >= steps.length - 1}
          style={{
            flex: 1,
            padding: "9px 0",
            background: currentStep >= steps.length - 1 ? t.inputBg : BURG,
            border: "none",
            borderRadius: 9,
            color: currentStep >= steps.length - 1 ? t.textDim : "#fff",
            fontSize: 12,
            fontWeight: 600,
            cursor: currentStep >= steps.length - 1 ? "not-allowed" : "pointer",
            boxShadow:
              currentStep < steps.length - 1
                ? `0 2px 12px ${BURG_GLOW}`
                : "none",
            transition: "all 0.15s",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 5,
          }}
          onMouseEnter={(e) => {
            if (currentStep < steps.length - 1)
              (e.currentTarget as HTMLButtonElement).style.background = BURG_LT;
          }}
          onMouseLeave={(e) => {
            if (currentStep < steps.length - 1)
              (e.currentTarget as HTMLButtonElement).style.background = BURG;
          }}
        >
          Next <LIcon name="ChevronRight" size={13} color="currentColor" />
        </button>
      </div>
    </div>
  );
}
