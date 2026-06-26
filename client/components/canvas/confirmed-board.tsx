"use client";

import { useState } from "react";
import { createPortal } from "react-dom";
import { BlackboardState } from "@/lib/types";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";
import { CheckCircle2, Maximize2, X } from "lucide-react";
import { ConfirmedCard } from "./blackboard/confirmed-card";

const GOLD = "#b5860d";

interface ConfirmedBoardProps {
  state: BlackboardState;
  /** Fixed position/size — boards are never moved or resized. */
  pos: { x: number; y: number } | null;
  width: number;
  height: number;
  zoom?: number;
  /** Filters to one thread; null/undefined shows all threads. */
  activeThreadId?: string | null;
}

export function ConfirmedBoard({
  state,
  pos,
  width,
  height,
  zoom = 1,
  activeThreadId = null,
}: ConfirmedBoardProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  const [expanded, setExpanded] = useState(false);

  const filteredConfirmed = activeThreadId
    ? state.confirmed.filter((e) => e.thread_id === activeThreadId)
    : state.confirmed;
  const activeThread =
    state.threads.find((th) => th.id === activeThreadId) ??
    state.threads[0] ??
    null;
  const hasContent = filteredConfirmed.length > 0;
  const idleMessage =
    "No confirmed entries yet — entries appear here once cited enough times.";

  const posStyle: React.CSSProperties = pos
    ? { left: pos.x, top: pos.y }
    : { left: "50%", top: "50%", transform: "translate(-50%, -50%)" };

  return (
    <div
      style={{
        position: "absolute",
        ...posStyle,
        width,
        pointerEvents: "all",
        userSelect: "none",
        zIndex: 20,
        transform: `scale(${zoom})`,
        transformOrigin: "top left",
        filter: "drop-shadow(0 8px 32px rgba(0,0,0,0.35))",
      }}
    >
      {/* ── Header (fixed — no drag handle) ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 14px",
          background: dark ? "rgba(181,134,13,0.16)" : "rgba(181,134,13,0.08)",
          border: `1px solid rgba(181,134,13,0.35)`,
          borderBottom: "none",
          borderRadius: "12px 12px 0 0",
          backdropFilter: "blur(12px)",
        }}
      >
        <CheckCircle2 size={13} strokeWidth={1.8} color={GOLD} />
        <span
          style={{
            fontSize: 11,
            fontWeight: 800,
            color: GOLD,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
          }}
        >
          Confirmed
        </span>
        {activeThread && (
          <>
            <span style={{ fontSize: 10, color: "rgba(181,134,13,0.5)" }}>
              ·
            </span>
            <span
              style={{
                fontSize: 10.5,
                color: GOLD,
                fontFamily: "'Space Grotesk', system-ui, sans-serif",
                fontWeight: 600,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                maxWidth: 120,
              }}
            >
              {activeThread.title}
            </span>
          </>
        )}
        <div
          style={{
            marginLeft: "auto",
            display: "flex",
            gap: 8,
            alignItems: "center",
          }}
        >
          <div
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: state.loading ? GOLD : hasContent ? GOLD : t.textDim,
              boxShadow:
                hasContent && !state.loading ? `0 0 5px ${GOLD}88` : "none",
            }}
          />
          <span
            style={{
              fontSize: 9.5,
              color: t.textDim,
              fontFamily: "'JetBrains Mono', monospace",
              whiteSpace: "nowrap",
            }}
          >
            {state.loading ? "syncing…" : `${filteredConfirmed.length}C`}
          </span>
          <button
            onClick={() => setExpanded(true)}
            title="Expand confirmed board"
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: "2px 4px",
              display: "flex",
              alignItems: "center",
              opacity: 0.6,
              color: GOLD,
            }}
          >
            <Maximize2 size={11} strokeWidth={2} />
          </button>
        </div>
      </div>

      {/* ── Body ── */}
      <div
        style={{
          background: dark ? "rgba(10,8,2,0.88)" : "rgba(255,253,244,0.94)",
          border: `1px solid rgba(181,134,13,0.22)`,
          borderTop: "none",
          borderRadius: "0 0 12px 12px",
          backdropFilter: "blur(16px)",
          padding: "12px 14px",
          height,
          overflowY: "auto",
          overflowX: "hidden",
          userSelect: "text",
        }}
        className="pscroll"
      >
        {state.loading && (
          <div
            style={{
              textAlign: "center",
              padding: "36px 0",
              color: t.textDim,
              fontSize: 12,
              fontFamily: "'Space Grotesk', system-ui",
            }}
          >
            Loading confirmed board…
          </div>
        )}

        {!state.loading && state.error && (
          <div
            style={{
              textAlign: "center",
              padding: "16px 0",
              color: "#c0392b",
              fontSize: 12,
            }}
          >
            {state.error}
          </div>
        )}

        {!state.loading && !state.error && (
          <>
            {filteredConfirmed.length === 0 ? (
              <div
                style={{
                  textAlign: "center",
                  padding: "36px 0",
                  color: t.textDim,
                  fontSize: 12,
                  fontFamily: "'Space Grotesk', system-ui",
                }}
              >
                {idleMessage}
              </div>
            ) : (
              filteredConfirmed.map((entry) => (
                <ConfirmedCard key={entry.id} entry={entry} />
              ))
            )}
          </>
        )}
      </div>

      {/* ── Fullscreen modal ── */}
      {expanded &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            onClick={(e) => {
              if (e.target === e.currentTarget) setExpanded(false);
            }}
            style={{
              position: "fixed",
              inset: 0,
              zIndex: 9999,
              backdropFilter: "blur(14px)",
              WebkitBackdropFilter: "blur(14px)",
              background: dark ? "rgba(0,0,0,0.6)" : "rgba(255,255,255,0.45)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <div
              style={{
                width: "min(860px, 90vw)",
                maxHeight: "85vh",
                display: "flex",
                flexDirection: "column",
                background: dark
                  ? "rgba(10,8,2,0.97)"
                  : "rgba(255,253,244,0.99)",
                border: "1px solid rgba(181,134,13,0.35)",
                borderRadius: 16,
                overflow: "hidden",
                boxShadow: "0 28px 90px rgba(0,0,0,0.5)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "12px 18px",
                  borderBottom: "1px solid rgba(181,134,13,0.2)",
                  flexShrink: 0,
                  background: dark
                    ? "rgba(181,134,13,0.12)"
                    : "rgba(181,134,13,0.06)",
                }}
              >
                <CheckCircle2 size={14} strokeWidth={1.8} color={GOLD} />
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 800,
                    color: GOLD,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    fontFamily: "'Space Grotesk', system-ui, sans-serif",
                  }}
                >
                  Confirmed
                </span>
                {activeThread && (
                  <>
                    <span
                      style={{ fontSize: 11, color: "rgba(181,134,13,0.45)" }}
                    >
                      ·
                    </span>
                    <span
                      style={{
                        fontSize: 12,
                        color: GOLD,
                        fontFamily: "'Space Grotesk', system-ui, sans-serif",
                        fontWeight: 600,
                      }}
                    >
                      {activeThread.title}
                    </span>
                  </>
                )}
                <button
                  onClick={() => setExpanded(false)}
                  style={{
                    marginLeft: "auto",
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    padding: "4px 6px",
                    display: "flex",
                    alignItems: "center",
                    color: t.textDim,
                    borderRadius: 6,
                  }}
                  title="Close"
                >
                  <X size={15} strokeWidth={2} />
                </button>
              </div>

              <div
                style={{ flex: 1, overflowY: "auto", padding: "16px 20px" }}
                className="pscroll"
              >
                {state.loading && (
                  <div
                    style={{
                      textAlign: "center",
                      padding: "60px 0",
                      color: t.textDim,
                      fontSize: 13,
                      fontFamily: "'Space Grotesk', system-ui",
                    }}
                  >
                    Loading confirmed board…
                  </div>
                )}
                {!state.loading && state.error && (
                  <div
                    style={{
                      textAlign: "center",
                      padding: "24px 0",
                      color: "#c0392b",
                      fontSize: 13,
                    }}
                  >
                    {state.error}
                  </div>
                )}
                {!state.loading && !state.error && (
                  <>
                    {filteredConfirmed.length === 0 ? (
                      <div
                        style={{
                          textAlign: "center",
                          padding: "60px 0",
                          color: t.textDim,
                          fontSize: 13,
                          fontFamily: "'Space Grotesk', system-ui",
                        }}
                      >
                        {idleMessage}
                      </div>
                    ) : (
                      filteredConfirmed.map((entry) => (
                        <ConfirmedCard key={entry.id} entry={entry} />
                      ))
                    )}
                  </>
                )}
              </div>
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}
