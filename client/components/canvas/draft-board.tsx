"use client";

import { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import { BlackboardState } from "@/lib/types";
import { useTheme } from "@/lib/theme-context";
import { getTheme, BURG_LT } from "@/lib/theme";
import { Layers, Maximize2, X } from "lucide-react";
import { computePromotionThreshold } from "@/lib/blackboard-utils";
import { ProposalCard } from "./blackboard/proposal-card";
import { ThreadedEntry } from "./blackboard/reply-thread";
import { ThreadFilterDropdown } from "./blackboard/thread-filter-dropdown";
import { PromptBrief } from "./blackboard/prompt-brief";

interface DraftBoardProps {
  state: BlackboardState;
  /** null = no run yet */
  runId: string | null;
  /** Fixed position/size — boards are never moved or resized. */
  pos: { x: number; y: number } | null;
  width: number;
  height: number;
  zoom?: number;
  /** Filters to one thread; null/undefined shows all threads. */
  activeThreadId?: string | null;
  /** When provided, renders the thread filter in the board header. */
  onThreadSelect?: (id: string | null) => void;
  /** Canvas agents list — used to assign stable, unique accent colours. */
  agents?: { id: string }[];
  /** Agents with a promoted contribution — always rendered gold. */
  promotedAgentIds?: Set<string>;
  /** True once the dummy / real run has fully completed. */
  done?: boolean;
}

function SkeletonCard({ dark, delay = 0 }: { dark: boolean; delay?: number }) {
  const bg = dark
    ? "linear-gradient(90deg,rgba(255,255,255,0.04) 25%,rgba(255,255,255,0.08) 50%,rgba(255,255,255,0.04) 75%)"
    : "linear-gradient(90deg,rgba(0,0,0,0.04) 25%,rgba(0,0,0,0.08) 50%,rgba(0,0,0,0.04) 75%)";
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
        background: dark ? "rgba(139,26,47,0.05)" : "rgba(139,26,47,0.03)",
        border: "1px solid rgba(139,26,47,0.1)",
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

function EmptyState({ runId, dark }: { runId: string | null; dark: boolean }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        padding: "32px 0 20px",
        gap: 8,
      }}
    >
      <Layers
        size={32}
        strokeWidth={1.2}
        color={`rgba(196,55,79,${dark ? 0.18 : 0.12})`}
      />
      <span
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: dark ? "rgba(196,55,79,0.5)" : "rgba(139,26,47,0.45)",
          fontFamily: "'Space Grotesk', system-ui",
        }}
      >
        {runId ? "Waiting for proposals…" : "No active run"}
      </span>
      <span
        style={{
          fontSize: 10.5,
          color: `rgba(${dark ? "255,255,255" : "0,0,0"},0.2)`,
          textAlign: "center",
          maxWidth: 170,
          lineHeight: 1.5,
        }}
      >
        {runId ? "Agents are deliberating" : "Type a prompt below to start"}
      </span>
    </div>
  );
}

export function DraftBoard({
  state,
  runId,
  pos,
  width,
  height,
  zoom = 1,
  activeThreadId = null,
  onThreadSelect,
  agents = [],
  promotedAgentIds,
  done = false,
}: DraftBoardProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  const [expanded, setExpanded] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [newCount, setNewCount] = useState(0);
  const prevLengthRef = useRef(0);

  const filteredDraft = activeThreadId
    ? state.draft.filter((e) => e.thread_id === activeThreadId)
    : state.draft;
  const activeThread =
    state.threads.find((th) => th.id === activeThreadId) ??
    state.threads[0] ??
    null;
  const visibleDraft = filteredDraft.filter((e) => e.is_visible);
  const hasContent = visibleDraft.length > 0;
  const threshold = computePromotionThreshold(filteredDraft);
  const promotedMap = new Map(
    state.confirmed
      .filter((c) => c.source_draft_id)
      .map((c) => [c.source_draft_id as string, c.round_confirmed] as const),
  );

  // Convergence meter: threads that have at least one confirmed entry
  const threadsWithConfirmed = new Set(state.confirmed.map((c) => c.thread_id));
  const convergingCount = state.threads.filter((th) =>
    threadsWithConfirmed.has(th.id),
  ).length;
  const totalThreads = state.threads.length;

  // Track new entries arriving while the user is scrolled up
  useEffect(() => {
    const diff = visibleDraft.length - prevLengthRef.current;
    prevLengthRef.current = visibleDraft.length;
    if (diff <= 0) return;
    const el = bodyRef.current;
    if (!el) return;
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 40;
    if (!atBottom) setNewCount((n) => n + diff);
  }, [visibleDraft.length]);

  const handleScrollToNew = () => {
    bodyRef.current?.scrollTo({
      top: bodyRef.current.scrollHeight,
      behavior: "smooth",
    });
    setNewCount(0);
  };
  const handleBodyScroll = () => {
    const el = bodyRef.current;
    if (!el) return;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 40) setNewCount(0);
  };

  // Group visible entries by round for the timeline dividers
  const roundGroups = visibleDraft.reduce<
    { round: number; entries: typeof visibleDraft }[]
  >((acc, entry) => {
    const last = acc[acc.length - 1];
    if (last && last.round === entry.round) {
      last.entries.push(entry);
    } else {
      acc.push({ round: entry.round, entries: [entry] });
    }
    return acc;
  }, []);

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
      <style>{`
        @keyframes boardShimmer {
          0%   { background-position: -400px 0; }
          100% { background-position:  400px 0; }
        }
        @keyframes boardStripe {
          0%   { left: -50%; }
          100% { left: 120%; }
        }
        @keyframes badgePulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50%       { opacity: 0.82; transform: scale(0.97); }
        }
      `}</style>

      {/* ── Header ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 14px",
          background: dark ? "rgba(139,26,47,0.18)" : "rgba(139,26,47,0.09)",
          border: `1px solid rgba(139,26,47,0.35)`,
          borderBottom: "none",
          borderRadius: "12px 12px 0 0",
          backdropFilter: "blur(12px)",
          position: "relative",
          overflow: "hidden",
        }}
      >
        <Layers size={13} strokeWidth={1.8} color={BURG_LT} />
        <span
          style={{
            fontSize: 11,
            fontWeight: 800,
            color: BURG_LT,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
          }}
        >
          Draft
        </span>
        {activeThread && (
          <>
            <span style={{ fontSize: 10, color: "rgba(139,26,47,0.5)" }}>
              ·
            </span>
            <span
              style={{
                fontSize: 10.5,
                color: BURG_LT,
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
          {/* Convergence meter — only shown when there are threads */}
          {totalThreads > 0 && runId && (
            <span
              title={`${convergingCount} of ${totalThreads} thread${
                totalThreads === 1 ? "" : "s"
              } converging`}
              style={{
                fontSize: 9.5,
                fontWeight: 700,
                fontFamily: "'JetBrains Mono', monospace",
                color: convergingCount === totalThreads ? "#3dba8c" : "#b5860d",
                whiteSpace: "nowrap",
                cursor: "default",
              }}
            >
              {convergingCount}/{totalThreads} ↑
            </span>
          )}
          {/* Thread filter — only shown when there are threads to choose from */}
          {state.threads.length > 0 && onThreadSelect && (
            <ThreadFilterDropdown
              threads={state.threads}
              activeThreadId={activeThreadId}
              onSelect={onThreadSelect}
              draftEntries={state.draft}
            />
          )}
          {runId && (
            <>
              <div
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: done
                    ? "#3dba8c"
                    : state.loading
                      ? "#b5860d"
                      : hasContent
                        ? "#3dba8c"
                        : t.textDim,
                  boxShadow: done
                    ? "0 0 6px #3dba8c"
                    : hasContent && !state.loading
                      ? "0 0 5px #3dba8c88"
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
                    : `${visibleDraft.length}D`}
              </span>
            </>
          )}
          <button
            onClick={() => setExpanded(true)}
            title="Expand draft board"
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: "2px 4px",
              display: "flex",
              alignItems: "center",
              opacity: 0.6,
              color: BURG_LT,
            }}
          >
            <Maximize2 size={11} strokeWidth={2} />
          </button>
          {/* Animated loading stripe along the header bottom edge */}
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
                  background: `linear-gradient(90deg, transparent, ${BURG_LT}cc, transparent)`,
                  animation: "boardStripe 1.3s linear infinite",
                }}
              />
            </div>
          )}
        </div>
      </div>

      {/* ── Body ── */}
      <div
        ref={bodyRef}
        onScroll={handleBodyScroll}
        style={{
          background: dark ? "rgba(6,5,12,0.88)" : "rgba(248,246,255,0.94)",
          border: `1px solid rgba(139,26,47,0.22)`,
          borderTop: "none",
          borderRadius: "0 0 12px 12px",
          backdropFilter: "blur(16px)",
          padding: "12px 14px",
          height,
          overflowY: "auto",
          overflowX: "hidden",
          userSelect: "text",
          position: "relative",
        }}
        className="pscroll"
      >
        {activeThread && <PromptBrief text={activeThread.description} />}

        {/* Skeleton: run active but no entries yet */}
        {state.loading && visibleDraft.length === 0 && (
          <>
            <SkeletonCard dark={dark} delay={0} />
            <SkeletonCard dark={dark} delay={0.15} />
            <SkeletonCard dark={dark} delay={0.3} />
          </>
        )}

        {/* Error */}
        {state.error && (
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

        {/* Styled empty state */}
        {!state.loading && !state.error && visibleDraft.length === 0 && (
          <EmptyState runId={runId} dark={dark} />
        )}

        {/* Round-grouped content */}
        {visibleDraft.length > 0 && !state.error && (
          <>
            {roundGroups.map((group, gi) => (
              <div key={group.round}>
                {gi > 0 && (
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      margin: "10px 0 8px",
                    }}
                  >
                    <div
                      style={{
                        flex: 1,
                        height: 1,
                        background: dark
                          ? "rgba(139,26,47,0.18)"
                          : "rgba(139,26,47,0.1)",
                      }}
                    />
                    <span
                      style={{
                        fontSize: 9.5,
                        color: dark
                          ? "rgba(196,55,79,0.5)"
                          : "rgba(139,26,47,0.4)",
                        fontFamily: "'JetBrains Mono', monospace",
                        whiteSpace: "nowrap",
                      }}
                    >
                      Round {group.round}
                    </span>
                    <div
                      style={{
                        flex: 1,
                        height: 1,
                        background: dark
                          ? "rgba(139,26,47,0.18)"
                          : "rgba(139,26,47,0.1)",
                      }}
                    />
                  </div>
                )}
                {group.entries.map((entry) =>
                  entry.entry_type === "proposal" ? (
                    <ProposalCard
                      key={entry.id}
                      entry={entry}
                      threshold={threshold}
                      promotedMap={promotedMap}
                      agents={agents}
                      promotedAgentIds={promotedAgentIds}
                    />
                  ) : (
                    <ThreadedEntry
                      key={entry.id}
                      entry={entry}
                      parentContent=""
                      depth={0}
                      threshold={threshold}
                      promotedMap={promotedMap}
                      agents={agents}
                      promotedAgentIds={promotedAgentIds}
                    />
                  ),
                )}
              </div>
            ))}
          </>
        )}

        {/* "New entries" scroll nudge */}
        {newCount > 0 && (
          <div
            style={{
              position: "sticky",
              bottom: 8,
              display: "flex",
              justifyContent: "center",
              pointerEvents: "none",
            }}
          >
            <button
              onClick={handleScrollToNew}
              style={{
                pointerEvents: "all",
                display: "flex",
                alignItems: "center",
                gap: 5,
                padding: "5px 14px",
                borderRadius: 100,
                border: "1px solid rgba(196,55,79,0.4)",
                background: dark
                  ? "rgba(139,26,47,0.88)"
                  : "rgba(139,26,47,0.92)",
                color: "#fff",
                fontSize: 11,
                fontWeight: 700,
                fontFamily: "'Space Grotesk', system-ui",
                cursor: "pointer",
                backdropFilter: "blur(8px)",
                boxShadow: "0 2px 12px rgba(139,26,47,0.4)",
                animation: "badgePulse 2s ease-in-out infinite",
              }}
            >
              ↓ {newCount} new
            </button>
          </div>
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
                  ? "rgba(6,5,12,0.97)"
                  : "rgba(248,246,255,0.99)",
                border: "1px solid rgba(139,26,47,0.35)",
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
                  borderBottom: "1px solid rgba(139,26,47,0.2)",
                  flexShrink: 0,
                  background: dark
                    ? "rgba(139,26,47,0.12)"
                    : "rgba(139,26,47,0.06)",
                }}
              >
                <Layers size={14} strokeWidth={1.8} color={BURG_LT} />
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 800,
                    color: BURG_LT,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    fontFamily: "'Space Grotesk', system-ui, sans-serif",
                  }}
                >
                  Draft
                </span>
                {activeThread && (
                  <>
                    <span
                      style={{ fontSize: 11, color: "rgba(139,26,47,0.45)" }}
                    >
                      ·
                    </span>
                    <span
                      style={{
                        fontSize: 12,
                        color: BURG_LT,
                        fontFamily: "'Space Grotesk', system-ui, sans-serif",
                        fontWeight: 600,
                      }}
                    >
                      {activeThread.title}
                    </span>
                  </>
                )}
                {runId && (
                  <span
                    style={{
                      marginLeft: 4,
                      fontSize: 10,
                      color: t.textDim,
                      fontFamily: "'JetBrains Mono', monospace",
                    }}
                  >
                    {runId.slice(0, 8)}
                  </span>
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
                {activeThread && <PromptBrief text={activeThread.description} />}

                {state.loading && visibleDraft.length === 0 && (
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
                {!state.loading &&
                  !state.error &&
                  visibleDraft.length === 0 && (
                    <EmptyState runId={runId} dark={dark} />
                  )}
                {visibleDraft.length > 0 && !state.error && (
                  <>
                    {roundGroups.map((group, gi) => (
                      <div key={group.round}>
                        {gi > 0 && (
                          <div
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: 8,
                              margin: "10px 0 8px",
                            }}
                          >
                            <div
                              style={{
                                flex: 1,
                                height: 1,
                                background: dark
                                  ? "rgba(139,26,47,0.18)"
                                  : "rgba(139,26,47,0.1)",
                              }}
                            />
                            <span
                              style={{
                                fontSize: 9.5,
                                color: dark
                                  ? "rgba(196,55,79,0.5)"
                                  : "rgba(139,26,47,0.4)",
                                fontFamily: "'JetBrains Mono', monospace",
                              }}
                            >
                              Round {group.round}
                            </span>
                            <div
                              style={{
                                flex: 1,
                                height: 1,
                                background: dark
                                  ? "rgba(139,26,47,0.18)"
                                  : "rgba(139,26,47,0.1)",
                              }}
                            />
                          </div>
                        )}
                        {group.entries.map((entry) =>
                          entry.entry_type === "proposal" ? (
                            <ProposalCard
                              key={entry.id}
                              entry={entry}
                              threshold={threshold}
                              promotedMap={promotedMap}
                              agents={agents}
                              promotedAgentIds={promotedAgentIds}
                            />
                          ) : (
                            <ThreadedEntry
                              key={entry.id}
                              entry={entry}
                              parentContent=""
                              depth={0}
                              threshold={threshold}
                              promotedMap={promotedMap}
                              agents={agents}
                              promotedAgentIds={promotedAgentIds}
                            />
                          ),
                        )}
                      </div>
                    ))}
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
