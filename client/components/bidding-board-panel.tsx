"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { BURG, BURG_GLOW, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import { LIcon } from "@/lib/icons";
import { SimStep } from "@/lib/types";
import {
  BoardContribution,
  BoardGap,
  useBiddingBoard,
} from "@/hooks/useBiddingBoard";

const MIN_W = 360;
const MIN_H = 280;

interface BiddingBoardPanelProps {
  steps: SimStep[];
  onClose: () => void;
  /** Current canvas zoom — used to convert screen-space drag/resize deltas
   *  to world-space deltas when the panel lives inside the .ctf world
   *  transform. */
  zoom?: number;
}

interface Edge {
  id: string;
  d: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export function BiddingBoardPanel({
  steps,
  onClose,
  zoom = 1,
}: BiddingBoardPanelProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const state = useBiddingBoard(steps);

  const counts = useMemo(() => {
    const uncovered = state.gaps.filter(
      (g) => g.coveredByContributionIds.length === 0,
    ).length;
    return {
      gaps: state.gaps.length,
      uncovered,
      contributions: state.contributions.length,
    };
  }, [state.gaps, state.contributions]);

  // Right column: covered contributions first (shorter, tidier edges), then
  // standalone findings.
  const orderedContribs = useMemo(() => {
    const covered = state.contributions.filter(
      (c) => c.coversGapIds.length > 0,
    );
    const standalone = state.contributions.filter(
      (c) => c.coversGapIds.length === 0,
    );
    return [...covered, ...standalone];
  }, [state.contributions]);

  // gap → contribution links to draw as edges.
  const links = useMemo(() => {
    const out: { gapId: string; contribId: string }[] = [];
    for (const g of state.gaps) {
      for (const cid of g.coveredByContributionIds) {
        out.push({ gapId: g.id, contribId: cid });
      }
    }
    return out;
  }, [state.gaps]);

  // ── click-to-highlight a node's connections ──────────────────────────────
  const [selected, setSelected] = useState<{
    kind: "gap" | "con";
    id: string;
  } | null>(null);

  const toggleSelect = useCallback((kind: "gap" | "con", id: string) => {
    setSelected((prev) =>
      prev && prev.kind === kind && prev.id === id ? null : { kind, id },
    );
  }, []);

  // Node keys (`gap:id` / `con:id`) and edge ids connected to the selection.
  // null ⇒ nothing selected, so everything renders at full strength.
  const highlight = useMemo(() => {
    if (!selected) return null;
    const nodeKeys = new Set<string>();
    const edgeIds = new Set<string>();
    if (selected.kind === "gap") {
      const g = state.gaps.find((x) => x.id === selected.id);
      if (!g) return null;
      nodeKeys.add(`gap:${g.id}`);
      for (const cid of g.coveredByContributionIds) {
        nodeKeys.add(`con:${cid}`);
        edgeIds.add(`${g.id}->${cid}`);
      }
    } else {
      const c = state.contributions.find((x) => x.id === selected.id);
      if (!c) return null;
      nodeKeys.add(`con:${c.id}`);
      for (const gid of c.coversGapIds) {
        nodeKeys.add(`gap:${gid}`);
        edgeIds.add(`${gid}->${c.id}`);
      }
    }
    return { nodeKeys, edgeIds };
  }, [selected, state.gaps, state.contributions]);

  // ── post-it measurement + edge geometry ─────────────────────────────────
  const innerRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef<Map<string, HTMLElement>>(new Map());
  const [edges, setEdges] = useState<Edge[]>([]);

  const setNodeRef = useCallback(
    (key: string) => (el: HTMLDivElement | null) => {
      if (el) nodeRefs.current.set(key, el);
      else nodeRefs.current.delete(key);
    },
    [],
  );

  const recompute = useCallback(() => {
    const inner = innerRef.current;
    if (!inner) return;
    const ir = inner.getBoundingClientRect();
    const next: Edge[] = [];
    for (const { gapId, contribId } of links) {
      const ge = nodeRefs.current.get(`gap:${gapId}`);
      const ce = nodeRefs.current.get(`con:${contribId}`);
      if (!ge || !ce) continue;
      const gr = ge.getBoundingClientRect();
      const cr = ce.getBoundingClientRect();
      // getBoundingClientRect is in screen px (post-zoom); divide deltas by
      // zoom to land in the inner element's local coordinate space, which is
      // what the SVG path uses.
      const x1 = (gr.right - ir.left) / zoom;
      const y1 = (gr.top - ir.top + gr.height / 2) / zoom;
      const x2 = (cr.left - ir.left) / zoom;
      const y2 = (cr.top - ir.top + cr.height / 2) / zoom;
      const mx = (x1 + x2) / 2;
      const d = `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;
      next.push({ id: `${gapId}->${contribId}`, d, x1, y1, x2, y2 });
    }
    setEdges((prev) => {
      if (
        prev.length === next.length &&
        prev.every((e, i) => e.id === next[i].id && e.d === next[i].d)
      ) {
        return prev;
      }
      return next;
    });
  }, [links, zoom]);

  useLayoutEffect(() => {
    recompute();
  }, [recompute, state.gaps, state.contributions, dark]);

  // Reflow on any size change of the board or its post-its (text wrapping,
  // resize, streaming new notes in).
  useEffect(() => {
    const inner = innerRef.current;
    if (!inner) return;
    const ro = new ResizeObserver(() => recompute());
    ro.observe(inner);
    nodeRefs.current.forEach((el) => ro.observe(el));
    return () => ro.disconnect();
  }, [recompute, state.gaps, state.contributions]);

  // ── drag / resize (world-space coords inside canvas .ctf) ───────────────
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const [size, setSize] = useState({ w: 560, h: 520 });
  const wrapRef = useRef<HTMLDivElement>(null);

  // Recompute edges when the panel itself is resized.
  useLayoutEffect(() => {
    recompute();
  }, [recompute, size]);

  const capturePos = useCallback((): { x: number; y: number } => {
    const el = wrapRef.current;
    if (!el) return { x: 0, y: 0 };
    return { x: el.offsetLeft - size.w / 2, y: el.offsetTop - size.h / 2 };
  }, [size]);

  type DragState = { sx: number; sy: number; px: number; py: number };
  type ResizeState = {
    sx: number;
    sy: number;
    sw: number;
    sh: number;
    px: number;
    py: number;
    dir: string;
  };
  const dragRef = useRef<DragState | null>(null);
  const resizeRef = useRef<ResizeState | null>(null);

  // The canvas attaches a non-passive `wheel` listener that preventDefaults to
  // zoom. Since this panel lives inside the canvas subtree, wheel events bubble
  // up and zoom the canvas instead of scrolling our list. A React onWheel can't
  // stop it (the canvas's native listener sits below React's root delegation and
  // fires first), so stop propagation natively at the wrapper — the browser
  // still scrolls the overflow container since we don't preventDefault.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const stop = (e: WheelEvent) => e.stopPropagation();
    el.addEventListener("wheel", stop, { passive: true });
    return () => el.removeEventListener("wheel", stop);
  }, []);

  const onHeaderMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if ((e.target as HTMLElement).closest("button")) return;
      e.preventDefault();
      e.stopPropagation();
      const p = pos ?? capturePos();
      if (!pos) setPos(p);
      dragRef.current = { sx: e.clientX, sy: e.clientY, px: p.x, py: p.y };
      document.body.style.cursor = "grabbing";

      const onMove = (ev: MouseEvent) => {
        if (!dragRef.current) return;
        setPos({
          x: dragRef.current.px + (ev.clientX - dragRef.current.sx) / zoom,
          y: dragRef.current.py + (ev.clientY - dragRef.current.sy) / zoom,
        });
      };
      const onUp = () => {
        dragRef.current = null;
        document.body.style.cursor = "";
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [pos, capturePos, zoom],
  );

  const onResizeMouseDown = useCallback(
    (e: React.MouseEvent, dir: string) => {
      e.preventDefault();
      e.stopPropagation();
      const p = pos ?? capturePos();
      if (!pos) setPos(p);
      resizeRef.current = {
        sx: e.clientX,
        sy: e.clientY,
        sw: size.w,
        sh: size.h,
        px: p.x,
        py: p.y,
        dir,
      };
      const cursors: Record<string, string> = {
        e: "e-resize",
        s: "s-resize",
        se: "se-resize",
        sw: "sw-resize",
      };
      document.body.style.cursor = cursors[dir] ?? "nwse-resize";

      const onMove = (ev: MouseEvent) => {
        const r = resizeRef.current;
        if (!r) return;
        const dx = (ev.clientX - r.sx) / zoom;
        const dy = (ev.clientY - r.sy) / zoom;
        let nw = r.sw,
          nh = r.sh,
          nx = r.px;
        if (r.dir.includes("e")) nw = Math.max(MIN_W, r.sw + dx);
        if (r.dir.includes("s")) nh = Math.max(MIN_H, r.sh + dy);
        if (r.dir.includes("w")) {
          nw = Math.max(MIN_W, r.sw - dx);
          nx = r.px + r.sw - nw;
        }
        setSize({ w: nw, h: nh });
        setPos({ x: nx, y: r.py });
      };
      const onUp = () => {
        resizeRef.current = null;
        document.body.style.cursor = "";
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [pos, size, capturePos, zoom],
  );

  const resizeHandle = (dir: string, style: React.CSSProperties) => (
    <div
      style={{ position: "absolute", zIndex: 10, ...style }}
      onMouseDown={(e) => onResizeMouseDown(e, dir)}
    />
  );

  const edgeColor = dark ? "rgba(196,55,79,0.7)" : "rgba(139,26,47,0.55)";

  return (
    <div
      ref={wrapRef}
      style={{
        position: "absolute",
        zIndex: 200,
        width: size.w,
        height: size.h,
        ...(pos === null
          ? { top: "50%", left: "50%", transform: "translate(-50%, -50%)" }
          : { top: pos.y, left: pos.x, transform: "none" }),
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: dark ? "rgba(8,6,16,0.97)" : "rgba(250,247,240,0.98)",
          backdropFilter: "blur(28px)",
          WebkitBackdropFilter: "blur(28px)",
          border: `1px solid ${t.borderHi}`,
          borderRadius: 16,
          boxShadow: dark
            ? "0 0 0 1px rgba(139,26,47,0.18), 0 18px 56px rgba(0,0,0,0.6)"
            : "0 0 0 1px rgba(139,26,47,0.10), 0 12px 40px rgba(0,0,0,0.12)",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <Header
          t={t}
          dark={dark}
          counts={counts}
          finalized={state.finalized}
          onClose={onClose}
          onHeaderMouseDown={onHeaderMouseDown}
        />

        <div
          className="pscroll"
          style={{
            padding: "14px 18px 20px",
            overflow: "auto",
            flex: 1,
            minHeight: 0,
          }}
        >
          {!state.hasData ? (
            <EmptyState t={t} />
          ) : (
            <div
              ref={innerRef}
              onClick={() => setSelected(null)}
              style={{
                position: "relative",
                display: "flex",
                gap: 40,
                alignItems: "flex-start",
                minWidth: "min-content",
              }}
            >
              {/* Edge layer — sits under the post-its, spans the full board. */}
              <svg
                style={{
                  position: "absolute",
                  inset: 0,
                  width: "100%",
                  height: "100%",
                  pointerEvents: "none",
                  overflow: "visible",
                  zIndex: 1,
                }}
              >
                {edges.map((e) => {
                  const dimmed =
                    highlight !== null && !highlight.edgeIds.has(e.id);
                  return (
                    <g
                      key={e.id}
                      style={{
                        opacity: dimmed ? 0.1 : 1,
                        transition: "opacity 0.15s",
                      }}
                    >
                      <path
                        d={e.d}
                        fill="none"
                        stroke={edgeColor}
                        strokeWidth={highlight !== null && !dimmed ? 2.6 : 1.8}
                      />
                      <circle cx={e.x1} cy={e.y1} r={3} fill={edgeColor} />
                      <circle cx={e.x2} cy={e.y2} r={3} fill={edgeColor} />
                    </g>
                  );
                })}
              </svg>

              {/* Gaps column */}
              <Column
                title="Gaps"
                icon="ClipboardList"
                count={state.gaps.length}
                t={t}
              >
                {state.gaps.map((g, i) => (
                  <PostIt
                    key={g.id}
                    ref={setNodeRef(`gap:${g.id}`)}
                    rotate={i % 2 ? 0.6 : -0.6}
                    dim={
                      highlight !== null &&
                      !highlight.nodeKeys.has(`gap:${g.id}`)
                    }
                    selected={selected?.kind === "gap" && selected.id === g.id}
                    onSelect={() => toggleSelect("gap", g.id)}
                  >
                    <GapNote gap={g} dark={dark} />
                  </PostIt>
                ))}
                {state.gaps.length === 0 && (
                  <ColumnEmpty t={t} text="No gaps posted." />
                )}
              </Column>

              {/* Contributions column */}
              <Column
                title="Contributions"
                icon="MessageSquare"
                count={orderedContribs.length}
                t={t}
              >
                {orderedContribs.map((c, i) => (
                  <PostIt
                    key={c.id}
                    ref={setNodeRef(`con:${c.id}`)}
                    rotate={i % 2 ? -0.6 : 0.6}
                    dim={
                      highlight !== null &&
                      !highlight.nodeKeys.has(`con:${c.id}`)
                    }
                    selected={selected?.kind === "con" && selected.id === c.id}
                    onSelect={() => toggleSelect("con", c.id)}
                  >
                    <ContributionNote contribution={c} dark={dark} />
                  </PostIt>
                ))}
                {orderedContribs.length === 0 && (
                  <ColumnEmpty t={t} text="No contributions yet." />
                )}
              </Column>
            </div>
          )}
        </div>
      </div>

      {/* Resize handles — kept flush-outside the right/bottom border so they
          never overlap the scrollable content or its scrollbar track. */}
      {resizeHandle("e", {
        right: -8,
        top: 10,
        bottom: 14,
        width: 8,
        cursor: "e-resize",
      })}
      {resizeHandle("s", {
        left: 14,
        right: 14,
        bottom: -8,
        height: 8,
        cursor: "s-resize",
      })}
      {resizeHandle("se", {
        right: -8,
        bottom: -8,
        width: 16,
        height: 16,
        cursor: "se-resize",
      })}
      {resizeHandle("sw", {
        left: -8,
        bottom: -8,
        width: 16,
        height: 16,
        cursor: "sw-resize",
      })}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────

function Header({
  t,
  dark,
  counts,
  finalized,
  onClose,
  onHeaderMouseDown,
}: {
  t: ReturnType<typeof getTheme>;
  dark: boolean;
  counts: { gaps: number; uncovered: number; contributions: number };
  finalized: boolean;
  onClose: () => void;
  onHeaderMouseDown: (e: React.MouseEvent) => void;
}) {
  return (
    <div
      onMouseDown={onHeaderMouseDown}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "12px 16px 10px",
        borderBottom: `1px solid ${t.border}`,
        cursor: "grab",
        userSelect: "none",
        flexShrink: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
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
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            color: t.text,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          Bidding Board
        </span>
        {finalized && (
          <span
            title="Selection finalized"
            style={{
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: 0.5,
              textTransform: "uppercase",
              color: dark ? "#4A9A6A" : "#1A5A3A",
              border: `1px solid ${
                dark ? "rgba(74,154,106,0.4)" : "rgba(26,90,58,0.35)"
              }`,
              borderRadius: 4,
              padding: "1px 6px",
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            Finalized
          </span>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <StatChip label="gaps" value={counts.gaps} t={t} />
        <StatChip
          label="uncovered"
          value={counts.uncovered}
          t={t}
          accent={counts.uncovered > 0 ? "warn" : undefined}
        />
        <StatChip label="contribs" value={counts.contributions} t={t} />
        <button
          onClick={onClose}
          aria-label="Close bidding board"
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
    </div>
  );
}

function StatChip({
  label,
  value,
  t,
  accent,
}: {
  label: string;
  value: number;
  t: ReturnType<typeof getTheme>;
  accent?: "warn";
}) {
  const color = accent === "warn" && value > 0 ? "#C98A35" : t.textSub;
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: 4,
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      <span style={{ fontSize: 13, fontWeight: 700, color }}>{value}</span>
      <span
        style={{
          fontSize: 9,
          letterSpacing: 0.6,
          textTransform: "uppercase",
          color: t.textDim,
        }}
      >
        {label}
      </span>
    </div>
  );
}

function EmptyState({ t }: { t: ReturnType<typeof getTheme> }) {
  return (
    <div
      style={{
        padding: "26px 8px",
        textAlign: "center",
        color: t.textDim,
        fontSize: 12,
        lineHeight: 1.5,
        fontStyle: "italic",
      }}
    >
      No bidding activity yet. Gaps and contributions will appear here as agents
      post bids and resolve matches.
    </div>
  );
}

function Column({
  title,
  icon,
  count,
  t,
  children,
}: {
  title: string;
  icon: string;
  count: number;
  t: ReturnType<typeof getTheme>;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        flex: "1 1 0",
        minWidth: 180,
        display: "flex",
        flexDirection: "column",
        gap: 18,
        position: "relative",
        zIndex: 2,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 7,
          paddingBottom: 2,
        }}
      >
        <LIcon name={icon} size={12} color={BURG} />
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: 1.2,
            textTransform: "uppercase",
            color: t.textSub,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {title}
        </span>
        <span
          style={{
            fontSize: 10,
            fontWeight: 600,
            color: t.textDim,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          · {count}
        </span>
      </div>
      {children}
    </div>
  );
}

function ColumnEmpty({
  t,
  text,
}: {
  t: ReturnType<typeof getTheme>;
  text: string;
}) {
  return (
    <div
      style={{
        fontSize: 11,
        color: t.textDim,
        fontStyle: "italic",
        padding: "4px 2px",
      }}
    >
      {text}
    </div>
  );
}

/** A sticky-note wrapper: holds the measured DOM node for edge anchoring and
 *  applies a slight rotation for the hand-placed feel. */
const PostIt = forwardRef<
  HTMLDivElement,
  {
    rotate?: number;
    children: React.ReactNode;
    dim?: boolean;
    selected?: boolean;
    onSelect?: () => void;
  }
>(function PostIt(
  { rotate = 0, children, dim = false, selected = false, onSelect },
  ref,
) {
  return (
    <div
      ref={ref}
      onClick={
        onSelect
          ? (e) => {
              e.stopPropagation();
              onSelect();
            }
          : undefined
      }
      style={{
        transform: `rotate(${rotate}deg)`,
        transition: "transform 0.15s, opacity 0.15s, box-shadow 0.15s",
        opacity: dim ? 0.25 : 1,
        cursor: onSelect ? "pointer" : "default",
        borderRadius: 4,
        boxShadow: selected
          ? `0 0 0 2px ${BURG}, 0 0 12px ${BURG_GLOW}`
          : "none",
      }}
    >
      {children}
    </div>
  );
});

function noteColors(
  kind: "gap-uncovered" | "gap-covered" | "bid" | "match",
  dark: boolean,
): { bg: string; border: string; tape: string } {
  if (dark) {
    switch (kind) {
      case "gap-uncovered":
        return {
          bg: "rgba(192,57,43,0.16)",
          border: "rgba(192,57,43,0.4)",
          tape: "rgba(255,255,255,0.08)",
        };
      case "gap-covered":
        return {
          bg: "rgba(201,138,53,0.16)",
          border: "rgba(201,138,53,0.4)",
          tape: "rgba(255,255,255,0.08)",
        };
      case "bid":
        return {
          bg: "rgba(122,122,204,0.16)",
          border: "rgba(122,122,204,0.4)",
          tape: "rgba(255,255,255,0.08)",
        };
      case "match":
        return {
          bg: "rgba(74,154,106,0.16)",
          border: "rgba(74,154,106,0.4)",
          tape: "rgba(255,255,255,0.08)",
        };
    }
  }
  switch (kind) {
    case "gap-uncovered":
      return {
        bg: "#FBE3DF",
        border: "#E7B6AD",
        tape: "rgba(255,255,255,0.6)",
      };
    case "gap-covered":
      return {
        bg: "#FFF3C4",
        border: "#E8D88A",
        tape: "rgba(255,255,255,0.6)",
      };
    case "bid":
      return {
        bg: "#E5ECFF",
        border: "#BCC8EE",
        tape: "rgba(255,255,255,0.6)",
      };
    case "match":
      return {
        bg: "#DEF3E6",
        border: "#AFD8BE",
        tape: "rgba(255,255,255,0.6)",
      };
  }
}

function Paper({
  colors,
  dark,
  children,
}: {
  colors: { bg: string; border: string; tape: string };
  dark: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        position: "relative",
        background: colors.bg,
        border: `1px solid ${colors.border}`,
        borderRadius: 4,
        padding: "12px 12px 11px",
        boxShadow: dark
          ? "2px 5px 14px rgba(0,0,0,0.5)"
          : "2px 4px 10px rgba(0,0,0,0.16)",
      }}
    >
      {/* tape strip */}
      <div
        style={{
          position: "absolute",
          top: -7,
          left: "50%",
          transform: "translateX(-50%) rotate(-1.5deg)",
          width: 44,
          height: 14,
          background: colors.tape,
          border: `1px solid ${colors.border}`,
          borderRadius: 1,
        }}
      />
      {children}
    </div>
  );
}

function GapNote({ gap, dark }: { gap: BoardGap; dark: boolean }) {
  const isCovered = gap.coveredByContributionIds.length > 0;
  const isUncovered =
    gap.finalUncovered === true || (gap.finalUncovered === null && !isCovered);
  const colors = noteColors(
    isUncovered ? "gap-uncovered" : "gap-covered",
    dark,
  );
  const ink = dark ? "#F0ECF5" : "#2A2420";
  const inkSub = dark ? "rgba(240,236,245,0.62)" : "rgba(42,36,32,0.6)";

  return (
    <Paper colors={colors} dark={dark}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 5,
          marginTop: 2,
          flexWrap: "wrap",
        }}
      >
        <span
          style={{
            fontSize: 9.5,
            fontWeight: 700,
            letterSpacing: 0.4,
            textTransform: "uppercase",
            color: dark ? "#C98A35" : "#9A5B05",
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {gap.postedByName}
        </span>
        <span style={{ marginLeft: "auto" }}>
          <StatusBadge
            covered={isCovered}
            uncovered={isUncovered}
            dark={dark}
          />
        </span>
      </div>
      <div
        style={{
          fontSize: 12.5,
          color: ink,
          fontWeight: 600,
          lineHeight: 1.4,
          marginBottom: gap.reason ? 4 : 0,
        }}
      >
        {gap.expects || "(no expectation given)"}
      </div>
      {gap.reason && (
        <div style={{ fontSize: 10.5, color: inkSub, lineHeight: 1.4 }}>
          {gap.reason}
        </div>
      )}
    </Paper>
  );
}

function ContributionNote({
  contribution,
  dark,
}: {
  contribution: BoardContribution;
  dark: boolean;
}) {
  const colors = noteColors(contribution.source, dark);
  const ink = dark ? "#F0ECF5" : "#2A2420";
  const inkSub = dark ? "rgba(240,236,245,0.55)" : "rgba(42,36,32,0.55)";
  const linked = contribution.coversGapIds.length > 0;

  return (
    <Paper colors={colors} dark={dark}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 5,
          marginTop: 2,
          flexWrap: "wrap",
        }}
      >
        <span
          style={{
            fontSize: 9.5,
            fontWeight: 700,
            color: ink,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {contribution.agentName}
        </span>
        <SourceTag source={contribution.source} dark={dark} />
        {!linked && (
          <span
            title="Not tied to any posted gap"
            style={{
              fontSize: 8.5,
              fontWeight: 600,
              letterSpacing: 0.4,
              textTransform: "uppercase",
              color: inkSub,
              marginLeft: "auto",
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            standalone
          </span>
        )}
      </div>
      <div style={{ fontSize: 12.5, color: ink, lineHeight: 1.4 }}>
        {contribution.data}
      </div>
      {contribution.citation && (
        <div
          style={{
            fontSize: 10,
            color: inkSub,
            marginTop: 4,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {contribution.citation}
        </div>
      )}
    </Paper>
  );
}

function StatusBadge({
  covered,
  uncovered,
  dark,
}: {
  covered: boolean;
  uncovered: boolean;
  dark: boolean;
}) {
  const cfg = uncovered
    ? {
        label: "Uncovered",
        color: "#C0392B",
        border: dark ? "rgba(192,57,43,0.5)" : "rgba(192,57,43,0.4)",
      }
    : covered
      ? {
          label: "Covered",
          color: dark ? "#5BB585" : "#1A5A3A",
          border: dark ? "rgba(74,154,106,0.5)" : "rgba(26,90,58,0.4)",
        }
      : {
          label: "Open",
          color: dark ? "#C98A35" : "#9A5B05",
          border: dark ? "rgba(201,138,53,0.5)" : "rgba(154,91,5,0.4)",
        };
  return (
    <span
      style={{
        fontSize: 8.5,
        fontWeight: 700,
        letterSpacing: 0.5,
        textTransform: "uppercase",
        color: cfg.color,
        border: `1px solid ${cfg.border}`,
        borderRadius: 4,
        padding: "1px 6px",
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      {cfg.label}
    </span>
  );
}

function SourceTag({
  source,
  dark,
}: {
  source: "bid" | "match";
  dark: boolean;
}) {
  const isMatch = source === "match";
  const color = isMatch
    ? dark
      ? "#5BB585"
      : "#1A5A3A"
    : dark
      ? "#9BA0E0"
      : "#4444AA";
  const border = isMatch
    ? dark
      ? "rgba(74,154,106,0.5)"
      : "rgba(26,90,58,0.4)"
    : dark
      ? "rgba(122,122,204,0.5)"
      : "rgba(68,68,170,0.4)";
  return (
    <span
      style={{
        fontSize: 8.5,
        fontWeight: 700,
        letterSpacing: 0.5,
        textTransform: "uppercase",
        color,
        border: `1px solid ${border}`,
        borderRadius: 3,
        padding: "0px 5px",
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      {source}
    </span>
  );
}
