"use client";

import { useRef, useCallback } from "react";
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

export function BlackboardCanvas({ state, runId, onSeed, seeding, pos, onPosChange, width, onWidthChange }: BlackboardCanvasProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  const dragStart = useRef<{ mx: number; my: number; ox: number; oy: number } | null>(null);
  const resizeStart = useRef<{ mx: number; startW: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const onHeaderMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest("button")) return;
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

  const onResizeMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    resizeStart.current = { mx: e.clientX, startW: width };
    const onMove = (me: MouseEvent) => {
      if (!resizeStart.current) return;
      onWidthChange(Math.max(280, Math.min(720, resizeStart.current.startW + (me.clientX - resizeStart.current.mx))));
    };
    const onUp = () => {
      resizeStart.current = null;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [width, onWidthChange]);

  const hasContent = state.confirmed.length > 0 || state.draft.length > 0;
  const activeThread = state.threads[0] ?? null;

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
      }}
    >
      {/* Header bar — drag handle */}
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
            <span style={{ fontSize: 10.5, color: BURG, fontFamily: "'Space Grotesk', system-ui, sans-serif", fontWeight: 600 }}>
              {activeThread.title}
            </span>
          </>
        )}
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          {/* Seed button — only when no run yet */}
          {!runId && onSeed && (
            <button
              onClick={onSeed}
              disabled={seeding}
              style={{
                display: "flex", alignItems: "center", gap: 5,
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
              <div style={{ width: 6, height: 6, borderRadius: "50%", background: state.loading ? "#b5860d" : hasContent ? "#3dba8c" : t.textDim, boxShadow: hasContent && !state.loading ? "0 0 5px #3dba8c88" : "none" }} />
              <span style={{ fontSize: 9.5, color: t.textDim, fontFamily: "'JetBrains Mono', monospace" }}>
                {state.loading ? "syncing…" : `${state.confirmed.length} confirmed · ${state.draft.length} draft`}
              </span>
            </>
          )}
        </div>
      </div>

      {/* Body */}
      <div
        style={{
          background: dark ? "rgba(6,5,12,0.88)" : "rgba(248,246,255,0.94)",
          border: `1px solid rgba(139,26,47,0.22)`,
          borderRadius: "0 0 12px 12px",
          backdropFilter: "blur(16px)",
          boxShadow: dark
            ? "0 16px 48px rgba(0,0,0,0.5), 0 0 0 1px rgba(139,26,47,0.12)"
            : "0 16px 48px rgba(0,0,0,0.12), 0 0 0 1px rgba(139,26,47,0.08)",
          padding: "12px 14px",
          maxHeight: 460,
          overflowY: "auto",
          overflowX: "hidden",
          userSelect: "text",
        }}
        className="pscroll"
      >
        {/* No run yet */}
        {!runId && (
          <div style={{ textAlign: "center", padding: "28px 0", color: t.textDim, fontSize: 12, fontFamily: "'Space Grotesk', system-ui" }}>
            Seed a run to populate the blackboard.
          </div>
        )}

        {/* Loading */}
        {runId && state.loading && (
          <div style={{ textAlign: "center", padding: "24px 0", color: t.textDim, fontSize: 12, fontFamily: "'Space Grotesk', system-ui" }}>
            Loading blackboard…
          </div>
        )}

        {/* Error */}
        {runId && !state.loading && state.error && (
          <div style={{ textAlign: "center", padding: "16px 0", color: "#c0392b", fontSize: 12 }}>
            {state.error}
          </div>
        )}

        {/* No content yet */}
        {runId && !state.loading && !state.error && !hasContent && (
          <div style={{ textAlign: "center", padding: "24px 0", color: t.textDim, fontSize: 12, fontFamily: "'Space Grotesk', system-ui" }}>
            Awaiting first entry…
          </div>
        )}

        {/* ── CONFIRMED SECTION ── */}
        {runId && !state.loading && state.confirmed.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
              <div style={{ flex: 1, height: 1, background: `linear-gradient(to right, rgba(139,26,47,0.4), transparent)` }} />
              <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: "0.12em", textTransform: "uppercase", color: BURG, fontFamily: "'Space Grotesk', system-ui" }}>
                Confirmed
              </span>
              <div style={{ flex: 1, height: 1, background: `linear-gradient(to left, rgba(139,26,47,0.4), transparent)` }} />
            </div>
            {state.confirmed.map((entry) => {
              const style = entryTypeStyle(entry.entry_type, dark);
              return (
                <div
                  key={entry.id}
                  style={{
                    background: style.bg,
                    border: `1px solid ${style.border}`,
                    borderRadius: 8,
                    padding: "8px 11px",
                    marginBottom: 6,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 5 }}>
                    {style.icon}
                    <span style={{ fontSize: 9.5, fontWeight: 800, color: style.color, letterSpacing: "0.08em", textTransform: "uppercase", fontFamily: "'Space Grotesk', system-ui" }}>
                      {style.label}
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
            })}
          </div>
        )}

        {/* ── DRAFT SECTION ── */}
        {runId && !state.loading && state.draft.filter((e) => e.is_visible).length > 0 && (
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
              <div style={{ flex: 1, height: 1, background: `linear-gradient(to right, ${t.border}, transparent)` }} />
              <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: "0.12em", textTransform: "uppercase", color: t.textDim, fontFamily: "'Space Grotesk', system-ui" }}>
                Draft
              </span>
              <div style={{ flex: 1, height: 1, background: `linear-gradient(to left, ${t.border}, transparent)` }} />
            </div>
            {state.draft.filter((e) => e.is_visible).map((entry) => (
              <DraftCard key={entry.id} entry={entry} depth={0} />
            ))}
          </div>
        )}
      </div>

      {/* Right-edge resize handle */}
      <div
        onMouseDown={onResizeMouseDown}
        style={{
          position: "absolute",
          top: 0,
          right: -4,
          width: 8,
          bottom: 0,
          cursor: "ew-resize",
          zIndex: 30,
          borderRadius: 4,
        }}
        title="Drag to resize"
      />
    </div>
  );
}
