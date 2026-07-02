"use client";

import { useState } from "react";
import { createPortal } from "react-dom";
import { BlackboardState } from "@/lib/types";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";
import { CheckCircle2, Maximize2, Sparkles, X } from "lucide-react";
import { ConfirmedCard } from "./blackboard/confirmed-card";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { findDraftEntry } from "@/lib/blackboard-utils";

const GOLD = "#b5860d";

/** The synthesised final answer, shown above the confirmed cards once the run
 *  completes. Combines the confirmed findings into one brief reply to the prompt.
 *  ``onExpand`` (when provided) re-opens the prominent completion overlay. */
function FinalAnswer({
  text,
  dark,
  onExpand,
}: {
  text: string;
  dark: boolean;
  onExpand?: () => void;
}) {
  return (
    <div
      style={{
        padding: "10px 13px",
        borderRadius: 10,
        background: dark ? "rgba(181,134,13,0.12)" : "rgba(181,134,13,0.07)",
        border: "1px solid rgba(181,134,13,0.35)",
        marginBottom: 12,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 6,
        }}
      >
        <Sparkles size={12} strokeWidth={2} color={GOLD} />
        <span
          style={{
            fontSize: 10,
            fontWeight: 800,
            color: GOLD,
            letterSpacing: "0.09em",
            textTransform: "uppercase",
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
          }}
        >
          Final answer
        </span>
        {onExpand && (
          <button
            onClick={onExpand}
            title="View full answer"
            style={{
              marginLeft: "auto",
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: "2px 4px",
              display: "flex",
              alignItems: "center",
              opacity: 0.65,
              color: GOLD,
            }}
          >
            <Maximize2 size={11} strokeWidth={2} />
          </button>
        )}
      </div>
      <div
        style={{
          fontSize: 12.5,
          lineHeight: 1.55,
          color: dark ? "rgba(255,250,235,0.92)" : "rgba(35,28,8,0.92)",
        }}
      >
        <MarkdownRenderer content={text} />
      </div>
    </div>
  );
}

interface ConfirmedBoardProps {
  state: BlackboardState;
  /** Fixed position/size — boards are never moved or resized. */
  pos: { x: number; y: number } | null;
  width: number;
  height: number;
  zoom?: number;
  /** Filters to one thread; null/undefined shows all threads. */
  activeThreadId?: string | null;
  /** True once the run has fully completed — turns the header dot solid green. */
  done?: boolean;
  /** Brief answer synthesised from the confirmed findings at run end. */
  finalAnswer?: string | null;
  /** Re-opens the prominent completion overlay from the in-board answer card. */
  onShowFinalAnswer?: () => void;
  /** Canvas agents list — used to resolve each card's author avatar color. */
  agents?: { id: string }[];
  /** Agents with a promoted contribution — always rendered gold. */
  promotedAgentIds?: Set<string>;
}

export function ConfirmedBoard({
  state,
  pos,
  width,
  height,
  zoom = 1,
  activeThreadId = null,
  done = false,
  finalAnswer = null,
  onShowFinalAnswer,
  agents = [],
  promotedAgentIds,
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
      {/* ── Header ── */}
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
          position: "relative",
          overflow: "hidden",
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
              background: done
                ? "#3dba8c"
                : state.loading
                  ? GOLD
                  : hasContent
                    ? GOLD
                    : t.textDim,
              boxShadow: done
                ? "0 0 6px #3dba8c"
                : hasContent && !state.loading
                  ? `0 0 5px ${GOLD}88`
                  : "none",
              transition: "background 0.5s, box-shadow 0.5s",
            }}
          />
          <span
            style={{
              fontSize: 9.5,
              color: done ? "#3dba8c" : t.textDim,
              fontFamily: "'JetBrains Mono', monospace",
              whiteSpace: "nowrap",
              fontWeight: done ? 700 : 400,
            }}
          >
            {done
              ? "done"
              : state.loading
                ? "syncing…"
                : `${filteredConfirmed.length}C`}
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
              color: done ? "#3dba8c" : GOLD,
            }}
          >
            <Maximize2 size={11} strokeWidth={2} />
          </button>
          {state.loading && (
            <div
              style={{
                position: "absolute",
                bottom: 0,
                left: 0,
                right: 0,
                height: 2,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  position: "absolute",
                  top: 0,
                  height: "100%",
                  width: "45%",
                  background: `linear-gradient(90deg, transparent, ${GOLD}cc, transparent)`,
                  animation: "boardStripe 1.3s linear infinite",
                }}
              />
            </div>
          )}
        </div>
      </div>

      <style>{`
        @keyframes boardStripe {
          0%   { left: -50%; }
          100% { left: 120%; }
        }
      `}</style>

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

        {/* Run complete banner */}
        {done && !state.loading && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 7,
              padding: "6px 12px",
              borderRadius: 8,
              background: dark
                ? "rgba(61,186,140,0.12)"
                : "rgba(61,186,140,0.08)",
              border: "1px solid rgba(61,186,140,0.35)",
              marginBottom: 10,
            }}
          >
            <CheckCircle2 size={13} strokeWidth={2} color="#3dba8c" />
            <span
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: "#3dba8c",
                fontFamily: "'Space Grotesk', system-ui, sans-serif",
              }}
            >
              Run complete
            </span>
            <span
              style={{
                fontSize: 10,
                color: dark ? "rgba(61,186,140,0.6)" : "rgba(30,120,90,0.6)",
                marginLeft: 2,
              }}
            >
              · {state.confirmed.length} entr
              {state.confirmed.length === 1 ? "y" : "ies"} confirmed
            </span>
          </div>
        )}

        {done && !state.loading && finalAnswer && (
          <FinalAnswer
            text={finalAnswer}
            dark={dark}
            onExpand={onShowFinalAnswer}
          />
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
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  padding: "32px 0 20px",
                  gap: 8,
                }}
              >
                <CheckCircle2
                  size={32}
                  strokeWidth={1.2}
                  color={`rgba(181,134,13,${dark ? 0.2 : 0.15})`}
                />
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 600,
                    color: `rgba(181,134,13,${dark ? 0.5 : 0.45})`,
                    fontFamily: "'Space Grotesk', system-ui",
                  }}
                >
                  Waiting for consensus…
                </span>
                <span
                  style={{
                    fontSize: 10.5,
                    color: `rgba(${dark ? "255,255,255" : "0,0,0"},0.2)`,
                    textAlign: "center",
                    maxWidth: 175,
                    lineHeight: 1.5,
                  }}
                >
                  Entries promoted here once cited enough times.
                </span>
              </div>
            ) : (
              filteredConfirmed.map((entry) => (
                <ConfirmedCard
                  key={entry.id}
                  entry={entry}
                  source={
                    entry.source_draft_id
                      ? (findDraftEntry(state.draft, entry.source_draft_id) ??
                        undefined)
                      : undefined
                  }
                  agents={agents}
                  promotedAgentIds={promotedAgentIds}
                />
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
                    {done && finalAnswer && (
                      <FinalAnswer text={finalAnswer} dark={dark} />
                    )}
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
                        <ConfirmedCard
                          key={entry.id}
                          entry={entry}
                          source={
                            entry.source_draft_id
                              ? (findDraftEntry(
                                  state.draft,
                                  entry.source_draft_id,
                                ) ?? undefined)
                              : undefined
                          }
                          agents={agents}
                          promotedAgentIds={promotedAgentIds}
                        />
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
