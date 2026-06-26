"use client";

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import {
  Agent,
  Source,
  Edge,
  AnimatedParticle,
  Tweaks,
  BlackboardState,
  SimStep,
} from "@/lib/types";
import { clamp } from "@/lib/utils";
import { computePromotedAuthorIds } from "@/lib/blackboard-utils";
import { useTheme } from "@/lib/theme-context";

import { AgentNode } from "./agent-node";
import { SourceNode } from "./source-node";
import { EdgeLayer } from "./edge-layer";
import { Minimap } from "./minimap";
import { DraftBoard } from "./draft-board";
import { ConfirmedBoard } from "./confirmed-board";
import { AgentDock } from "./agent-dock";
import { ThreadNode } from "./blackboard/thread-node";
import { PhonebookPanel } from "../phonebook-panel";
import { BiddingBoardPanel } from "../bidding-board-panel";

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
  panAdjust?: { dx: number; seq: number };
  /** Swarm mode: blackboard state to render in-world */
  blackboardState?: BlackboardState;
  appMode?: "topology" | "swarm" | null;
  /** Swarm: current run id — controls whether world nodes are visible */
  swarmRunId?: string | null;
  topbarWidth?: number | null;
  onSelectAgentChip?: (id: string) => void;
  /** When provided, renders the PhonebookPanel inside the world transform so
   *  it pans/zooms with the canvas like any other element. */
  phonebook?: {
    agents: Agent[];
    steps: SimStep[];
    currentStep: number;
    dynamicEdges: Edge[];
    simMode: boolean;
  } | null;
  /** When provided, renders the BiddingBoardPanel as a draggable node inside
   *  the world transform — pans/zooms with the canvas. */
  biddingBoard?: {
    steps: SimStep[];
    onClose: () => void;
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
  blackboardState,
  appMode,
  swarmRunId,
  topbarWidth,
  onSelectAgentChip,
  phonebook = null,
  biddingBoard = null,
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

  // ── Swarm widget positions (viewport-relative px) ──
  // Boards are fixed forever — geometry is derived from the measured topbar
  // width, never independently moved or resized. The agent dock anchor is
  // derived the same way (see dockAnchor below).
  const BOARD_DEFAULT_W = 315;
  const BOARD_HEIGHT = 300;
  const BOARD_GAP = 24;
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [boardLayout, setBoardLayout] = useState<{
    draftPos: { x: number; y: number };
    confirmedPos: { x: number; y: number };
    boardWidth: number;
    dockAnchor: { x: number; y: number };
  } | null>(null);

  // Recompute whenever the canvas resizes or the measured topbar width
  // changes — this is the only thing that ever updates board/dock geometry.
  useEffect(() => {
    if (appMode !== "swarm") return;
    const el = canvasRef.current;
    if (!el) return;

    const recompute = () => {
      const { width, height } = el.getBoundingClientRect();
      const cx = width / 2;
      const cy = height / 2;
      const totalWidth = topbarWidth ?? BOARD_DEFAULT_W * 2 + BOARD_GAP;
      const boardWidth = (totalWidth - BOARD_GAP) / 2;
      setBoardLayout({
        draftPos: { x: cx - boardWidth - BOARD_GAP / 2, y: cy - 120 },
        confirmedPos: { x: cx + BOARD_GAP / 2, y: cy - 120 },
        boardWidth,
        dockAnchor: { x: cx, y: height - 130 },
      });
    };

    recompute();
    window.addEventListener("resize", recompute);
    return () => window.removeEventListener("resize", recompute);
  }, [appMode, topbarWidth]);

  const draftPos = boardLayout?.draftPos ?? null;
  const confirmedPos = boardLayout?.confirmedPos ?? null;
  const boardWidth = boardLayout?.boardWidth ?? BOARD_DEFAULT_W;
  const dockAnchor = boardLayout?.dockAnchor ?? null;

  const promotedAuthorIds = useMemo(
    () =>
      computePromotedAuthorIds(
        blackboardState?.draft ?? [],
        blackboardState?.confirmed ?? [],
      ),
    [blackboardState],
  );

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
      if (appMode === "swarm") return;
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
    [pan, zoom, appMode],
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
      if (appMode !== "swarm") {
        panning.current = true;
        panStart.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
      }
      onCanvasClick();
    },
    [pan, onCanvasClick, appMode],
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
      if (appMode === "swarm") return; // connections locked to blackboard in swarm mode
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
    [appMode, agents, sources, pan, zoom],
  );

  const accent = tweaks.accentColor;
  const hasNodes = agents.length > 0 || sources.length > 0;
  const gridSize = tweaks.gridDensity * zoom;
  const offX = pan.x % gridSize;
  const offY = pan.y % gridSize;

  const canvasBg = dark
    ? `radial-gradient(ellipse 80% 60% at 50% 0%, rgba(139,26,47,0.07) 0%, transparent 70%), #111018`
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
        {appMode !== "swarm" &&
          agents.map((agent) => (
            <AgentNode
              key={agent.id}
              agent={agent}
              selected={selectedNode === agent.id}
              active={activeNodeId === agent.id}
              simMode={simMode}
              swarmMode={false}
              zoom={zoom}
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
            swarmMode={appMode === "swarm"}
            zoom={zoom}
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
        {biddingBoard && (
          <BiddingBoardPanel
            steps={biddingBoard.steps}
            onClose={biddingBoard.onClose}
            zoom={zoom}
          />
        )}
      </div>

      {/* ── Swarm-mode viewport overlays (not in world transform) ── */}
      {appMode === "swarm" && (
        <>
          {/* Dashed connector between MM and Draft board; per-agent connectors
              that re-target from Draft to Confirmed once an agent has a
              promoted entry. */}
          {draftPos && dockAnchor && (
            <svg
              style={{
                position: "absolute",
                inset: 0,
                width: "100%",
                height: "100%",
                pointerEvents: "none",
                zIndex: 18,
                overflow: "visible",
              }}
            >
              {/* Agent → board connectors, all originating from the fixed
                  AgentDock anchor (agents have no individual canvas position
                  in swarm mode anymore): Draft by default, Confirmed (solid
                  gold) once that agent has a promoted entry. */}
              {agents.map((agent) => {
                const promoted = promotedAuthorIds.has(agent.id);
                const targetPos = promoted ? confirmedPos : draftPos;
                if (!targetPos) return null;
                const bx = targetPos.x + (boardWidth * zoom) / 2;
                const by = targetPos.y;
                return (
                  <line
                    key={agent.id}
                    x1={dockAnchor.x}
                    y1={dockAnchor.y}
                    x2={bx}
                    y2={by}
                    stroke={promoted ? "#b5860d" : "rgba(139,26,47,0.25)"}
                    strokeWidth={promoted ? "1.5" : "1"}
                    strokeDasharray={promoted ? undefined : "4,5"}
                  />
                );
              })}
            </svg>
          )}
          <AgentDock agents={agents} onSelectAgent={onSelectAgentChip ?? (() => {})} />
          {draftPos && (blackboardState?.threads.length ?? 0) > 0 && (
            <>
              <ThreadNode
                thread={{ id: "__all__", title: "All threads" }}
                active={activeThreadId === null}
                pos={{ x: draftPos.x, y: draftPos.y - 32 }}
                onClick={() => setActiveThreadId(null)}
              />
              {blackboardState!.threads.map((th, i) => (
                <ThreadNode
                  key={th.id}
                  thread={th}
                  active={activeThreadId === th.id}
                  pos={{ x: draftPos.x + (i + 1) * 110, y: draftPos.y - 32 }}
                  onClick={() => setActiveThreadId(th.id)}
                />
              ))}
            </>
          )}
          <DraftBoard
            state={
              blackboardState ?? {
                confirmed: [],
                draft: [],
                threads: [],
                loading: false,
                error: null,
              }
            }
            runId={swarmRunId ?? null}
            pos={draftPos}
            width={boardWidth}
            height={BOARD_HEIGHT}
            zoom={zoom}
            activeThreadId={activeThreadId}
          />
          <ConfirmedBoard
            state={
              blackboardState ?? {
                confirmed: [],
                draft: [],
                threads: [],
                loading: false,
                error: null,
              }
            }
            pos={confirmedPos}
            width={boardWidth}
            height={BOARD_HEIGHT}
            zoom={zoom}
            activeThreadId={activeThreadId}
          />
        </>
      )}

      {/* Empty state — hidden during swarm mode or when a panel occupies the space */}
      {!hasNodes && appMode !== "swarm" && !phonebook && (
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
              alt="Mycellium"
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
              Mycellium
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
