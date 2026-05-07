"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { CanvasState, Tweaks } from "@/lib/types";
import { BURG } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import { useCanvasState } from "@/hooks/useCanvasState";
import { useSimulation } from "@/hooks/useSimulation";
import { useUIState } from "@/hooks/useUIState";
import { Canvas } from "@/components/canvas";
import { LogWall } from "@/components/log-wall";
import { Toolbar } from "@/components/toolbar";
import { PromptBar } from "@/components/prompt-bar";
import { ContextMenu, ContextMenuItem } from "@/components/context-menu";
import { TweaksPanel } from "@/components/tweaks-panel";
import { AgentPanel } from "@/components/panels/agent-panel";
import { SourcePanel } from "@/components/panels/source-panel";
import { getTheme } from "@/lib/theme";

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

export function App() {
  const { dark, toggle: toggleTheme } = useTheme();

  const [tweaks, setTweaks] = useState<Tweaks>(defaultTweaks);
  const setTweak = useCallback(
    (k: keyof Tweaks, v: Tweaks[keyof Tweaks]) =>
      setTweaks((t) => ({ ...t, [k]: v })),
    [],
  );

  const {
    agents,
    sources,
    edges,
    dispatch,
    saveAgent,
    deleteAgent,
    saveSource,
    deleteSource,
    connectNodes,
    deleteEdge: deleteEdgeBase,
  } = useCanvasState();

  const {
    steps,
    cur,
    setCur,
    simMode,
    logExp,
    setLogExp,
    activeNode,
    activeEdge,
    particles,
    runSim,
    stopSim,
  } = useSimulation(agents, edges);

  const [logSidebarWidth, setLogSidebarWidth] = useState(290);
  const prevSidebarWidth = useRef(290);
  const [panAdjust, setPanAdjust] = useState({ dx: 0, seq: 0 });

  const handleSidebarWidthChange = useCallback((w: number) => {
    const delta = w - prevSidebarWidth.current;
    prevSidebarWidth.current = w;
    setLogSidebarWidth(w);
    // Shift the canvas pan by half the width delta so the network stays centred.
    setPanAdjust((p) => ({ dx: -delta / 2, seq: p.seq + 1 }));
  }, []);

  const {
    selNode,
    setSelNode,
    selEdge,
    setSelEdge,
    panel,
    setPanel,
    ctx,
    setCtx,
    showTweaks,
    setShowTweaks,
  } = useUIState();

  const [importError, setImportError] = useState<string | null>(null);
  const importErrorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );

  useEffect(() => {
    return () => {
      if (importErrorTimerRef.current)
        clearTimeout(importErrorTimerRef.current);
    };
  }, []);

  // Wire deleteEdge to also clear selection
  const deleteEdge = useCallback(
    (id: string) => {
      deleteEdgeBase(id);
      setSelEdge(null);
    },
    [deleteEdgeBase, setSelEdge],
  );

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
  }, [
    selNode,
    selEdge,
    agents,
    dispatch,
    setPanel,
    setCtx,
    setSelNode,
    setSelEdge,
    setShowTweaks,
  ]);

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
    [dispatch, showImportError],
  );

  const selectNode = useCallback(
    (id: string, e: React.MouseEvent) => {
      setSelNode(id);
      setSelEdge(null);
      if (e?.button === 2) {
        e.preventDefault();
        setCtx({ x: e.clientX, y: e.clientY, nodeId: id });
      }
    },
    [setSelNode, setSelEdge, setCtx],
  );

  const openPanel = useCallback(
    (id: string) => {
      if (simMode) return;
      if (agents.some((a) => a.id === id)) setPanel({ type: "agent", id });
      else if (sources.some((s) => s.id === id))
        setPanel({ type: "source", id });
    },
    [simMode, agents, sources, setPanel],
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
      label: "Add File",
      icon: "FileText",
      fn: () => {
        setPanel({ type: "source", id: null });
        setSelNode(null);
      },
    },
  ];

  const onSelectEdge = useCallback(
    (id: string) => {
      setSelEdge(id);
      setSelNode(null);
    },
    [setSelEdge, setSelNode],
  );

  const onMoveNode = useCallback(
    (id: string, pos: { x: number; y: number }) =>
      dispatch({ type: "MOVE_NODE", id, position: pos }),
    [dispatch],
  );

  const onCanvasClick = useCallback(() => {
    setSelNode(null);
    setSelEdge(null);
    setPanel(null);
    setCtx(null);
  }, [setSelNode, setSelEdge, setPanel, setCtx]);

  const onAddAgent = useCallback(() => {
    setPanel({ type: "agent", id: null });
    setSelNode(null);
  }, [setPanel, setSelNode]);

  const onAddFile = useCallback(() => {
    setPanel({ type: "source", id: null });
    setSelNode(null);
  }, [setPanel, setSelNode]);

  const onClear = useCallback(() => dispatch({ type: "CLEAR" }), [dispatch]);
  const onAutoLayout = useCallback(
    () => dispatch({ type: "AUTO_LAYOUT" }),
    [dispatch],
  );
  const onToggleTweaks = useCallback(
    () => setShowTweaks((x) => !x),
    [setShowTweaks],
  );

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

      <div
        style={{
          width: simMode ? `calc(100vw - ${logSidebarWidth}px)` : "100%",
          height: "100%",
          display: "flex",
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
          tweaks={tweaks}
          onCanvasClick={onCanvasClick}
          panAdjust={panAdjust}
        />

        <Toolbar
          simMode={simMode}
          onToggleTheme={toggleTheme}
          onAddAgent={onAddAgent}
          onAddFile={onAddFile}
          onClear={onClear}
          onStop={stopSim}
          onAutoLayout={onAutoLayout}
          onExport={exportCanvas}
          onImport={importCanvas}
          showTweaks={showTweaks}
          onToggleTweaks={onToggleTweaks}
        />

        <PromptBar simMode={simMode} onRun={runSim} />
      </div>

      {simMode && (
        <LogWall
          steps={steps}
          currentStep={cur}
          onNext={() => setCur((s) => Math.min(s + 1, steps.length - 1))}
          onPrev={() => setCur((s) => Math.max(s - 1, 0))}
          expanded={logExp}
          onToggleExpand={() => setLogExp((x) => !x)}
          sidebarWidth={logSidebarWidth}
          onSidebarWidthChange={handleSidebarWidthChange}
        />
      )}

      {showTweaks && (
        <TweaksPanel
          tweaks={tweaks}
          onChange={setTweak}
          onClose={() => setShowTweaks(false)}
        />
      )}

      {panel?.type === "agent" && (
        <AgentPanel
          key={panel.id ?? "new-agent"}
          agent={panelAgent}
          agents={agents}
          onSave={async (data) => {
            await saveAgent(data);
            setPanel(null);
          }}
          onDelete={async (id) => {
            await deleteAgent(id);
            setPanel(null);
            setSelNode(null);
            setCtx(null);
          }}
          onClose={() => setPanel(null)}
        />
      )}
      {panel?.type === "source" && (
        <SourcePanel
          key={panel.id ?? "new-source"}
          source={panelSource}
          onSave={(data) => {
            saveSource(data);
            setPanel(null);
          }}
          onDelete={(id) => {
            deleteSource(id);
            setPanel(null);
            setSelNode(null);
            setCtx(null);
          }}
          onClose={() => setPanel(null)}
        />
      )}

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

      {ctx && (
        <ContextMenu
          x={ctx.x}
          y={ctx.y}
          items={ctx.nodeId ? nodeCtxItems(ctx.nodeId) : canvasCtxItems}
          onClose={() => setCtx(null)}
        />
      )}

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
