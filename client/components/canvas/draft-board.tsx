"use client";

import { useState, useRef, useCallback } from "react";
import { createPortal } from "react-dom";
import { BlackboardState } from "@/lib/types";
import { useTheme } from "@/lib/theme-context";
import { getTheme, BURG, BURG_LT } from "@/lib/theme";
import {
  Layers,
  FlaskConical,
  GripHorizontal,
  Maximize2,
  X,
} from "lucide-react";
import { computePromotionThreshold } from "@/lib/blackboard-utils";
import { ProposalCard } from "./blackboard/proposal-card";
import { ThreadedEntry } from "./blackboard/reply-thread";

interface DraftBoardProps {
  state: BlackboardState;
  /** null = no run yet, show seed button */
  runId: string | null;
  onSeed?: () => void;
  seeding?: boolean;
  /** Controlled position from parent (viewport px) */
  pos: { x: number; y: number } | null;
  onPosChange: (pos: { x: number; y: number }) => void;
  width: number;
  onWidthChange: (w: number) => void;
  height: number;
  onHeightChange: (h: number) => void;
  zoom?: number;
  /** Filters to one thread; null/undefined shows all threads. */
  activeThreadId?: string | null;
}

export function DraftBoard({
  state,
  runId,
  onSeed,
  seeding,
  pos,
  onPosChange,
  width,
  onWidthChange,
  height,
  onHeightChange,
  zoom = 1,
  activeThreadId = null,
}: DraftBoardProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  const [expanded, setExpanded] = useState(false);

  const dragStart = useRef<{
    mx: number;
    my: number;
    ox: number;
    oy: number;
  } | null>(null);
  const resizeStart = useRef<{
    mx: number;
    my: number;
    startW: number;
    startH: number;
  } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const onHeaderMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if ((e.target as HTMLElement).closest("button,input,select")) return;
      e.preventDefault();
      const rect = containerRef.current!.getBoundingClientRect();
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

  // Resize: drag the bottom-right corner to resize both width and height
  const onResizeMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      resizeStart.current = {
        mx: e.clientX,
        my: e.clientY,
        startW: width,
        startH: height,
      };
      const onMove = (me: MouseEvent) => {
        if (!resizeStart.current) return;
        onWidthChange(
          Math.max(
            240,
            Math.min(900, resizeStart.current.startW + (me.clientX - resizeStart.current.mx)),
          ),
        );
        onHeightChange(
          Math.max(
            180,
            Math.min(800, resizeStart.current.startH + (me.clientY - resizeStart.current.my)),
          ),
        );
      };
      const onUp = () => {
        resizeStart.current = null;
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },
    [width, height, onWidthChange, onHeightChange],
  );

  const filteredDraft = activeThreadId
    ? state.draft.filter((e) => e.thread_id === activeThreadId)
    : state.draft;
  const activeThread =
    state.threads.find((th) => th.id === activeThreadId) ?? state.threads[0] ?? null;
  const visibleDraft = filteredDraft.filter((e) => e.is_visible);
  const hasContent = visibleDraft.length > 0;
  const threshold = computePromotionThreshold(filteredDraft);
  const promotedMap = new Map(
    state.confirmed
      .filter((c) => c.source_draft_id)
      .map((c) => [c.source_draft_id as string, c.round_confirmed] as const),
  );
  const idleMessage = runId
    ? "No entries yet."
    : "No active run — type a prompt or seed test data.";

  const posStyle: React.CSSProperties = pos
    ? { left: pos.x, top: pos.y }
    : { left: "50%", top: "50%", transform: "translate(-50%, -50%)" };

  return (
    <div
      ref={containerRef}
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
      {/* ── Header / drag handle ── */}
      <div
        onMouseDown={onHeaderMouseDown}
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
          cursor: "grab",
        }}
      >
        <GripHorizontal size={11} strokeWidth={2} color={BURG_LT} style={{ opacity: 0.5, flexShrink: 0 }} />
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
            <span style={{ fontSize: 10, color: "rgba(139,26,47,0.5)" }}>·</span>
            <span
              style={{
                fontSize: 10.5,
                color: BURG,
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
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          {!runId && onSeed && (
            <button
              onClick={onSeed}
              disabled={seeding}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 5,
                padding: "4px 10px",
                background: BURG,
                color: "#fff",
                border: "none",
                borderRadius: 6,
                cursor: seeding ? "not-allowed" : "pointer",
                fontSize: 10.5,
                fontWeight: 700,
                opacity: seeding ? 0.6 : 1,
                fontFamily: "'Space Grotesk', system-ui, sans-serif",
                boxShadow: `0 2px 8px rgba(139,26,47,0.35)`,
              }}
            >
              <FlaskConical size={10} strokeWidth={2} />
              {seeding ? "Seeding…" : "Seed test data"}
            </button>
          )}
          {runId && (
            <>
              <div
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: state.loading ? "#b5860d" : hasContent ? "#3dba8c" : t.textDim,
                  boxShadow: hasContent && !state.loading ? "0 0 5px #3dba8c88" : "none",
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
                {state.loading ? "syncing…" : `${visibleDraft.length}D`}
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
        </div>
      </div>

      {/* ── Body ── */}
      <div
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
            Loading draft board…
          </div>
        )}

        {!state.loading && state.error && (
          <div style={{ textAlign: "center", padding: "16px 0", color: "#c0392b", fontSize: 12 }}>
            {state.error}
          </div>
        )}

        {!state.loading && !state.error && (
          <>
            {visibleDraft.length === 0 ? (
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
              visibleDraft.map((entry) =>
                entry.entry_type === "proposal" ? (
                  <ProposalCard key={entry.id} entry={entry} threshold={threshold} promotedMap={promotedMap} />
                ) : (
                  <ThreadedEntry
                    key={entry.id}
                    entry={entry}
                    parentContent=""
                    depth={0}
                    threshold={threshold}
                    promotedMap={promotedMap}
                  />
                ),
              )
            )}
          </>
        )}
      </div>

      {/* ── Bottom-right corner resize handle ── */}
      <div
        onMouseDown={onResizeMouseDown}
        style={{
          position: "absolute",
          bottom: 0,
          right: 0,
          width: 16,
          height: 16,
          cursor: "nwse-resize",
          zIndex: 30,
          borderRadius: "0 0 12px 0",
          background: "transparent",
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "flex-end",
          padding: 3,
        }}
        title="Drag to resize"
      >
        <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
          <path
            d="M1 7L7 1M4 7L7 4M7 7L7 7"
            stroke="rgba(139,26,47,0.45)"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
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
                background: dark ? "rgba(6,5,12,0.97)" : "rgba(248,246,255,0.99)",
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
                  background: dark ? "rgba(139,26,47,0.12)" : "rgba(139,26,47,0.06)",
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
                    <span style={{ fontSize: 11, color: "rgba(139,26,47,0.45)" }}>·</span>
                    <span
                      style={{
                        fontSize: 12,
                        color: BURG,
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

              <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px" }} className="pscroll">
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
                    Loading draft board…
                  </div>
                )}
                {!state.loading && state.error && (
                  <div style={{ textAlign: "center", padding: "24px 0", color: "#c0392b", fontSize: 13 }}>
                    {state.error}
                  </div>
                )}
                {!state.loading && !state.error && (
                  <>
                    {visibleDraft.length === 0 ? (
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
                      visibleDraft.map((entry) =>
                        entry.entry_type === "proposal" ? (
                          <ProposalCard
                            key={entry.id}
                            entry={entry}
                            threshold={threshold}
                            promotedMap={promotedMap}
                          />
                        ) : (
                          <ThreadedEntry
                            key={entry.id}
                            entry={entry}
                            parentContent=""
                            depth={0}
                            threshold={threshold}
                            promotedMap={promotedMap}
                          />
                        ),
                      )
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
