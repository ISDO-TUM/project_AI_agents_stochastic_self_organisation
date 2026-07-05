"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Network,
  ZoomIn,
  ZoomOut,
  Scan,
  Target,
  X,
  GitCommitHorizontal,
  Quote,
  AtSign,
  ThumbsUp,
  Lightbulb,
  Reply as ReplyIcon,
  Settings2,
} from "lucide-react";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";
import { clamp } from "@/lib/utils";
import { agentColor } from "@/lib/agent-color";
import { DraftEntry } from "@/lib/types";
import {
  computeBoardGraphLayout,
  buildGraphEdges,
  GraphEdge,
  GraphEdgeKind,
  GraphLayout,
  HUB_RADIUS,
} from "@/lib/board-graph-layout";
import { GraphHubNode, GraphEntryCard } from "./board-graph-node";
import { EntryDetailModal } from "./entry-detail-modal";

interface BoardGraphViewProps {
  /** Thread-filtered but NOT visibility-filtered — the graph shows the full
   *  structure (evaporated entries included, just dimmed) since seeing what
   *  didn't survive is part of the point of this view. */
  draft: DraftEntry[];
  promotedMap: Map<string, number>;
  threshold: number;
  /** Full canvas roster incl. display names — needed so agents who only
   *  cite/vote (never author an entry) can still be resolved to a hub. */
  agents?: { id: string; name?: string }[];
  promotedAgentIds?: Set<string>;
  done?: boolean;
}

type Selected = { kind: "agent" | "entry"; id: string } | null;

const MIN_SCALE = 0.32;
const MAX_SCALE = 2.4;

/** Small constant perpendicular shift applied to *both* endpoints of an edge
 *  (not a mid-point bend) — keeps the line perfectly straight while still
 *  nudging apart edges that would otherwise draw exactly on top of each
 *  other (e.g. two citations between the same pair of nodes). Because the
 *  shift is uniform along the whole segment, the arrowhead's direction
 *  still matches the line's direction exactly — no more skewed arrows. */
function edgeLateralOffset(id: string): number {
  let hash = 0;
  for (let i = 0; i < id.length; i++)
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  return ((hash % 5) - 2) * 2.2;
}

/** What an edge endpoint key refers to, for boundary clipping — either a
 *  circular agent hub (fixed HUB_RADIUS) or a rectangular entry card (its
 *  actual on-screen w/h from the layout). */
function endpointShape(
  key: string,
  layout: GraphLayout,
): { hub: true } | { hub: false; w: number; h: number } {
  if (key.startsWith("entry:")) {
    const node = layout.nodeById.get(key.slice("entry:".length));
    if (node) return { hub: false, w: node.w, h: node.h };
  }
  return { hub: true };
}

/** Point where a ray from (cx,cy) toward unit direction (ux,uy) exits the
 *  node's own visual shape (circle for hubs, rectangle for cards) plus a
 *  small gap — i.e. where an edge should visually *stop*, instead of
 *  plunging into (and, through translucent backgrounds, visibly bleeding
 *  through) the node it's connecting to. */
function clipToBoundary(
  cx: number,
  cy: number,
  ux: number,
  uy: number,
  shape: { hub: true } | { hub: false; w: number; h: number },
  gap: number,
): { x: number; y: number } {
  if (shape.hub) {
    const r = HUB_RADIUS + gap;
    return { x: cx + ux * r, y: cy + uy * r };
  }
  const hw = shape.w / 2 + gap;
  const hh = shape.h / 2 + gap;
  const tx = ux !== 0 ? hw / Math.abs(ux) : Infinity;
  const ty = uy !== 0 ? hh / Math.abs(uy) : Infinity;
  const t = Math.min(tx, ty);
  return { x: cx + ux * t, y: cy + uy * t };
}

/**
 * Full drawable geometry for one edge: both ends pulled back to sit right
 * at the boundary of whichever node they touch (never crossing into it),
 * then nudged apart perpendicular to the line so multiple edges sharing
 * the same pair of nodes fan out instead of drawing on top of each other.
 * The perpendicular nudge is uniform along the whole segment, so the
 * arrowhead direction always matches the rendered line exactly.
 */
function edgeGeometry(
  edge: GraphEdge,
  layout: GraphLayout,
): { x1: number; y1: number; x2: number; y2: number } {
  const dx = edge.x2 - edge.x1;
  const dy = edge.y2 - edge.y1;
  const dist = Math.hypot(dx, dy) || 1;
  const ux = dx / dist;
  const uy = dy / dist;

  const p1 = clipToBoundary(
    edge.x1,
    edge.y1,
    ux,
    uy,
    endpointShape(edge.fromKey, layout),
    4,
  );
  const p2 = clipToBoundary(
    edge.x2,
    edge.y2,
    -ux,
    -uy,
    endpointShape(edge.toKey, layout),
    7,
  );

  const offset = edgeLateralOffset(edge.id);
  const nx = -uy * offset;
  const ny = ux * offset;
  return { x1: p1.x + nx, y1: p1.y + ny, x2: p2.x + nx, y2: p2.y + ny };
}

function arrowPolygon(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  pullBack = 2,
  size = 5,
): string {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  const tipX = x2 - ux * pullBack;
  const tipY = y2 - uy * pullBack;
  const baseX = tipX - ux * size * 1.7;
  const baseY = tipY - uy * size * 1.7;
  const px = -uy;
  const py = ux;
  return `${tipX},${tipY} ${baseX + px * size},${baseY + py * size} ${
    baseX - px * size
  },${baseY - py * size}`;
}

function edgeDash(kind: GraphEdgeKind): string | undefined {
  if (kind === "citation") return "7,5";
  if (kind === "mention") return "0.1,7";
  return undefined;
}

function toggleMembership<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

export function BoardGraphView({
  draft,
  promotedMap,
  threshold,
  agents = [],
  promotedAgentIds,
  done = false,
}: BoardGraphViewProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);

  const layout = useMemo(
    () => computeBoardGraphLayout(draft, agents, promotedMap),
    [draft, agents, promotedMap],
  );
  const edges = useMemo(
    () => buildGraphEdges(layout, agents, promotedAgentIds),
    [layout, agents, promotedAgentIds],
  );

  const [selected, setSelected] = useState<Selected>(null);
  const [spotlight, setSpotlight] = useState(done);
  const [expandedEntryId, setExpandedEntryId] = useState<string | null>(null);
  const [disabledKinds, setDisabledKinds] = useState<Set<GraphEdgeKind>>(
    new Set(),
  );
  const [disabledEntryTypes, setDisabledEntryTypes] = useState<
    Set<DraftEntry["entry_type"]>
  >(new Set());
  const [disabledAgentIds, setDisabledAgentIds] = useState<Set<string>>(
    new Set(),
  );
  const [view, setView] = useState({ x: 40, y: 30, scale: 0.85 });
  const [isPanning, setIsPanning] = useState(false);

  const viewportRef = useRef<HTMLDivElement>(null);
  const didFitRef = useRef(false);
  const dragRef = useRef<{
    sx: number;
    sy: number;
    ox: number;
    oy: number;
    moved: boolean;
  } | null>(null);

  // Once the run finishes, default to spotlighting confirmed findings so the
  // "what actually won" signal is immediate — still fully user-toggleable.
  const prevDoneRef = useRef(done);
  useEffect(() => {
    if (done && !prevDoneRef.current) setSpotlight(true);
    prevDoneRef.current = done;
  }, [done]);

  const fitToView = useCallback(() => {
    const el = viewportRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    if (rect.width < 10 || rect.height < 10) return;
    const scale = clamp(
      Math.min(rect.width / layout.maxX, rect.height / layout.maxY) * 0.9,
      MIN_SCALE,
      1.15,
    );
    setView({
      x: (rect.width - layout.maxX * scale) / 2,
      y: (rect.height - layout.maxY * scale) / 2,
      scale,
    });
  }, [layout]);

  useLayoutEffect(() => {
    if (didFitRef.current) return;
    if (layout.hubs.length === 0) return;
    didFitRef.current = true;
    const raf = requestAnimationFrame(fitToView);
    return () => cancelAnimationFrame(raf);
  }, [layout, fitToView]);

  // Wheel-to-zoom — React's onWheel is passive by default, so preventDefault
  // must happen on a manually-attached, non-passive native listener.
  useLayoutEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const rect = el.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      setView((v) => {
        const newScale = clamp(
          v.scale * (1 - e.deltaY * 0.0016),
          MIN_SCALE,
          MAX_SCALE,
        );
        const worldX = (cx - v.x) / v.scale;
        const worldY = (cy - v.y) / v.scale;
        return {
          scale: newScale,
          x: cx - worldX * newScale,
          y: cy - worldY * newScale,
        };
      });
    };
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, []);

  const zoomBy = useCallback((factor: number) => {
    const el = viewportRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const cx = rect.width / 2;
    const cy = rect.height / 2;
    setView((v) => {
      const newScale = clamp(v.scale * factor, MIN_SCALE, MAX_SCALE);
      const worldX = (cx - v.x) / v.scale;
      const worldY = (cy - v.y) / v.scale;
      return {
        scale: newScale,
        x: cx - worldX * newScale,
        y: cy - worldY * newScale,
      };
    });
  }, []);

  const onBgMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (e.button !== 0) return;
      setIsPanning(true);
      dragRef.current = {
        sx: e.clientX,
        sy: e.clientY,
        ox: view.x,
        oy: view.y,
        moved: false,
      };
      const onMove = (ev: MouseEvent) => {
        const d = dragRef.current;
        if (!d) return;
        const dx = ev.clientX - d.sx;
        const dy = ev.clientY - d.sy;
        if (Math.abs(dx) > 3 || Math.abs(dy) > 3) d.moved = true;
        setView((v) => ({ ...v, x: d.ox + dx, y: d.oy + dy }));
      };
      const onUp = () => {
        if (dragRef.current && !dragRef.current.moved) setSelected(null);
        dragRef.current = null;
        setIsPanning(false);
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [view],
  );

  // ── Selection → one-hop highlight (mirrors the bidding board's pattern) ──
  const highlight = useMemo(() => {
    if (!selected) return null;
    const nodeKeys = new Set<string>();
    const edgeIds = new Set<string>();
    if (selected.kind === "agent") {
      nodeKeys.add(`agent:${selected.id}`);
      for (const n of layout.nodes) {
        if (n.entry.author_id === selected.id)
          nodeKeys.add(`entry:${n.entry.id}`);
      }
    } else {
      nodeKeys.add(`entry:${selected.id}`);
      const node = layout.nodeById.get(selected.id);
      if (node) nodeKeys.add(`agent:${node.entry.author_id}`);
    }
    for (const e of edges) {
      if (nodeKeys.has(e.fromKey) || nodeKeys.has(e.toKey)) {
        edgeIds.add(e.id);
        nodeKeys.add(e.fromKey);
        nodeKeys.add(e.toKey);
      }
    }
    return { nodeKeys, edgeIds };
  }, [selected, layout, edges]);

  const hubOpacity = useCallback(
    (hubId: string) => {
      if (highlight) return highlight.nodeKeys.has(`agent:${hubId}`) ? 1 : 0.15;
      if (disabledAgentIds.has(hubId)) return 0.15;
      return 1;
    },
    [highlight, disabledAgentIds],
  );

  const entryOpacity = useCallback(
    (
      entryId: string,
      visible: boolean,
      confirmed: boolean,
      entryType: DraftEntry["entry_type"],
      authorId: string,
    ) => {
      if (highlight)
        return highlight.nodeKeys.has(`entry:${entryId}`) ? 1 : 0.08;
      if (disabledEntryTypes.has(entryType) || disabledAgentIds.has(authorId))
        return 0.2;
      if (!visible) return 0.32;
      if (spotlight && !confirmed) return 0.26;
      return 1;
    },
    [highlight, spotlight, disabledEntryTypes, disabledAgentIds],
  );

  const edgeStyle = useCallback(
    (edge: GraphEdge) => {
      const isHi = highlight?.edgeIds.has(edge.id) ?? false;
      const baseOpacity =
        edge.kind === "mention" ? 0.55 : edge.kind === "citation" ? 0.85 : 0.75;
      const filteredOut =
        disabledKinds.has(edge.kind) || disabledAgentIds.has(edge.ownerAgentId);
      const opacity = highlight
        ? isHi
          ? 1
          : 0.04
        : filteredOut
          ? 0.06
          : baseOpacity;
      // Reply/mention edges take the author's own accent (whose thought is
      // whose); citation and vote are recolored to the app's existing
      // "consensus" language (gold = cited toward confirmation, green =
      // voted) so the legend swatches always match what's on the canvas.
      const color =
        edge.kind === "vote"
          ? "#3dba8c"
          : edge.kind === "citation"
            ? "#b5860d"
            : edge.color;
      const width =
        (isHi ? 1.6 : 1) *
        (edge.kind === "citation" ? 2 : edge.kind === "mention" ? 1.6 : 1.8);
      return { opacity, color, width };
    },
    [highlight, disabledKinds, disabledAgentIds],
  );

  const hasContent = layout.hubs.length > 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* ── Toolbar ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 4px",
          flexShrink: 0,
          flexWrap: "wrap",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            overflowX: "auto",
            flex: 1,
            minWidth: 0,
            paddingBottom: 2,
          }}
          className="no-scrollbar"
        >
          {layout.hubs.map((hub) => {
            const color = agentColor(hub.id, agents, promotedAgentIds);
            const isSelected =
              selected?.kind === "agent" && selected.id === hub.id;
            return (
              <button
                key={hub.id}
                onClick={() =>
                  setSelected(isSelected ? null : { kind: "agent", id: hub.id })
                }
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 5,
                  padding: "3px 9px 3px 6px",
                  borderRadius: 100,
                  border: `1px solid ${isSelected ? color : `${color}45`}`,
                  background: isSelected
                    ? `${color}22`
                    : dark
                      ? "rgba(255,255,255,0.03)"
                      : "rgba(0,0,0,0.02)",
                  cursor: "pointer",
                  flexShrink: 0,
                  whiteSpace: "nowrap",
                }}
              >
                <span
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: "50%",
                    background: color,
                    flexShrink: 0,
                  }}
                />
                <span
                  style={{ fontSize: 10.5, fontWeight: 700, color: t.text }}
                >
                  {hub.name}
                </span>
                {hub.entryCount > 0 ? (
                  <span
                    style={{
                      fontSize: 9,
                      color: t.textDim,
                      fontFamily: "'JetBrains Mono', monospace",
                    }}
                  >
                    {hub.entryCount}
                  </span>
                ) : (
                  hub.citesGiven > 0 && (
                    <span
                      title={`Cited/voted ${hub.citesGiven}× without posting own contributions`}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 2,
                        fontSize: 9,
                        color: t.textDim,
                        fontFamily: "'JetBrains Mono', monospace",
                      }}
                    >
                      <ThumbsUp size={8} strokeWidth={2} />
                      {hub.citesGiven}
                    </span>
                  )
                )}
              </button>
            );
          })}
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
            flexShrink: 0,
          }}
        >
          {selected && (
            <button
              onClick={() => setSelected(null)}
              title="Clear selection"
              style={toolBtnStyle(dark, false)}
            >
              <X size={12} strokeWidth={2} />
            </button>
          )}
          <button
            onClick={() => zoomBy(0.82)}
            title="Zoom out"
            style={toolBtnStyle(dark, false)}
          >
            <ZoomOut size={12} strokeWidth={2} />
          </button>
          <button
            onClick={() => zoomBy(1.22)}
            title="Zoom in"
            style={toolBtnStyle(dark, false)}
          >
            <ZoomIn size={12} strokeWidth={2} />
          </button>
          <button
            onClick={fitToView}
            title="Fit to view"
            style={toolBtnStyle(dark, false)}
          >
            <Scan size={12} strokeWidth={2} />
          </button>
        </div>
      </div>

      {/* ── Viewport ── */}
      <div
        ref={viewportRef}
        onMouseDown={onBgMouseDown}
        style={{
          position: "relative",
          flex: 1,
          minHeight: 0,
          overflow: "hidden",
          borderRadius: 10,
          background: dark
            ? "radial-gradient(circle at 50% 40%, rgba(139,26,47,0.06), transparent 65%)"
            : "radial-gradient(circle at 50% 40%, rgba(139,26,47,0.04), transparent 65%)",
          cursor: isPanning ? "grabbing" : "grab",
        }}
      >
        {!hasContent && (
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              color: t.textDim,
            }}
          >
            <Network
              size={30}
              strokeWidth={1.3}
              color={`rgba(196,55,79,${dark ? 0.22 : 0.16})`}
            />
            <span style={{ fontSize: 12, fontWeight: 600 }}>
              Nothing to graph yet
            </span>
          </div>
        )}

        {hasContent && (
          <div
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              width: layout.maxX,
              height: layout.maxY,
              transformOrigin: "0 0",
              transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
              // Its own self-contained stacking context — makes the
              // svg-below-nodes ordering right below unambiguous regardless
              // of anything going on further up the tree (e.g. the modal
              // that hosts this view).
              isolation: "isolate",
            }}
          >
            <svg
              style={{
                position: "absolute",
                inset: 0,
                width: "100%",
                height: "100%",
                overflow: "visible",
                pointerEvents: "none",
                // Always below hub/entry nodes (zIndex 3+) — see
                // edgeGeometry() above, which also clips each edge to stop
                // right at a node's boundary instead of drawing into it,
                // so lines never visually "collide" with what they connect.
                zIndex: 1,
              }}
            >
              {edges.map((edge) => {
                const { x1, y1, x2, y2 } = edgeGeometry(edge, layout);
                const d = `M ${x1} ${y1} L ${x2} ${y2}`;
                const { opacity, color, width } = edgeStyle(edge);
                const showArrow = edge.kind !== "mention";
                return (
                  <g
                    key={edge.id}
                    style={{ opacity, transition: "opacity 0.15s" }}
                  >
                    <path
                      d={d}
                      fill="none"
                      stroke={color}
                      strokeWidth={width}
                      strokeDasharray={edgeDash(edge.kind)}
                      strokeLinecap="round"
                    />
                    {showArrow && (
                      <polygon
                        points={arrowPolygon(x1, y1, x2, y2)}
                        fill={color}
                      />
                    )}
                    {edge.kind === "citation" && (
                      <circle r={2.8} fill={color}>
                        <animateMotion
                          dur="2.1s"
                          repeatCount="indefinite"
                          path={d}
                        />
                      </circle>
                    )}
                  </g>
                );
              })}
            </svg>

            {layout.hubs.map((hub) => (
              <GraphHubNode
                key={hub.id}
                hub={hub}
                color={agentColor(hub.id, agents, promotedAgentIds)}
                opacity={hubOpacity(hub.id)}
                selected={selected?.kind === "agent" && selected.id === hub.id}
                onOpenChange={(open) =>
                  setSelected(open ? { kind: "agent", id: hub.id } : null)
                }
              />
            ))}

            {layout.nodes.map((node) => (
              <GraphEntryCard
                key={node.entry.id}
                node={node}
                color={agentColor(
                  node.entry.author_id,
                  agents,
                  promotedAgentIds,
                )}
                opacity={entryOpacity(
                  node.entry.id,
                  node.entry.is_visible,
                  node.confirmedRound !== null,
                  node.entry.entry_type,
                  node.entry.author_id,
                )}
                selected={
                  selected?.kind === "entry" && selected.id === node.entry.id
                }
                threshold={threshold}
                onToggleSelect={() =>
                  setSelected((prev) =>
                    prev?.kind === "entry" && prev.id === node.entry.id
                      ? null
                      : { kind: "entry", id: node.entry.id },
                  )
                }
                onExpand={() => setExpandedEntryId(node.entry.id)}
              />
            ))}
          </div>
        )}

        {/* ── Legend / filters ── */}
        {hasContent && (
          <div
            style={{
              position: "absolute",
              left: 10,
              bottom: 10,
              display: "flex",
              flexDirection: "column",
              gap: 8,
              padding: "7px 10px",
              borderRadius: 9,
              background: dark ? "rgba(10,9,16,0.75)" : "rgba(255,255,255,0.8)",
              border: `1px solid ${t.border}`,
              backdropFilter: "blur(8px)",
              pointerEvents: "none",
              maxHeight: "min(70%, 420px)",
              overflowY: "auto",
            }}
            className="no-scrollbar"
          >
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={legendGroupLabel(t.textDim)}>Line types</div>
              <LegendRow
                icon={GitCommitHorizontal}
                label="Reply"
                swatch={t.textSub}
                active={!disabledKinds.has("reply")}
                onClick={() =>
                  setDisabledKinds((prev) => toggleMembership(prev, "reply"))
                }
              />
              <LegendRow
                icon={Quote}
                label="Citation flow"
                swatch="#b5860d"
                dashed
                active={!disabledKinds.has("citation")}
                onClick={() =>
                  setDisabledKinds((prev) => toggleMembership(prev, "citation"))
                }
              />
              <LegendRow
                icon={AtSign}
                label="Mention"
                swatch={t.textDim}
                dotted
                active={!disabledKinds.has("mention")}
                onClick={() =>
                  setDisabledKinds((prev) => toggleMembership(prev, "mention"))
                }
              />
              <LegendRow
                icon={ThumbsUp}
                label="Vote"
                swatch="#3dba8c"
                active={!disabledKinds.has("vote")}
                onClick={() =>
                  setDisabledKinds((prev) => toggleMembership(prev, "vote"))
                }
              />
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={legendGroupLabel(t.textDim)}>Contributions</div>
              <LegendRow
                icon={Lightbulb}
                label="Proposal"
                swatch={t.textSub}
                active={!disabledEntryTypes.has("proposal")}
                onClick={() =>
                  setDisabledEntryTypes((prev) =>
                    toggleMembership(prev, "proposal"),
                  )
                }
              />
              <LegendRow
                icon={ReplyIcon}
                label="Reply"
                swatch={t.textDim}
                active={!disabledEntryTypes.has("reply")}
                onClick={() =>
                  setDisabledEntryTypes((prev) =>
                    toggleMembership(prev, "reply"),
                  )
                }
              />
              <LegendRow
                icon={ThumbsUp}
                label="Vote"
                swatch="#3dba8c"
                active={!disabledEntryTypes.has("vote")}
                onClick={() =>
                  setDisabledEntryTypes((prev) =>
                    toggleMembership(prev, "vote"),
                  )
                }
              />
              <LegendRow
                icon={Settings2}
                label="System"
                swatch="#7b9ec0"
                active={!disabledEntryTypes.has("system")}
                onClick={() =>
                  setDisabledEntryTypes((prev) =>
                    toggleMembership(prev, "system"),
                  )
                }
              />
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={legendGroupLabel(t.textDim)}>Unconfirmed</div>
              <LegendRow
                icon={Target}
                label="Unconfirmed findings"
                swatch="#b5860d"
                active={!spotlight}
                onClick={() => setSpotlight((s) => !s)}
              />
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={legendGroupLabel(t.textDim)}>Agents</div>
              {layout.hubs.map((hub) => {
                const hubColor = agentColor(hub.id, agents, promotedAgentIds);
                const active = !disabledAgentIds.has(hub.id);
                return (
                  <button
                    key={hub.id}
                    onClick={() =>
                      setDisabledAgentIds((prev) =>
                        toggleMembership(prev, hub.id),
                      )
                    }
                    title={active ? `Dim ${hub.name}` : `Show ${hub.name}`}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      background: "none",
                      border: "none",
                      padding: 0,
                      cursor: "pointer",
                      pointerEvents: "auto",
                      opacity: active ? 1 : 0.4,
                      transition: "opacity 0.15s",
                    }}
                  >
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: "50%",
                        background: hubColor,
                        flexShrink: 0,
                      }}
                    />
                    <span style={{ fontSize: 9.5, color: t.textSub }}>
                      {hub.name}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {expandedEntryId &&
          (() => {
            const node = layout.nodeById.get(expandedEntryId);
            if (!node) return null;
            return (
              <EntryDetailModal
                node={node}
                color={agentColor(
                  node.entry.author_id,
                  agents,
                  promotedAgentIds,
                )}
                threshold={threshold}
                onClose={() => setExpandedEntryId(null)}
              />
            );
          })()}
      </div>
    </div>
  );
}

function toolBtnStyle(
  dark: boolean,
  active: boolean,
  activeColor = "#C4374F",
): React.CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    width: 24,
    height: 24,
    borderRadius: 6,
    border: `1px solid ${active ? activeColor : "transparent"}`,
    background: active
      ? `${activeColor}22`
      : dark
        ? "rgba(255,255,255,0.05)"
        : "rgba(0,0,0,0.04)",
    color: active ? activeColor : dark ? "#9694b0" : "#4e4c68",
    cursor: "pointer",
    flexShrink: 0,
  };
}

function legendGroupLabel(textDim: string): React.CSSProperties {
  return {
    fontSize: 8.5,
    fontWeight: 800,
    color: textDim,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    fontFamily: "'Space Grotesk', system-ui, sans-serif",
  };
}

function LegendRow({
  icon: Icon,
  label,
  swatch,
  dashed,
  dotted,
  active,
  onClick,
}: {
  icon: React.ComponentType<{
    size?: number;
    strokeWidth?: number;
    color?: string;
  }>;
  label: string;
  swatch: string;
  dashed?: boolean;
  dotted?: boolean;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={
        active ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`
      }
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        background: "none",
        border: "none",
        padding: 0,
        cursor: "pointer",
        pointerEvents: "auto",
        opacity: active ? 1 : 0.4,
        transition: "opacity 0.15s",
      }}
    >
      <svg width={16} height={8}>
        <line
          x1={0}
          y1={4}
          x2={16}
          y2={4}
          stroke={swatch}
          strokeWidth={1.6}
          strokeDasharray={dashed ? "1,3.5" : dotted ? "2.5,3" : undefined}
        />
      </svg>
      <Icon size={10} strokeWidth={2} color={swatch} />
      <span style={{ fontSize: 9.5, color: swatch }}>{label}</span>
    </button>
  );
}
