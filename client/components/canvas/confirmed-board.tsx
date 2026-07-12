"use client";

import { useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { BlackboardState, Ratification } from "@/lib/types";
import { useTheme } from "@/lib/theme-context";
import { getTheme, SURFACE_DARK_RGB } from "@/lib/theme";
import {
  AlertTriangle,
  CheckCircle2,
  Gavel,
  Maximize2,
  Table as TableIcon,
  X,
} from "lucide-react";
import { ConfirmedCard } from "./blackboard/confirmed-card";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { findDraftEntry } from "@/lib/blackboard-utils";
import { extractResultTable } from "@/lib/result-table";

const GOLD = "#b5860d";
const AMBER = "#c55a11";

/** Shimmering placeholder card shown while the confirmed board is syncing —
 *  mirrors the draft board's skeleton, tinted gold to match this board. */
function SkeletonCard({ dark, delay = 0 }: { dark: boolean; delay?: number }) {
  const bg = dark
    ? "linear-gradient(90deg,rgba(181,134,13,0.06) 25%,rgba(181,134,13,0.14) 50%,rgba(181,134,13,0.06) 75%)"
    : "linear-gradient(90deg,rgba(181,134,13,0.05) 25%,rgba(181,134,13,0.12) 50%,rgba(181,134,13,0.05) 75%)";
  const sh = (w: number | string, h = 9, r = 4): React.CSSProperties => ({
    width: w,
    height: h,
    borderRadius: r,
    background: bg,
    backgroundSize: "400px 100%",
    animation: `boardShimmer 1.4s ease-in-out ${delay}s infinite`,
    flexShrink: 0,
  });
  return (
    <div
      style={{
        background: dark ? "rgba(181,134,13,0.05)" : "rgba(181,134,13,0.03)",
        border: "1px solid rgba(181,134,13,0.1)",
        borderRadius: 10,
        padding: "11px 14px",
        marginBottom: 10,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 9,
        }}
      >
        <div style={sh(22, 22, 11)} />
        <div style={sh(72)} />
        <div style={{ ...sh(38, 8), marginLeft: "auto" }} />
      </div>
      <div style={sh("100%", 9)} />
      <div style={{ ...sh("85%", 9), marginTop: 5 }} />
      <div style={{ ...sh("60%", 9), marginTop: 5, marginBottom: 12 }} />
      <div style={sh(48, 8)} />
    </div>
  );
}

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
        <Gavel size={12} strokeWidth={2} color={GOLD} />
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
        <MarkdownRenderer content={text} fontSize={12.5} compact />
      </div>
    </div>
  );
}

/** The takers' vote on the synthesised answer — a ratified badge or a
 *  contested block listing each objection. Rendered on the board independently
 *  of the final-answer card so it stays visible even when synthesis returns no
 *  answer to show. */
function RatificationSummary({
  ratification,
  dark,
}: {
  ratification: Ratification;
  dark: boolean;
}) {
  if (ratification.approved) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 5,
          marginBottom: 12,
          fontSize: 10.5,
          fontWeight: 700,
          color: GOLD,
          fontFamily: "'Space Grotesk', system-ui, sans-serif",
        }}
      >
        <CheckCircle2 size={12} strokeWidth={2} />
        Ratified by {ratification.approvals}/{ratification.voters} takers
      </div>
    );
  }
  return (
    <div
      style={{
        marginBottom: 12,
        padding: "8px 11px",
        background: "rgba(197,90,17,0.09)",
        border: "1px solid rgba(197,90,17,0.3)",
        borderRadius: 8,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 5,
          fontSize: 10,
          fontWeight: 800,
          color: AMBER,
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          fontFamily: "'Space Grotesk', system-ui, sans-serif",
          marginBottom: ratification.objections.length ? 5 : 0,
        }}
      >
        <AlertTriangle size={11} strokeWidth={2.5} />
        Contested synthesis ({ratification.approvals}/{ratification.voters}{" "}
        approved)
      </div>
      {ratification.objections.length > 0 && (
        <ul
          style={{
            margin: 0,
            paddingLeft: 15,
            fontSize: 11,
            color: dark ? "rgba(255,250,235,0.82)" : "rgba(35,28,8,0.82)",
          }}
        >
          {ratification.objections.map((o, i) => {
            // Objections are formatted "AgentName: reason" server-side, so a
            // contested synthesis stays traceable to who raised each point.
            const sep = o.indexOf(": ");
            const name = sep > 0 ? o.slice(0, sep) : null;
            const reason = sep > 0 ? o.slice(sep + 2) : o;
            return (
              <li key={i} style={{ marginBottom: 4 }}>
                {name && (
                  <span
                    style={{ fontWeight: 700, color: AMBER, marginRight: 4 }}
                  >
                    {name}:
                  </span>
                )}
                <MarkdownRenderer content={reason} fontSize={11} compact />
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** The run's tabular deliverable (e.g. the order-allocation table), lifted out
 *  of the author's blackboard message and shown beneath the prose answer. */
function ResultTable({ markdown, dark }: { markdown: string; dark: boolean }) {
  return (
    <div
      style={{
        padding: "10px 13px",
        borderRadius: 10,
        background: dark ? "rgba(181,134,13,0.08)" : "rgba(181,134,13,0.05)",
        border: "1px solid rgba(181,134,13,0.28)",
        marginBottom: 12,
        overflowX: "auto",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 8,
        }}
      >
        <TableIcon size={12} strokeWidth={2} color={GOLD} />
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
          Result table
        </span>
      </div>
      <MarkdownRenderer content={markdown} fontSize={11.5} compact />
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
  /** True while a run is in flight — drives the loading skeleton. */
  running?: boolean;
  /** Brief answer synthesised from the confirmed findings at run end. */
  finalAnswer?: string | null;
  /** Takers' vote on the answer — surfaces the ratified / contested badge. */
  ratification?: Ratification | null;
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
  running = false,
  finalAnswer = null,
  ratification = null,
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
  // The run's tabular deliverable (e.g. the allocation table) lives in the
  // author's blackboard message, not the synthesised prose — surface it once
  // the run is done so it sits right under the answer.
  const resultTable = useMemo(
    () => (done ? extractResultTable(state) : null),
    [done, state],
  );

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
        @keyframes boardShimmer {
          0%   { background-position: -400px 0; }
          100% { background-position:  400px 0; }
        }
      `}</style>

      {/* ── Body ── */}
      <div
        style={{
          background: dark
            ? `rgba(${SURFACE_DARK_RGB},0.92)`
            : "rgba(255,253,244,0.94)",
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
        {running && !hasContent && !state.error && (
          <>
            <SkeletonCard dark={dark} delay={0} />
            <SkeletonCard dark={dark} delay={0.15} />
            <SkeletonCard dark={dark} delay={0.3} />
          </>
        )}

        {/* Run complete banner */}
        {done && (
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

        {done && ratification && (
          <RatificationSummary ratification={ratification} dark={dark} />
        )}

        {done && !state.loading && finalAnswer && (
          <FinalAnswer
            text={finalAnswer}
            dark={dark}
            onExpand={onShowFinalAnswer}
          />
        )}

        {done && resultTable && (
          <ResultTable markdown={resultTable} dark={dark} />
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

        {!state.error && (
          <>
            {filteredConfirmed.length === 0 && !running ? (
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
                      ? findDraftEntry(state.draft, entry.source_draft_id) ??
                        undefined
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
                  ? `rgba(${SURFACE_DARK_RGB},0.97)`
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
                {running && !hasContent && !state.error && (
                  <>
                    <SkeletonCard dark={dark} delay={0} />
                    <SkeletonCard dark={dark} delay={0.15} />
                    <SkeletonCard dark={dark} delay={0.3} />
                  </>
                )}
                {state.error && (
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
                {!state.error && (
                  <>
                    {done && ratification && (
                      <RatificationSummary
                        ratification={ratification}
                        dark={dark}
                      />
                    )}
                    {done && finalAnswer && (
                      <FinalAnswer text={finalAnswer} dark={dark} />
                    )}
                    {done && resultTable && (
                      <ResultTable markdown={resultTable} dark={dark} />
                    )}
                    {filteredConfirmed.length === 0 && !running ? (
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
                              ? findDraftEntry(
                                  state.draft,
                                  entry.source_draft_id,
                                ) ?? undefined
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
