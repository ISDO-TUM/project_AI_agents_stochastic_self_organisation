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
} from "@/lib/board-graph-layout";
import { GraphHubNode, GraphEntryCard } from "./board-graph-node";

interface BoardGraphViewProps {
  /** Thread-filtered but NOT visibility-filtered — the graph shows the full
   *  structure (evaporated entries included, just dimmed) since seeing what
   *  didn't survive is part of the point of this view. */
  draft: DraftEntry[];
  promotedMap: Map<string, number>;
  threshold: number;
  agents?: { id: string }[];
  promotedAgentIds?: Set<string>;
  done?: boolean;
}

type Selected = { kind: "agent" | "entry"; id: string } | null;

const MIN_SCALE = 0.32;
const MAX_SCALE = 2.4;

function curvedPath(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  bend: number,
): string {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const dist = Math.hypot(dx, dy) || 1;
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const nx = -dy / dist;
  const ny = dx / dist;
  const cx = mx + nx * dist * bend;
  const cy = my + ny * dist * bend;
  return `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`;
}

function edgeBend(id: string): number {
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  return (hash % 2 === 0 ? 1 : -1) * 0.14;
}

function arrowPolygon(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  pullBack = 15,
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
  if (kind === "citation") return "1,5";
  if (kind === "mention") return "3,4";
  return undefined;
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

  const agentIds = useMemo(() => agents.map((a) => a.id), [agents]);
  const layout = useMemo(
    () => computeBoardGraphLayout(draft, agentIds, promotedMap),
    [draft, agentIds, promotedMap],
  );
  const edges = useMemo(
    () => buildGraphEdges(layout, agents, promotedAgentIds),
    [layout, agents, promotedAgentIds],
  );

  const [selected, setSelected] = useState<Selected>(null);
  const [spotlight, setSpotlight] = useState(done);
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
        if (n.entry.author_id === selected.id) nodeKeys.add(`entry:${n.entry.id}`);
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
      return 1;
    },
    [highlight],
  );

  const entryOpacity = useCallback(
    (entryId: string, visible: boolean, confirmed: boolean) => {
      if (highlight) return highlight.nodeKeys.has(`entry:${entryId}`) ? 1 : 0.08;
      if (!visible) return 0.32;
      if (spotlight && !confirmed) return 0.26;
      return 1;
    },
    [highlight, spotlight],
  );

  const edgeStyle = useCallback(
    (edge: GraphEdge) => {
      const isHi = highlight?.edgeIds.has(edge.id) ?? false;
      const baseOpacity =
        edge.kind === "mention" ? 0.4 : edge.kind === "citation" ? 0.7 : 0.62;
      const opacity = highlight ? (isHi ? 1 : 0.04) : baseOpacity;
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
      const width = (isHi ? 1.5 : 1) * (edge.kind === "citation" ? 1.7 : edge.kind === "mention" ? 1 : 1.5);
      return { opacity, color, width };
    },
    [highlight],
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
            const isSelected = selected?.kind === "agent" && selected.id === hub.id;
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
                <span style={{ fontSize: 10.5, fontWeight: 700, color: t.text }}>
                  {hub.name}
                </span>
                <span
                  style={{
                    fontSize: 9,
                    color: t.textDim,
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                >
                  {hub.entryCount}
                </span>
              </button>
            );
          })}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
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
            onClick={() => setSpotlight((s) => !s)}
            title={
              spotlight
                ? "Spotlight: showing only confirmed findings clearly"
                : "Spotlight confirmed findings"
            }
            style={toolBtnStyle(dark, spotlight, "#b5860d")}
          >
            <Target size={12} strokeWidth={2} />
          </button>
          <button onClick={() => zoomBy(0.82)} title="Zoom out" style={toolBtnStyle(dark, false)}>
            <ZoomOut size={12} strokeWidth={2} />
          </button>
          <button onClick={() => zoomBy(1.22)} title="Zoom in" style={toolBtnStyle(dark, false)}>
            <ZoomIn size={12} strokeWidth={2} />
          </button>
          <button onClick={fitToView} title="Fit to view" style={toolBtnStyle(dark, false)}>
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
            <Network size={30} strokeWidth={1.3} color={`rgba(196,55,79,${dark ? 0.22 : 0.16})`} />
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
                zIndex: 1,
              }}
            >
              {edges.map((edge) => {
                const bend = edgeBend(edge.id);
                const path = curvedPath(edge.x1, edge.y1, edge.x2, edge.y2, bend);
                const { opacity, color, width } = edgeStyle(edge);
                const showArrow = edge.kind !== "mention";
                return (
                  <g key={edge.id} style={{ opacity, transition: "opacity 0.15s" }}>
                    <path
                      d={path}
                      fill="none"
                      stroke={color}
                      strokeWidth={width}
                      strokeDasharray={edgeDash(edge.kind)}
                      strokeLinecap="round"
                    />
                    {showArrow && (
                      <polygon
                        points={arrowPolygon(edge.x1, edge.y1, edge.x2, edge.y2)}
                        fill={color}
                      />
                    )}
                    {edge.kind === "citation" && (
                      <circle r={2.6} fill={color}>
                        <animateMotion
                          dur="2.1s"
                          repeatCount="indefinite"
                          path={path}
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
                color={agentColor(node.entry.author_id, agents, promotedAgentIds)}
                opacity={entryOpacity(
                  node.entry.id,
                  node.entry.is_visible,
                  node.confirmedRound !== null,
                )}
                selected={selected?.kind === "entry" && selected.id === node.entry.id}
                threshold={threshold}
                onToggleSelect={() =>
                  setSelected((prev) =>
                    prev?.kind === "entry" && prev.id === node.entry.id
                      ? null
                      : { kind: "entry", id: node.entry.id },
                  )
                }
              />
            ))}
          </div>
        )}

        {/* ── Edge-kind legend ── */}
        {hasContent && (
          <div
            style={{
              position: "absolute",
              left: 10,
              bottom: 10,
              display: "flex",
              flexDirection: "column",
              gap: 4,
              padding: "7px 10px",
              borderRadius: 9,
              background: dark ? "rgba(10,9,16,0.75)" : "rgba(255,255,255,0.8)",
              border: `1px solid ${t.border}`,
              backdropFilter: "blur(8px)",
              pointerEvents: "none",
            }}
          >
            <LegendRow icon={GitCommitHorizontal} label="Reply" swatch={t.textSub} />
            <LegendRow icon={Quote} label="Citation flow" swatch="#b5860d" dashed />
            <LegendRow icon={AtSign} label="Mention" swatch={t.textDim} dotted />
            <LegendRow icon={ThumbsUp} label="Vote" swatch="#3dba8c" />
          </div>
        )}
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

function LegendRow({
  icon: Icon,
  label,
  swatch,
  dashed,
  dotted,
}: {
  icon: React.ComponentType<{ size?: number; strokeWidth?: number; color?: string }>;
  label: string;
  swatch: string;
  dashed?: boolean;
  dotted?: boolean;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
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
    </div>
  );
}
