"use client";

import { useEffect, useRef, useCallback } from "react";
import { SimStep } from "@/lib/types";
import { BURG, BURG_LT, BURG_GLOW, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { LIcon } from "@/lib/icons";

const MIN_WIDTH = 220;
const MAX_WIDTH = 640;

interface LogWallProps {
  steps: SimStep[];
  currentStep: number;
  onNext: () => void;
  onPrev: () => void;
  onJumpTo: (idx: number) => void;
  expanded: boolean;
  onToggleExpand: () => void;
  sidebarWidth: number;
  onSidebarWidthChange: (w: number) => void;
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
  roundIndex?: number,
): string {
  if (roundIndex != null) {
    const colors = dark
      ? ["#C4374F", "#7A7ACC", "#4A9A6A", "#C98A35", "#9B72D9", "#4E9FBF"]
      : ["#8B1A2F", "#4444AA", "#1A5A3A", "#9A5B05", "#6D3AB5", "#0F6F8E"];
    return colors[(roundIndex - 1) % colors.length];
  }
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
  onJumpTo,
  expanded,
  onToggleExpand,
  sidebarWidth,
  onSidebarWidthChange,
}: LogWallProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const { dark } = useTheme();
  const t = getTheme(dark);

  // ── Resize drag ────────────────────────────────────────────────────────
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);

  const onResizeMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragRef.current = { startX: e.clientX, startW: sidebarWidth };
    },
    [sidebarWidth],
  );

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragRef.current) return;
      // handle is on the left edge → dragging left increases width
      const delta = dragRef.current.startX - e.clientX;
      onSidebarWidthChange(
        Math.min(
          MAX_WIDTH,
          Math.max(MIN_WIDTH, dragRef.current.startW + delta),
        ),
      );
    };
    const onUp = () => {
      dragRef.current = null;
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [onSidebarWidthChange]);

  // ── Scroll active step into view ──────────────────────────────────────────
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

  // ── Shared panel content ───────────────────────────────────────────────────
  const panelContent = (
    <>
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
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <button
            onClick={() => {
              const blob = new Blob([JSON.stringify(steps, null, 2)], {
                type: "application/json",
              });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = "activity-log.json";
              a.click();
              URL.revokeObjectURL(url);
            }}
            title="Download log as JSON"
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
            <LIcon name="Download" size={13} color="currentColor" />
          </button>
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
          const color = typeColor(step.type, dark, t.textDim, step.roundIndex);
          return (
            <div
              key={step.id}
              data-active={isActive ? "true" : "false"}
              onClick={() => onJumpTo(idx)}
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
                cursor: "pointer",
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
                      fontSize: isActive ? (expanded ? 13 : 11) : 11,
                      color: isActive ? t.text : t.textSub,
                      lineHeight: 1.45,
                      ...(!isActive && {
                        maxHeight: 52,
                        overflow: "hidden",
                        maskImage:
                          "linear-gradient(to bottom, black 50%, transparent 100%)",
                        WebkitMaskImage:
                          "linear-gradient(to bottom, black 50%, transparent 100%)",
                      }),
                    }}
                  >
                    <MarkdownRenderer
                      content={step.msg}
                      fontSize={isActive && expanded ? 13 : 11}
                      compact
                    />
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
    </>
  );

  // ── Expanded modal ─────────────────────────────────────────────────────────
  if (expanded) {
    return (
      <div
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 500,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: dark ? "rgba(0,0,0,0.65)" : "rgba(220,216,235,0.6)",
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
          animation: "fadeIn 0.2s ease-out",
        }}
        onClick={(e) => {
          // Close when clicking the backdrop
          if (e.target === e.currentTarget) onToggleExpand();
        }}
      >
        <div
          style={{
            width: "min(860px, 92vw)",
            height: "82vh",
            background: dark ? "rgba(8,6,16,0.97)" : "rgba(255,254,255,0.98)",
            border: `1px solid ${t.borderHi}`,
            borderRadius: 16,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            boxShadow: dark
              ? "0 24px 80px rgba(0,0,0,0.7), 0 0 0 1px rgba(139,26,47,0.2)"
              : "0 24px 80px rgba(0,0,0,0.18), 0 0 0 1px rgba(139,26,47,0.14)",
            animation: "logSlide 0.28s cubic-bezier(0.22,1,0.36,1)",
          }}
        >
          {panelContent}
        </div>
      </div>
    );
  }

  // ── Sidebar (resizable) ────────────────────────────────────────────────────
  return (
    <div
      style={{
        width: sidebarWidth,
        minWidth: sidebarWidth,
        height: "100%",
        background: dark ? "rgba(5,4,10,0.95)" : "rgba(252,250,255,0.96)",
        backdropFilter: "blur(24px)",
        borderLeft: `1px solid ${t.border}`,
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
        position: "relative",
        zIndex: 50,
        animation: "logSlide 0.3s cubic-bezier(0.22,1,0.36,1)",
      }}
    >
      {/* Resize handle — left edge */}
      <div
        onMouseDown={onResizeMouseDown}
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          bottom: 0,
          width: 5,
          cursor: "col-resize",
          zIndex: 10,
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLDivElement).style.background =
            "rgba(139,26,47,0.18)";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLDivElement).style.background = "transparent";
        }}
      />
      {panelContent}
    </div>
  );
}
