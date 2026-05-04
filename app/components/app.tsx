"use client";

import { useState, useEffect, useCallback, useReducer, useRef } from "react";
import {
  CanvasState,
  CanvasAction,
  Agent,
  Source,
  SimStep,
  AnimatedParticle,
  Tweaks,
} from "@/lib/types";
import { uuid, autoLayout } from "@/lib/utils";
import { BURG } from "@/lib/theme";
import { generateSimSteps } from "@/lib/simulation";
import {
  fetchAgents,
  createAgent,
  updateAgent,
  deleteAgentApi,
} from "@/lib/api";
import { Canvas } from "@/components/canvas";
import { LogWall } from "@/components/log-wall";
import { Toolbar } from "@/components/toolbar";
import { PromptBar } from "@/components/prompt-bar";
import { ContextMenu, ContextMenuItem } from "@/components/context-menu";
import { TweaksPanel } from "@/components/tweaks-panel";
import { AgentPanel } from "@/components/panels/agent-panel";
import { SourcePanel } from "@/components/panels/source-panel";
import { getTheme } from "@/lib/theme";

function reducer(state: CanvasState, action: CanvasAction): CanvasState {
  const { agents, sources, edges } = state;
  switch (action.type) {
    case "ADD_AGENT":
      return { ...state, agents: [...agents, action.agent] };
    case "UPDATE_AGENT":
      return {
        ...state,
        agents: agents.map((a) =>
          a.id === action.agent.id ? action.agent : a,
        ),
      };
    case "DELETE_AGENT":
      return {
        ...state,
        agents: agents
          .filter((a) => a.id !== action.id)
          .map((a) => ({
            ...a,
            connections: a.connections.filter((c) => c !== action.id),
          })),
        edges: edges.filter((e) => e.from !== action.id && e.to !== action.id),
      };
    case "ADD_SOURCE":
      return { ...state, sources: [...sources, action.source] };
    case "UPDATE_SOURCE":
      return {
        ...state,
        sources: sources.map((s) =>
          s.id === action.source.id ? action.source : s,
        ),
      };
    case "DELETE_SOURCE":
      return {
        ...state,
        sources: sources.filter((s) => s.id !== action.id),
        edges: edges.filter((e) => e.from !== action.id && e.to !== action.id),
      };
    case "MOVE_NODE":
      return {
        ...state,
        agents: agents.map((a) =>
          a.id === action.id ? { ...a, position: action.position } : a,
        ),
        sources: sources.map((s) =>
          s.id === action.id ? { ...s, position: action.position } : s,
        ),
      };
    case "ADD_EDGE":
      return edges.some(
        (e) => e.from === action.edge.from && e.to === action.edge.to,
      )
        ? state
        : { ...state, edges: [...edges, action.edge] };
    case "DELETE_EDGE":
      return { ...state, edges: edges.filter((e) => e.id !== action.id) };
    case "CLEAR":
      return { agents: [], sources: [], edges: [] };
    case "LOAD":
      return action.state;
    case "AUTO_LAYOUT": {
      const { agents: na, sources: ns } = autoLayout(agents, sources);
      return { ...state, agents: na, sources: ns };
    }
    default:
      return state;
  }
}

const defaultTweaks: Tweaks = {
  nodeSize: 88,
  edgeWidth: 1.5,
  gridDensity: 28,
  showGrid: true,
  showOrbs: true,
  particleSpeed: 0.9,
  showPulse: true,
  accentColor: BURG,
};

interface PanelState {
  type: "agent" | "source";
  id: string | null;
}
interface CtxState {
  x: number;
  y: number;
  nodeId: string | null;
}

export function App() {
  const [dark, setDark] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return (localStorage.getItem("theme") ?? "light") === "dark";
  });

  useEffect(() => {
    localStorage.setItem("theme", dark ? "dark" : "light");
    document.body.style.background = dark ? "#060608" : "#f0eef8";
    document.body.style.color = dark ? "#eceaf5" : "#18161f";
  }, [dark]);

  const [tweaks, setTweaks] = useState<Tweaks>(defaultTweaks);
  const [showTweaks, setShowTweaks] = useState(false);
  const setTweak = useCallback(
    (k: keyof Tweaks, v: Tweaks[keyof Tweaks]) =>
      setTweaks((t) => ({ ...t, [k]: v })),
    [],
  );

  const [state, dispatch] = useReducer(reducer, {
    agents: [],
    sources: [],
    edges: [],
  });
  const { agents, sources, edges } = state;

  const [selNode, setSelNode] = useState<string | null>(null);
  const [selEdge, setSelEdge] = useState<string | null>(null);
  const [panel, setPanel] = useState<PanelState | null>(null);
  const [ctx, setCtx] = useState<CtxState | null>(null);
  const [simMode, setSim] = useState(false);
  const [steps, setSteps] = useState<SimStep[]>([]);
  const [cur, setCur] = useState(0);
  const [logExp, setLogExp] = useState(false);
  const [activeNode, setActNode] = useState<string | null>(null);
  const [activeEdge, setActEdge] = useState<string | null>(null);
  const [particles, setParticles] = useState<AnimatedParticle[]>([]);
  const [importError, setImportError] = useState<string | null>(null);
  const particleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const importErrorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );

  useEffect(() => {
    return () => {
      if (particleTimerRef.current) clearTimeout(particleTimerRef.current);
      if (importErrorTimerRef.current)
        clearTimeout(importErrorTimerRef.current);
    };
  }, []);

  // Hydrate agents from API on mount
  useEffect(() => {
    fetchAgents()
      .then((list) => {
        dispatch({
          type: "LOAD",
          state: { agents: list, sources: [], edges: [] },
        });
      })
      .catch(() => {
        // API not yet available – start with empty canvas
      });
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.matches("input,textarea,select")) return;
      if (e.key === "Escape") {
        setPanel(null);
        setCtx(null);
        setSelNode(null);
        setSelEdge(null);
        setShowTweaks(false);
      }
      if (
        (e.key === "Delete" || e.key === "Backspace") &&
        !e.metaKey &&
        !e.ctrlKey
      ) {
        if (selNode) {
          if (agents.some((a) => a.id === selNode))
            dispatch({ type: "DELETE_AGENT", id: selNode });
          else dispatch({ type: "DELETE_SOURCE", id: selNode });
          setSelNode(null);
        }
        if (selEdge) {
          dispatch({ type: "DELETE_EDGE", id: selEdge });
          setSelEdge(null);
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selNode, selEdge, agents]);

  // Sim step sync
  useEffect(() => {
    if (!simMode || !steps.length) return;
    const s = steps[cur];
    if (!s) return;
    if (s.nodeId) {
      setActNode(s.nodeId);
      setActEdge(null);
    } else if (s.fromId && s.toId) {
      const e = edges.find(
        (e) =>
          (e.from === s.fromId && e.to === s.toId) ||
          (e.from === s.toId && e.to === s.fromId),
      );
      setActEdge(e ? e.id : null);
      setActNode(s.fromId ?? null);
    } else {
      setActNode(null);
      setActEdge(null);
    }
  }, [cur, simMode, steps, edges]);

  const saveAgent = useCallback(
    async (data: Agent) => {
      const exists = agents.find((a) => a.id === data.id);
      try {
        const saved = exists
          ? await updateAgent(data)
          : await createAgent(data);
        // preserve canvas position (API doesn't store it)
        const withPos: Agent = { ...saved, position: data.position };
        if (exists) {
          dispatch({ type: "UPDATE_AGENT", agent: withPos });
          const existing = edges
            .filter((e) => e.from === data.id)
            .map((e) => e.to);
          withPos.connections
            .filter((c) => !existing.includes(c))
            .forEach((toId) =>
              dispatch({
                type: "ADD_EDGE",
                edge: { id: uuid(), from: withPos.id, to: toId },
              }),
            );
        } else {
          dispatch({ type: "ADD_AGENT", agent: withPos });
          withPos.connections.forEach((toId) =>
            dispatch({
              type: "ADD_EDGE",
              edge: { id: uuid(), from: withPos.id, to: toId },
            }),
          );
        }
      } catch {
        // API unavailable — fall back to local-only
        if (exists) {
          dispatch({ type: "UPDATE_AGENT", agent: data });
          const existing = edges
            .filter((e) => e.from === data.id)
            .map((e) => e.to);
          data.connections
            .filter((c) => !existing.includes(c))
            .forEach((toId) =>
              dispatch({
                type: "ADD_EDGE",
                edge: { id: uuid(), from: data.id, to: toId },
              }),
            );
        } else {
          dispatch({ type: "ADD_AGENT", agent: data });
          data.connections.forEach((toId) =>
            dispatch({
              type: "ADD_EDGE",
              edge: { id: uuid(), from: data.id, to: toId },
            }),
          );
        }
      }
      setPanel(null);
    },
    [agents, edges],
  );

  const deleteAgent = useCallback(async (id: string) => {
    try {
      await deleteAgentApi(id);
    } catch {
      // API unavailable — proceed with local delete
    }
    dispatch({ type: "DELETE_AGENT", id });
    setPanel(null);
    setSelNode(null);
    setCtx(null);
  }, []);

  const saveSource = useCallback(
    (data: Source) => {
      if (sources.find((s) => s.id === data.id))
        dispatch({ type: "UPDATE_SOURCE", source: data });
      else dispatch({ type: "ADD_SOURCE", source: data });
      setPanel(null);
    },
    [sources],
  );

  const deleteSource = useCallback((id: string) => {
    dispatch({ type: "DELETE_SOURCE", id });
    setPanel(null);
    setSelNode(null);
    setCtx(null);
  }, []);

  const connectNodes = useCallback(
    (from: string, to: string) => {
      dispatch({ type: "ADD_EDGE", edge: { id: uuid(), from, to } });
      const ag = agents.find((a) => a.id === from);
      if (ag && !ag.connections.includes(to))
        dispatch({
          type: "UPDATE_AGENT",
          agent: { ...ag, connections: [...ag.connections, to] },
        });
    },
    [agents],
  );

  const deleteEdge = useCallback(
    (id: string) => {
      const e = edges.find((e) => e.id === id);
      if (e) {
        const ag = agents.find((a) => a.id === e.from);
        if (ag)
          dispatch({
            type: "UPDATE_AGENT",
            agent: {
              ...ag,
              connections: ag.connections.filter((c) => c !== e.to),
            },
          });
      }
      dispatch({ type: "DELETE_EDGE", id });
      setSelEdge(null);
    },
    [edges, agents],
  );

  const runSim = useCallback(
    (prompt: string) => {
      const s = generateSimSteps(agents, sources, prompt);
      if (!s.length) return;
      setSteps(s);
      setCur(0);
      setSim(true);
      setLogExp(false);
      const pts: AnimatedParticle[] = edges.map((e, i) => ({
        id: uuid(),
        from: e.from,
        to: e.to,
        dur: 0.55 + Math.random() * 0.3,
        delay: i * 0.09,
      }));
      setParticles(pts);
      if (particleTimerRef.current) clearTimeout(particleTimerRef.current);
      particleTimerRef.current = setTimeout(() => setParticles([]), 3500);
    },
    [agents, sources, edges],
  );

  const stopSim = useCallback(() => {
    if (particleTimerRef.current) clearTimeout(particleTimerRef.current);
    setSim(false);
    setSteps([]);
    setCur(0);
    setActNode(null);
    setActEdge(null);
    setParticles([]);
  }, []);

  const exportCanvas = useCallback(() => {
    const blob = new Blob(
      [JSON.stringify({ agents, sources, edges }, null, 2)],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "canvas.json";
    a.click();
    URL.revokeObjectURL(url);
  }, [agents, sources, edges]);

  const showImportError = useCallback((msg: string) => {
    if (importErrorTimerRef.current) clearTimeout(importErrorTimerRef.current);
    setImportError(msg);
    importErrorTimerRef.current = setTimeout(() => setImportError(null), 4000);
  }, []);

  const importCanvas = useCallback(
    (raw: string) => {
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = JSON.parse(raw) as any;
        if (
          Array.isArray(data.agents) &&
          Array.isArray(data.sources) &&
          Array.isArray(data.edges)
        )
          dispatch({ type: "LOAD", state: data as CanvasState });
        else
          showImportError(
            "Invalid canvas file — missing agents, sources, or edges",
          );
      } catch {
        showImportError("Invalid JSON file");
      }
    },
    [showImportError],
  );

  const selectNode = useCallback((id: string, e: React.MouseEvent) => {
    setSelNode(id);
    setSelEdge(null);
    if (e?.button === 2) {
      e.preventDefault();
      setCtx({ x: e.clientX, y: e.clientY, nodeId: id });
    }
  }, []);

  const openPanel = useCallback(
    (id: string) => {
      if (simMode) return;
      if (agents.some((a) => a.id === id)) setPanel({ type: "agent", id });
      else if (sources.some((s) => s.id === id))
        setPanel({ type: "source", id });
    },
    [simMode, agents, sources],
  );

  const nodeCtxItems = (id: string): ContextMenuItem[] => [
    { label: "Edit", icon: "Settings2", fn: () => openPanel(id) },
    {
      label: "Delete",
      icon: "Trash2",
      danger: true,
      fn: () => {
        agents.some((a) => a.id === id) ? deleteAgent(id) : deleteSource(id);
      },
    },
  ];

  const canvasCtxItems: ContextMenuItem[] = [
    {
      label: "Add Agent",
      icon: "Plus",
      fn: () => {
        setPanel({ type: "agent", id: null });
        setSelNode(null);
      },
    },
    {
      label: "Add Source",
      icon: "FileText",
      fn: () => {
        setPanel({ type: "source", id: null });
        setSelNode(null);
      },
    },
  ];

  const onSelectEdge = useCallback((id: string) => {
    setSelEdge(id);
    setSelNode(null);
  }, []);

  const onMoveNode = useCallback(
    (id: string, pos: { x: number; y: number }) =>
      dispatch({ type: "MOVE_NODE", id, position: pos }),
    [],
  );

  const onCanvasClick = useCallback(() => {
    setSelNode(null);
    setSelEdge(null);
    setPanel(null);
    setCtx(null);
  }, []);

  const onToggleTheme = useCallback(() => setDark((x) => !x), []);
  const onAddAgent = useCallback(() => {
    setPanel({ type: "agent", id: null });
    setSelNode(null);
  }, []);
  const onAddSource = useCallback(() => {
    setPanel({ type: "source", id: null });
    setSelNode(null);
  }, []);
  const onClear = useCallback(() => dispatch({ type: "CLEAR" }), []);
  const onAutoLayout = useCallback(() => dispatch({ type: "AUTO_LAYOUT" }), []);
  const onToggleTweaks = useCallback(() => setShowTweaks((x) => !x), []);

  const panelAgent =
    panel?.type === "agent" && panel.id
      ? agents.find((a) => a.id === panel.id) ?? null
      : null;
  const panelSource =
    panel?.type === "source" && panel.id
      ? sources.find((s) => s.id === panel.id) ?? null
      : null;
  const t = getTheme(dark);
  const hasNodes = agents.length > 0 || sources.length > 0;

  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        width: "100vw",
        background: t.bg,
        overflow: "hidden",
        position: "relative",
      }}
      onContextMenu={(e) => {
        const el = (e.target as HTMLElement).closest(
          "[data-node-id]",
        ) as HTMLElement | null;
        if (el) {
          e.preventDefault();
          const id = el.getAttribute("data-node-id")!;
          setCtx({ x: e.clientX, y: e.clientY, nodeId: id });
          setSelNode(id);
        } else if (!simMode) {
          e.preventDefault();
          setCtx({ x: e.clientX, y: e.clientY, nodeId: null });
        }
      }}
    >
      <style>{`
        .connect-handle { opacity: 0; transition: opacity 0.18s; }
        [data-node-id]:hover .connect-handle { opacity: 1 !important; }
        input, textarea, select { font-family: 'Space Grotesk', system-ui, sans-serif; }
        select { -webkit-appearance: none; appearance: none; }
        .pscroll::-webkit-scrollbar { width: 3px; }
        .pscroll::-webkit-scrollbar-thumb { background: rgba(139,26,47,0.22); border-radius: 2px; }
      `}</style>

      {/* Full-bleed canvas */}
      <div
        style={{
          flex: 1,
          display: "flex",
          overflow: "hidden",
          position: "relative",
        }}
        onClick={(e) => {
          const el = (e.target as HTMLElement).closest(
            "[data-node-id]",
          ) as HTMLElement | null;
          if (el) openPanel(el.getAttribute("data-node-id")!);
        }}
      >
        <Canvas
          agents={agents}
          sources={sources}
          edges={edges}
          selectedNode={selNode}
          selectedEdge={selEdge}
          onSelectNode={selectNode}
          onSelectEdge={onSelectEdge}
          onMoveNode={onMoveNode}
          onConnectNodes={connectNodes}
          onDeleteEdge={deleteEdge}
          simMode={simMode}
          activeNodeId={activeNode}
          activeEdgeId={activeEdge}
          animatedParticles={particles}
          dark={dark}
          tweaks={tweaks}
          onCanvasClick={onCanvasClick}
        />
      </div>

      {/* Log wall */}
      {simMode && (
        <LogWall
          steps={steps}
          currentStep={cur}
          onNext={() => setCur((s) => Math.min(s + 1, steps.length - 1))}
          onPrev={() => setCur((s) => Math.max(s - 1, 0))}
          expanded={logExp}
          onToggleExpand={() => setLogExp((x) => !x)}
          dark={dark}
        />
      )}

      {/* Floating toolbar */}
      <Toolbar
        simMode={simMode}
        dark={dark}
        onToggleTheme={onToggleTheme}
        onAddAgent={onAddAgent}
        onAddSource={onAddSource}
        onClear={onClear}
        onStop={stopSim}
        onAutoLayout={onAutoLayout}
        onExport={exportCanvas}
        onImport={importCanvas}
        showTweaks={showTweaks}
        onToggleTweaks={onToggleTweaks}
      />

      {/* Floating prompt bar */}
      <PromptBar simMode={simMode} onRun={runSim} dark={dark} />

      {/* Tweaks panel */}
      {showTweaks && (
        <TweaksPanel
          tweaks={tweaks}
          onChange={setTweak}
          onClose={() => setShowTweaks(false)}
          dark={dark}
        />
      )}

      {/* Slide-in panels */}
      {panel?.type === "agent" && (
        <AgentPanel
          key={panel.id ?? "new-agent"}
          agent={panelAgent}
          agents={agents}
          onSave={saveAgent}
          onDelete={deleteAgent}
          onClose={() => setPanel(null)}
          dark={dark}
        />
      )}
      {panel?.type === "source" && (
        <SourcePanel
          key={panel.id ?? "new-source"}
          source={panelSource}
          onSave={saveSource}
          onDelete={deleteSource}
          onClose={() => setPanel(null)}
          dark={dark}
        />
      )}

      {/* Import error toast */}
      {importError && (
        <div
          style={{
            position: "absolute",
            top: 72,
            left: "50%",
            transform: "translateX(-50%)",
            background: "rgba(139,26,47,0.92)",
            color: "#fff",
            borderRadius: 8,
            padding: "8px 18px",
            fontSize: 13,
            fontWeight: 600,
            zIndex: 200,
            pointerEvents: "none",
            animation: "fadeIn 0.2s ease-out",
          }}
        >
          {importError}
        </div>
      )}

      {/* Context menu */}
      {ctx && (
        <ContextMenu
          x={ctx.x}
          y={ctx.y}
          dark={dark}
          items={ctx.nodeId ? nodeCtxItems(ctx.nodeId) : canvasCtxItems}
          onClose={() => setCtx(null)}
        />
      )}

      {/* Keyboard hints */}
      {!simMode && hasNodes && (
        <div
          style={{
            position: "absolute",
            bottom: 104,
            left: "50%",
            transform: "translateX(-50%)",
            display: "flex",
            gap: 14,
            pointerEvents: "none",
            zIndex: 90,
          }}
        >
          {(
            [
              ["Del", "delete"],
              ["Esc", "close"],
              ["Space", "pan"],
            ] as const
          ).map(([k, label]) => (
            <div
              key={k}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 5,
                opacity: 0.3,
              }}
            >
              <span
                style={{
                  fontSize: 9.5,
                  background: t.pill,
                  border: `1px solid ${t.border}`,
                  borderRadius: 4,
                  padding: "1px 6px",
                  color: t.textSub,
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                {k}
              </span>
              <span
                style={{
                  fontSize: 9.5,
                  color: t.textDim,
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                {label}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
