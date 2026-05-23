"use client";

import { useState, useRef, useCallback } from "react";
import { BlackboardState, ConfirmedEntry, DraftEntry } from "@/lib/types";
import { useTheme } from "@/lib/theme-context";
import { getTheme, BURG, BURG_LT, BURG_DIM } from "@/lib/theme";
import { Pin, FileText, MessageSquare, CheckCircle2, Layers, FlaskConical, GripHorizontal } from "lucide-react";
import { MarkdownRenderer } from "@/components/markdown-renderer";

interface BlackboardCanvasProps {
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
}

function entryTypeStyle(type: ConfirmedEntry["entry_type"], dark: boolean) {
  if (type === "anchor") return { icon: <Pin size={11} strokeWidth={2} color={BURG_LT} />, label: "ANCHOR", color: BURG_LT, bg: BURG_DIM, border: "rgba(139,26,47,0.3)" };
  if (type === "finding") return { icon: <CheckCircle2 size={11} strokeWidth={2} color="#3dba8c" />, label: "FINDING", color: "#3dba8c", bg: "rgba(61,186,140,0.08)", border: "rgba(61,186,140,0.25)" };
  return { icon: <FileText size={11} strokeWidth={2} color="#7b9ec0" />, label: "SYSTEM", color: "#7b9ec0", bg: "rgba(123,158,192,0.08)", border: "rgba(123,158,192,0.25)" };
}

function draftTypeColor(type: DraftEntry["entry_type"]) {
  if (type === "proposal") return BURG_LT;
  if (type === "reply") return "#7b9ec0";
  if (type === "vote") return "#b5860d";
  return "#888";
}

function DraftCard({ entry, depth = 0 }: { entry: DraftEntry; depth?: number }) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  if (!entry.is_visible) return null;

  return (
    <div style={{ marginLeft: depth * 14, marginBottom: 6 }}>
      <div
        style={{
          background: dark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.025)",
          border: `1px solid ${t.border}`,
          borderLeft: `2.5px solid ${draftTypeColor(entry.entry_type)}`,
          borderRadius: 7,
          padding: "7px 10px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
          <MessageSquare size={10} strokeWidth={2} color={draftTypeColor(entry.entry_type)} />
          <span style={{ fontSize: 9.5, fontWeight: 700, color: draftTypeColor(entry.entry_type), textTransform: "uppercase", letterSpacing: "0.06em" }}>{entry.entry_type}</span>
          <span style={{ fontSize: 9.5, color: t.textDim }}>·</span>
          <span style={{ fontSize: 9.5, color: t.textDim, fontFamily: "'JetBrains Mono', monospace" }}>{entry.author_name ?? entry.author_id.slice(0, 6)}</span>
          {entry.citation_count > 0 && (
            <span style={{ marginLeft: "auto", fontSize: 9.5, color: t.textDim }}>♡ {entry.citation_count}</span>
          )}
        </div>
        <div style={{ fontSize: 11.5, color: t.textSub, lineHeight: 1.5 }}>
          <MarkdownRenderer content={entry.content} />
        </div>
      </div>
      {entry.children.map((child) => (
        <DraftCard key={child.id} entry={child} depth={depth + 1} />
      ))}
    </div>
  );
}

export function BlackboardCanvas({ state, runId, onSeed, seeding, pos, onPosChange, width, onWidthChange, height, onHeightChange }: BlackboardCanvasProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  // Tab: "confirmed" | "draft"
  const [tab, setTab] = useState<"confirmed" | "draft">("confirmed");

  const dragStart = useRef<{ mx: number; my: number; ox: number; oy: number } | null>(null);
  const resizeStart = useRef<{ mx: number; my: number; startW: number; startH: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const onHeaderMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest("button,input,select")) return;
    e.preventDefault();
    const rect = containerRef.current!.getBoundingClientRect();
    dragStart.current = { mx: e.clientX, my: e.clientY, ox: rect.left, oy: rect.top };
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
  }, [onPosChange]);

  // Resize: drag the bottom-right corner to resize both width and height
  const onResizeMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    resizeStart.current = { mx: e.clientX, my: e.clientY, startW: width, startH: height };
    const onMove = (me: MouseEvent) => {
      if (!resizeStart.current) return;
      onWidthChange(Math.max(240, Math.min(900, resizeStart.current.startW + (me.clientX - resizeStart.current.mx))));
      onHeightChange(Math.max(180, Math.min(800, resizeStart.current.startH + (me.clientY - resizeStart.current.my))));
    };
    const onUp = () => {
      resizeStart.current = null;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [width, height, onWidthChange, onHeightChange]);

  const hasContent = state.confirmed.length > 0 || state.draft.length > 0;
  const activeThread = state.threads[0] ?? null;
  const visibleDraft = state.draft.filter((e) => e.is_visible);

  const posStyle: React.CSSProperties = pos
    ? { left: pos.x, top: pos.y }
    : { left: "50%", top: "50%", transform: "translate(-50%, -50%)" };

  const tabStyle = (active: boolean): React.CSSProperties => ({
    padding: "4px 12px",
    fontSize: 10.5,
    fontWeight: 700,
    fontFamily: "'Space Grotesk', system-ui, sans-serif",
    letterSpacing: "0.06em",
    textTransform: "uppercase",
    border: "none",
    borderRadius: 6,
    cursor: "pointer",
    background: active ? BURG : "transparent",
    color: active ? "#fff" : t.textDim,
    transition: "all 0.15s",
  });

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
        // shadow so it floats visually
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
        <span style={{ fontSize: 11, fontWeight: 800, color: BURG_LT, letterSpacing: "0.1em", textTransform: "uppercase", fontFamily: "'Space Grotesk', system-ui, sans-serif" }}>
          Blackboard
        </span>
        {activeThread && (
          <>
            <span style={{ fontSize: 10, color: "rgba(139,26,47,0.5)" }}>·</span>
            <span style={{ fontSize: 10.5, color: BURG, fontFamily: "'Space Grotesk', system-ui, sans-serif", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 120 }}>
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
                display: "flex", alignItems: "center", gap: 5,
                padding: "4px 10px",
                background: BURG, color: "#fff", border: "none", borderRadius: 6,
                cursor: seeding ? "not-allowed" : "pointer",
                fontSize: 10.5, fontWeight: 700, opacity: seeding ? 0.6 : 1,
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
              <div style={{ width: 6, height: 6, borderRadius: "50%", background: state.loading ? "#b5860d" : hasContent ? "#3dba8c" : t.textDim, boxShadow: hasContent && !state.loading ? "0 0 5px #3dba8c88" : "none" }} />
              <span style={{ fontSize: 9.5, color: t.textDim, fontFamily: "'JetBrains Mono', monospace", whiteSpace: "nowrap" }}>
                {state.loading ? "syncing…" : `${state.confirmed.length}C · ${visibleDraft.length}D`}
              </span>
            </>
          )}
        </div>
      </div>

      {/* ── Tab bar (only when there's a run) ── */}
      {runId && (
        <div
          style={{
            display: "flex",
            gap: 4,
            padding: "6px 14px",
            background: dark ? "rgba(10,8,20,0.9)" : "rgba(240,238,252,0.95)",
            border: `1px solid rgba(139,26,47,0.22)`,
            borderTop: "none",
            borderBottom: "none",
            backdropFilter: "blur(12px)",
          }}
          onMouseDown={(e) => e.stopPropagation()} // don't trigger header drag
        >
          <button style={tabStyle(tab === "confirmed")} onClick={() => setTab("confirmed")}>
            Confirmed {state.confirmed.length > 0 && `(${state.confirmed.length})`}
          </button>
          <button style={tabStyle(tab === "draft")} onClick={() => setTab("draft")}>
            Draft {visibleDraft.length > 0 && `(${visibleDraft.length})`}
          </button>
        </div>
      )}

      {/* ── Body ── */}
      <div
        style={{
          background: dark ? "rgba(6,5,12,0.88)" : "rgba(248,246,255,0.94)",
          border: `1px solid rgba(139,26,47,0.22)`,
          borderTop: runId ? "none" : undefined,
          borderRadius: runId ? "0 0 12px 12px" : "0 0 12px 12px",
          backdropFilter: "blur(16px)",
          padding: "12px 14px",
          height: height,
          overflowY: "auto",
          overflowX: "hidden",
          userSelect: "text",
        }}
        className="pscroll"
      >
        {/* No run yet */}
        {!runId && (
          <div style={{ textAlign: "center", padding: "36px 0", color: t.textDim, fontSize: 12, fontFamily: "'Space Grotesk', system-ui" }}>
            Seed a run to populate the blackboard.
          </div>
        )}

        {/* Loading */}
        {runId && state.loading && (
          <div style={{ textAlign: "center", padding: "36px 0", color: t.textDim, fontSize: 12, fontFamily: "'Space Grotesk', system-ui" }}>
            Loading blackboard…
          </div>
        )}

        {/* Error */}
        {runId && !state.loading && state.error && (
          <div style={{ textAlign: "center", padding: "16px 0", color: "#c0392b", fontSize: 12 }}>
            {state.error}
          </div>
        )}

        {/* ── CONFIRMED TAB ── */}
        {runId && !state.loading && tab === "confirmed" && (
          <>
            {state.confirmed.length === 0 ? (
              <div style={{ textAlign: "center", padding: "36px 0", color: t.textDim, fontSize: 12, fontFamily: "'Space Grotesk', system-ui" }}>
                No confirmed entries yet.
              </div>
            ) : (
              state.confirmed.map((entry) => {
                const es = entryTypeStyle(entry.entry_type, dark);
                return (
                  <div
                    key={entry.id}
                    style={{ background: es.bg, border: `1px solid ${es.border}`, borderRadius: 8, padding: "8px 11px", marginBottom: 6 }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 5 }}>
                      {es.icon}
                      <span style={{ fontSize: 9.5, fontWeight: 800, color: es.color, letterSpacing: "0.08em", textTransform: "uppercase", fontFamily: "'Space Grotesk', system-ui" }}>
                        {es.label}
                      </span>
                      {entry.entry_type !== "anchor" && (
                        <span style={{ fontSize: 9.5, color: t.textDim }}>Round {entry.round_confirmed}</span>
                      )}
                      {entry.citation_count > 0 && (
                        <span style={{ marginLeft: "auto", fontSize: 9.5, color: t.textDim }}>♡ {entry.citation_count}</span>
                      )}
                    </div>
                    <div style={{ fontSize: 12, color: t.text, lineHeight: 1.55 }}>
                      <MarkdownRenderer content={entry.content} />
                    </div>
                  </div>
                );
              })
            )}
          </>
        )}

        {/* ── DRAFT TAB ── */}
        {runId && !state.loading && tab === "draft" && (
          <>
            {visibleDraft.length === 0 ? (
              <div style={{ textAlign: "center", padding: "36px 0", color: t.textDim, fontSize: 12, fontFamily: "'Space Grotesk', system-ui" }}>
                No draft entries yet.
              </div>
            ) : (
              visibleDraft.map((entry) => (
                <DraftCard key={entry.id} entry={entry} depth={0} />
              ))
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
          <path d="M1 7L7 1M4 7L7 4M7 7L7 7" stroke="rgba(139,26,47,0.45)" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      </div>
    </div>
  );
}
