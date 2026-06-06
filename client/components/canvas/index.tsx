"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import {
  Agent,
  Source,
  Edge,
  AnimatedParticle,
  Tweaks,
  SimStep,
} from "@/lib/types";
import { clamp } from "@/lib/utils";
import { useTheme } from "@/lib/theme-context";

import { AgentNode } from "./agent-node";
import { SourceNode } from "./source-node";
import { EdgeLayer } from "./edge-layer";
import { Minimap } from "./minimap";
import { PhonebookPanel } from "../phonebook-panel";

interface CanvasProps {
  agents: Agent[];
  sources: Source[];
  edges: Edge[];
  dynamicEdges: Edge[];
  selectedNode: string | null;
  selectedEdge: string | null;
  onSelectNode: (id: string, e: React.MouseEvent) => void;
  onSelectEdge: (id: string) => void;
  onMoveNode: (id: string, position: { x: number; y: number }) => void;
  onConnectNodes: (fromId: string, toId: string) => void;
  onDeleteEdge: (id: string) => void;
  simMode: boolean;
  activeNodeId: string | null;
  activeEdgeId: string | null;
  activeEdgeReversed: boolean;
  animatedParticles: AnimatedParticle[];
  tweaks: Tweaks;
  onCanvasClick: () => void;
  /** Fired by parent when the available canvas width changes; dx is the
   *  translation to apply to the current pan so nodes stay put visually. */
  panAdjust?: { dx: number; seq: number };
  /** When provided, renders the PhonebookPanel inside the world transform so
   *  it pans/zooms with the canvas like any other element. */
  phonebook?: {
    agents: Agent[];
    steps: SimStep[];
    currentStep: number;
    dynamicEdges: Edge[];
    simMode: boolean;
  } | null;
}

interface ConnectingState {
  fromId: string;
  startX: number;
  startY: number;
}

interface ConnectLine {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export function Canvas({
  agents,
  sources,
  edges,
  dynamicEdges,
  selectedNode,
  selectedEdge,
  onSelectNode,
  onSelectEdge,
  onMoveNode,
  onConnectNodes,
  onDeleteEdge,
  simMode,
  activeNodeId,
  activeEdgeId,
  activeEdgeReversed,
  animatedParticles,
  tweaks,
  onCanvasClick,
  panAdjust,
  phonebook = null,
}: CanvasProps) {
  const { dark } = useTheme();
  const canvasRef = useRef<HTMLDivElement>(null);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const panning = useRef(false);
  const panStart = useRef({ x: 0, y: 0 });
  const connectingFrom = useRef<ConnectingState | null>(null);
  const [connectLine, setConnectLine] = useState<ConnectLine | null>(null);
  const spaceDown = useRef(false);

  // Apply external pan delta (e.g. from sidebar resize) to keep nodes stable.
  // panAdjust is a new object reference on every resize tick (seq increments),
  // so listing it as the dependency is both correct and exhaustive.
  useEffect(() => {
    if (!panAdjust || panAdjust.dx === 0) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPan((p) => ({ ...p, x: p.x + panAdjust.dx }));
  }, [panAdjust]);
  const handleWheel = useCallback(
    (e: WheelEvent) => {
      e.preventDefault();
      const el = canvasRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      // Cursor position in canvas-element space (screen coords relative to canvas)
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const oldZoom = zoom;
      const newZoom = clamp(oldZoom * (e.deltaY > 0 ? 0.93 : 1.07), 0.15, 5);
      const { x: px, y: py } = pan;
      // Keep the world-space point under the cursor fixed:
      //   worldPt = (screenPt - pan) / zoom
      //   newPan  = screenPt - worldPt * newZoom
      setPan({
        x: mx - ((mx - px) / oldZoom) * newZoom,
        y: my - ((my - py) / oldZoom) * newZoom,
      });
      setZoom(newZoom);
    },
    [pan, zoom],
  );

  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    el.addEventListener("wheel", handleWheel, { passive: false });
    return () => el.removeEventListener("wheel", handleWheel);
  }, [handleWheel]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (
        e.code === "Space" &&
        !(e.target as HTMLElement).matches("input,textarea,select")
      ) {
        e.preventDefault();
        spaceDown.current = true;
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code === "Space") spaceDown.current = false;
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, []);

  const canvasMouseDown = useCallback(
    (e: React.MouseEvent) => {
      const target = e.target as HTMLElement;
      const isCanvas =
        target === canvasRef.current || target.classList.contains("ctf");
      if (!isCanvas && !spaceDown.current) return;
      panning.current = true;
      panStart.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
      onCanvasClick();
    },
    [pan, onCanvasClick],
  );

  const canvasMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (panning.current) {
        setPan({
          x: e.clientX - panStart.current.x,
          y: e.clientY - panStart.current.y,
        });
      }
      if (connectingFrom.current && canvasRef.current) {
        const rect = canvasRef.current.getBoundingClientRect();
        setConnectLine({
          x1: connectingFrom.current.startX,
          y1: connectingFrom.current.startY,
          x2: (e.clientX - rect.left - pan.x) / zoom,
          y2: (e.clientY - rect.top - pan.y) / zoom,
        });
      }
    },
    [pan, zoom],
  );

  const canvasMouseUp = useCallback(
    (e: React.MouseEvent) => {
      if (panning.current) panning.current = false;
      if (connectingFrom.current) {
        const target = document.elementFromPoint(
          e.clientX,
          e.clientY,
        ) as HTMLElement | null;
        const nodeEl = target?.closest("[data-node-id]") as HTMLElement | null;
        const toId = nodeEl?.getAttribute("data-node-id");
        if (toId && toId !== connectingFrom.current.fromId) {
          onConnectNodes(connectingFrom.current.fromId, toId);
        }
        connectingFrom.current = null;
        setConnectLine(null);
      }
    },
    [onConnectNodes],
  );

  const handleConnectStart = useCallback(
    (fromId: string, e: React.MouseEvent) => {
      if (!canvasRef.current) return;
      const node = [...agents, ...sources].find((n) => n.id === fromId);
      if (!node) return;
      const rect = canvasRef.current.getBoundingClientRect();
      connectingFrom.current = {
        fromId,
        startX: node.position.x,
        startY: node.position.y,
      };
      setConnectLine({
        x1: node.position.x,
        y1: node.position.y,
        x2: (e.clientX - rect.left - pan.x) / zoom,
        y2: (e.clientY - rect.top - pan.y) / zoom,
      });
    },
    [agents, sources, pan, zoom],
  );

  const accent = tweaks.accentColor;
  const hasNodes = agents.length > 0 || sources.length > 0;
  const gridSize = tweaks.gridDensity * zoom;
  const offX = pan.x % gridSize;
  const offY = pan.y % gridSize;

  const canvasBg = dark
    ? `radial-gradient(ellipse 80% 60% at 50% 0%, rgba(139,26,47,0.07) 0%, transparent 70%), #060608`
    : `radial-gradient(ellipse 80% 60% at 50% 0%, rgba(139,26,47,0.04) 0%, transparent 70%), #f0eef8`;

  return (
    <div
      ref={canvasRef}
      style={{
        flex: 1,
        height: "100%",
        position: "relative",
        overflow: "hidden",
        cursor: "default",
        background: canvasBg,
      }}
      onMouseDown={canvasMouseDown}
      onMouseMove={canvasMouseMove}
      onMouseUp={canvasMouseUp}
    >
      {/* SVG dot grid */}
      {tweaks.showGrid && (
        <svg
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            pointerEvents: "none",
            zIndex: 0,
          }}
        >
          <defs>
            <pattern
              id="grid"
              x={offX}
              y={offY}
              width={gridSize}
              height={gridSize}
              patternUnits="userSpaceOnUse"
            >
              <circle
                cx={1}
                cy={1}
                r={0.9}
                fill={dark ? "rgba(255,255,255,0.07)" : "rgba(0,0,0,0.1)"}
              />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)" />
        </svg>
      )}

      {/* Ambient orbs */}
      {tweaks.showOrbs && dark && (
        <>
          <div
            style={{
              position: "absolute",
              width: 600,
              height: 600,
              borderRadius: "50%",
              background: `radial-gradient(circle, ${accent}09 0%, transparent 70%)`,
              top: "-15%",
              left: "25%",
              animation: "orbDrift 18s ease-in-out infinite",
              pointerEvents: "none",
              zIndex: 0,
            }}
          />
          <div
            style={{
              position: "absolute",
              width: 400,
              height: 400,
              borderRadius: "50%",
              background:
                "radial-gradient(circle, rgba(80,30,120,0.05) 0%, transparent 70%)",
              bottom: "5%",
              right: "15%",
              animation: "orbDrift 24s ease-in-out infinite reverse",
              pointerEvents: "none",
              zIndex: 0,
            }}
          />
        </>
      )}

      {/* Nodes + Edges (panned/zoomed) */}
      <div
        className="ctf"
        style={{
          position: "absolute",
          inset: 0,
          transformOrigin: "0 0",
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          zIndex: 1,
        }}
      >
        <EdgeLayer
          edges={edges}
          dynamicEdges={dynamicEdges}
          agents={agents}
          sources={sources}
          selectedEdge={selectedEdge}
          onSelectEdge={onSelectEdge}
          onDeleteEdge={onDeleteEdge}
          activeEdgeId={activeEdgeId}
          activeEdgeReversed={activeEdgeReversed}
          animatedParticles={animatedParticles}
          tweaks={tweaks}
        />
        {connectLine && (
          <svg
            style={{
              position: "absolute",
              inset: 0,
              overflow: "visible",
              pointerEvents: "none",
              zIndex: 100,
            }}
          >
            <line
              x1={connectLine.x1}
              y1={connectLine.y1}
              x2={connectLine.x2}
              y2={connectLine.y2}
              stroke={accent}
              strokeWidth="1.5"
              strokeDasharray="6,4"
              opacity={0.7}
            />
            <circle
              cx={connectLine.x2}
              cy={connectLine.y2}
              r="5"
              fill={accent}
              opacity={0.5}
            />
          </svg>
        )}
        {agents.map((agent) => (
          <AgentNode
            key={agent.id}
            agent={agent}
            selected={selectedNode === agent.id}
            active={activeNodeId === agent.id}
            simMode={simMode}
            onSelect={onSelectNode}
            onDragEnd={onMoveNode}
            onConnectStart={handleConnectStart}
            tweaks={tweaks}
          />
        ))}
        {sources.map((source) => (
          <SourceNode
            key={source.id}
            source={source}
            selected={selectedNode === source.id}
            active={activeNodeId === source.id}
            simMode={simMode}
            onSelect={onSelectNode}
            onDragEnd={onMoveNode}
            onConnectStart={handleConnectStart}
            tweaks={tweaks}
          />
        ))}
        {/* PhonebookPanel lives in world space — pans & zooms with the canvas */}
        {phonebook && (
          <PhonebookPanel
            agents={phonebook.agents}
            steps={phonebook.steps}
            currentStep={phonebook.currentStep}
            dynamicEdges={phonebook.dynamicEdges}
            simMode={phonebook.simMode}
            zoom={zoom}
          />
        )}
      </div>

      {/* Empty state — hidden when the phonebook panel takes its place */}
      {!hasNodes && !phonebook && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 20,
            pointerEvents: "none",
            zIndex: 10,
            animation: "fadeIn 0.7s ease-out",
          }}
        >
          <div style={{ animation: "emptyFloat 4s ease-in-out infinite" }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={dark ? "/logo_dark.png" : "/logo_light.png"}
              alt="Stochastic Agents"
              style={{ height: 160, width: "auto" }}
            />
          </div>
          <div
            style={{
              textAlign: "center",
              display: "flex",
              flexDirection: "column",
              gap: 8,
              alignItems: "center",
            }}
          >
            <div
              style={{
                fontSize: 26,
                fontWeight: 700,
                color: accent,
                letterSpacing: 4,
                textTransform: "uppercase",
              }}
            >
              Stochastic Agents
            </div>
            <div
              style={{
                fontSize: 12,
                color: dark ? "rgba(255,255,255,0.22)" : "rgba(0,0,0,0.28)",
                letterSpacing: 1.5,
                fontFamily: "'JetBrains Mono', monospace",
              }}
            >
              Add agents · Connect · Simulate
            </div>
          </div>
        </div>
      )}

      {/* Zoom indicator */}
      {zoom !== 1 && (
        <div
          style={{
            position: "absolute",
            bottom: 16,
            left: 16,
            background: dark ? "rgba(6,5,12,0.8)" : "rgba(255,255,255,0.85)",
            border: `1px solid ${
              dark ? "rgba(255,255,255,0.07)" : "rgba(0,0,0,0.08)"
            }`,
            borderRadius: 7,
            padding: "3px 9px",
            fontSize: 10,
            color: dark ? "#3e3c52" : "#6b6880",
            fontFamily: "'JetBrains Mono', monospace",
            backdropFilter: "blur(8px)",
            zIndex: 20,
          }}
        >
          {Math.round(zoom * 100)}%
        </div>
      )}

      {/* Minimap */}
      {hasNodes && <Minimap agents={agents} sources={sources} edges={edges} />}
    </div>
  );
}
