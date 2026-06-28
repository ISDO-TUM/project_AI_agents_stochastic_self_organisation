"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { createPortal } from "react-dom";
import {
  CanvasState,
  ConsensusMode,
  Rule,
  SourceType,
  TopologyMode,
  Tweaks,
} from "@/lib/types";
import { BURG } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import { useCanvasState } from "@/hooks/useCanvasState";
import { useSimulation } from "@/hooks/useSimulation";
import { useUIState } from "@/hooks/useUIState";
import {
  fetchAgents,
  fetchFiles,
  fetchRules,
  createAgent,
  deleteAgentApi,
  createFile,
  deleteFileApi,
  attachFile,
  clearAll,
} from "@/lib/api";
import { Canvas } from "@/components/canvas";
import { LogWall } from "@/components/log-wall";
import { Toolbar } from "@/components/toolbar";
import { HistoryPage } from "@/components/history-page";
import { PromptBar } from "@/components/prompt-bar";
import { ContextMenu, ContextMenuItem } from "@/components/context-menu";
import { TweaksPanel } from "@/components/tweaks-panel";

import { AgentPanel } from "@/components/panels/agent-panel";
import { SourcePanel } from "@/components/panels/source-panel";
import { ModeGate, AppMode } from "@/components/mode-gate";
import {
  SwarmConfigModal,
  SwarmRunConfig,
} from "@/components/swarm-config-modal";
import { useDummySwarm } from "@/hooks/useDummySwarm";
import { useSwarmRun } from "@/hooks/useSwarmRun";
import { generateDummyRun } from "@/lib/dummy-swarm";
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

interface AppProps {
  onModeSelected?: () => void;
}

export function App({ onModeSelected }: AppProps = {}) {
  const { dark, toggle: toggleTheme } = useTheme();

  const [tweaks] = useState<Tweaks>(defaultTweaks);

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
    running,
    turns,
    logExp,
    setLogExp,
    activeNode,
    activeEdge,
    activeEdgeReversed,
    particles,
    runSim,
    stopSim,
    dynamicEdges,
    resetContext,
    batchProgress,
  } = useSimulation(agents, edges);

  const [logSidebarWidth, setLogSidebarWidth] = useState(290);
  const prevSidebarWidth = useRef(290);
  const [panAdjust, setPanAdjust] = useState({ dx: 0, seq: 0 });
  const [showHistory, setShowHistory] = useState(false);

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
  const [sourceOverlay, setSourceOverlay] = useState<{
    id: string | null;
    sourceType?: SourceType;
    presetAgentId?: string;
  } | null>(null);
  const [overlayWidth, setOverlayWidth] = useState(360);

  const [rules, setRules] = useState<Rule[]>([]);
  const [selectedRules, setSelectedRules] = useState<Set<string>>(new Set());
  const [importError, setImportError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [appMode, setAppMode] = useState<AppMode | null>(null);
  const [swarmConfigOpen, setSwarmConfigOpen] = useState(false);
  const [pendingSwarmPrompt, setPendingSwarmPrompt] = useState("");
  const [topbarWidth, setTopbarWidth] = useState<number | null>(null);
  const [topbarHeight, setTopbarHeight] = useState<number | null>(null);
  const [promptBarHeight, setPromptBarHeight] = useState<number | null>(null);
  const dummy = useDummySwarm();
  // Real swarm run: streams SSE and builds the board directly from the events
  // (draft → confirmed), like the dummy — no REST re-fetch, no activity log.
  const swarm = useSwarmRun();
  const blackboardState = dummy.state.active
    ? dummy.state.blackboard
    : swarm.state.blackboard;

  // Run configuration — edited in the Settings panel, read at run start.
  const [consensusMode, setConsensusMode] =
    useState<ConsensusMode>("plurality_voting");
  const [topology, setTopology] = useState<TopologyMode>("static");
  const [fanout, setFanout] = useState(3);
  const [iterations, setIterations] = useState(1);
  const [biddingBoardOpen, setBiddingBoardOpen] = useState(false);

  useEffect(() => {
    fetchRules()
      .then((rs) => {
        setRules(rs);
        setSelectedRules((prev) => {
          if (prev.size > 0) return prev;
          return new Set(rs.filter((r) => r.default).map((r) => r.id));
        });
      })
      .catch(() => {});
  }, []);

  const toggleRule = useCallback((id: string) => {
    setSelectedRules((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleRun = useCallback(
    (prompt: string) => {
      if (appMode === "swarm") {
        setPendingSwarmPrompt(prompt);
        setSwarmConfigOpen(true);
        return;
      }
      const active = rules.filter((r) => selectedRules.has(r.id));
      const ruleset = active.length
        ? active.map((r) => `- ${r.instruction}`).join("\n")
        : undefined;
      if (consensusMode === "bidding") setBiddingBoardOpen(true);
      runSim(prompt, consensusMode, ruleset, topology, fanout, iterations);
    },
    [
      appMode,
      rules,
      selectedRules,
      runSim,
      consensusMode,
      topology,
      fanout,
      iterations,
    ],
  );

  const handleSwarmConfigConfirm = useCallback(
    (config: SwarmRunConfig) => {
      setSwarmConfigOpen(false);
      if (pendingSwarmPrompt.trim().toLowerCase() === "test_mohamed") {
        swarm.reset();
        const fixture = generateDummyRun(
          { takers: config.takersMax, rounds: config.roundsMax },
          agents,
        );
        dummy.start(fixture);
        setRunId(fixture.runId);
        return;
      }
      dummy.reset();
      setRunId(null);
      swarm.start(pendingSwarmPrompt);
    },
    [pendingSwarmPrompt, agents, dummy, swarm],
  );
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
          if (agents.some((a) => a.id === selNode)) deleteAgent(selNode);
          else deleteSource(selNode);
          setSelNode(null);
        }
        if (selEdge) {
          deleteEdge(selEdge);
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
    deleteAgent,
    deleteSource,
    deleteEdge,
    setPanel,
    setCtx,
    setSelNode,
    setSelEdge,
    setShowTweaks,
  ]);

  const exportCanvas = useCallback(() => {
    const payload: CanvasState = { agents, sources, edges };
    if (selectedRules.size > 0) payload.selectedRules = [...selectedRules];
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "canvas.json";
    a.click();
    URL.revokeObjectURL(url);
  }, [agents, sources, edges, selectedRules]);

  const showImportError = useCallback((msg: string) => {
    if (importErrorTimerRef.current) clearTimeout(importErrorTimerRef.current);
    setImportError(msg);
    importErrorTimerRef.current = setTimeout(() => setImportError(null), 4000);
  }, []);

  const importCanvas = useCallback(
    async (raw: string) => {
      let data: CanvasState;
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const parsed = JSON.parse(raw) as any;
        if (
          !Array.isArray(parsed.agents) ||
          !Array.isArray(parsed.sources) ||
          !Array.isArray(parsed.edges)
        ) {
          showImportError(
            "Invalid canvas file — missing agents, sources, or edges",
          );
          return;
        }
        data = parsed as CanvasState;
        // Auto-assign positions for any agents/sources that omit them
        // (e.g. configs generated for Market Hive mode without layout info).
        data = {
          ...data,
          agents: data.agents.map((a, i) => ({
            ...a,
            position: a.position ?? {
              x: 160 + (i % 4) * 220,
              y: 180 + Math.floor(i / 4) * 180,
            },
          })),
          sources: data.sources.map((s, i) => ({
            ...s,
            position: s.position ?? {
              x: 180 + (i % 4) * 220,
              y: 480 + Math.floor(i / 4) * 180,
            },
          })),
        };
      } catch {
        showImportError("Invalid JSON file");
        return;
      }

      // Render the imported canvas locally first so the user sees it instantly.
      dispatch({ type: "LOAD", state: data });
      if (Array.isArray(data.selectedRules)) {
        setSelectedRules(
          new Set(data.selectedRules.filter((x) => typeof x === "string")),
        );
      }

      // Persist to the backend so simulations have the same state. Do it on a
      // best-effort basis — if the API is offline we keep the local view but
      // surface the error.
      try {
        const [existingAgents, existingFiles] = await Promise.all([
          fetchAgents(),
          fetchFiles(),
        ]);
        await Promise.all([
          ...existingAgents.map((a) => deleteAgentApi(a.id).catch(() => {})),
          ...existingFiles.map((f) => deleteFileApi(f.id).catch(() => {})),
        ]);

        await Promise.all(
          data.sources.map((s) =>
            createFile(s.name, s.content, s.id).catch(() => {}),
          ),
        );
        await Promise.all(
          data.agents.map((a) => createAgent(a, { preserveId: true })),
        );
        const fileIds = new Set(data.sources.map((s) => s.id));
        await Promise.all(
          data.edges
            .filter(
              (e) =>
                data.agents.some((a) => a.id === e.from) && fileIds.has(e.to),
            )
            .map((e) => attachFile(e.from, e.to).catch(() => {})),
        );
      } catch (err) {
        showImportError(
          `Imported locally, but failed to sync to API: ${
            err instanceof Error ? err.message : "unknown error"
          }`,
        );
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
        if (agents.some((a) => a.id === id)) deleteAgent(id);
        else deleteSource(id);
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

  const onAddDataset = useCallback(() => {
    setPanel({ type: "source", id: null, sourceType: "dataset" });
    setSelNode(null);
  }, [setPanel, setSelNode]);

  const onClear = useCallback(async () => {
    await clearAll().catch(() => {});
    dispatch({ type: "CLEAR" });
    // Also wipe the swarm run state and boards so the canvas starts fresh.
    dummy.reset();
    setRunId(null);
    stopSim();
  }, [dispatch, dummy, stopSim]);
  const onAutoLayout = useCallback(
    () => dispatch({ type: "AUTO_LAYOUT" }),
    [dispatch],
  );
  const onToggleTweaks = useCallback(
    () => setShowTweaks((x) => !x),
    [setShowTweaks],
  );

  // Source.agentIds is never populated from real data (load() never sets it,
  // and saveSource/createFile don't persist it) — the real truth is `edges`,
  // same lookup `connectedSources` in agent-panel.tsx already uses. Override
  // agentIds with that derived value whenever handing an existing source to
  // SourcePanel, so "Assign to agents" reflects reality instead of always
  // showing every chip unchecked.
  const withRealAgentIds = (sourceId: string) => {
    const found = sources.find((s) => s.id === sourceId);
    if (!found) return null;
    return {
      ...found,
      agentIds: edges
        .filter((e) => e.from === sourceId || e.to === sourceId)
        .map((e) => (e.from === sourceId ? e.to : e.from))
        .filter((id) => agents.some((a) => a.id === id)),
    };
  };

  const panelAgent =
    panel?.type === "agent" && panel.id
      ? agents.find((a) => a.id === panel.id) ?? null
      : null;
  const panelSource =
    panel?.type === "source" && panel.id ? withRealAgentIds(panel.id) : null;
  const overlaySource = sourceOverlay?.id
    ? withRealAgentIds(sourceOverlay.id)
    : null;
  const t = getTheme(dark);
  const hasNodes = agents.length > 0 || sources.length > 0;

  if (!appMode) {
    return (
      <ModeGate
        onSelect={(mode) => {
          setAppMode(mode);
          onModeSelected?.();
        }}
      />
    );
  }

  return (
    <div
      style={{
        display: "flex",
        height: "100%",
        width: "100%",
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
          flexShrink: 0,
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
          dynamicEdges={simMode ? dynamicEdges : []}
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
          activeEdgeReversed={activeEdgeReversed}
          animatedParticles={particles}
          tweaks={tweaks}
          onCanvasClick={onCanvasClick}
          panAdjust={panAdjust}
          blackboardState={blackboardState}
          appMode={appMode}
          swarmRunId={
            appMode === "swarm"
              ? dummy.state.active
                ? runId
                : swarm.state.runId
              : null
          }
          topbarWidth={topbarWidth}
          topbarHeight={topbarHeight}
          promptBarHeight={promptBarHeight}
          onSelectAgentChip={openPanel}
          swarmDone={
            appMode === "swarm" && (dummy.state.done || swarm.state.done)
          }
          swarmTrustVectors={dummy.state.trustVectors}
          phonebook={
            topology === "dynamic"
              ? {
                  agents,
                  steps,
                  currentStep: cur,
                  dynamicEdges: simMode ? dynamicEdges : [],
                  simMode,
                }
              : null
          }
          biddingBoard={
            simMode && biddingBoardOpen && consensusMode === "bidding"
              ? {
                  steps,
                  onClose: () => setBiddingBoardOpen(false),
                }
              : null
          }
        />

        <Toolbar
          simMode={simMode}
          onToggleTheme={toggleTheme}
          onAddAgent={onAddAgent}
          onAddFile={onAddFile}
          onAddDataset={onAddDataset}
          onClear={onClear}
          onStop={stopSim}
          onAutoLayout={onAutoLayout}
          onExport={exportCanvas}
          onImport={importCanvas}
          onOpenHistory={() => setShowHistory(true)}
          showTweaks={showTweaks}
          onToggleTweaks={onToggleTweaks}
          showBiddingBoardToggle={consensusMode === "bidding"}
          biddingBoardOpen={biddingBoardOpen}
          onToggleBiddingBoard={() => setBiddingBoardOpen((x) => !x)}
          onWidthChange={setTopbarWidth}
          onHeightChange={setTopbarHeight}
        />

        <PromptBar
          running={running}
          turnCount={turns.length}
          onRun={handleRun}
          onResetContext={resetContext}
          onOpenKeys={() => setShowTweaks(true)}
          iterations={iterations}
          onIterationsChange={setIterations}
          batchProgress={batchProgress}
          onHeightChange={setPromptBarHeight}
        />
      </div>

      {/* Log wall — only shows during active simulation (topology or swarm) */}
      {simMode && (
        <LogWall
          steps={steps}
          currentStep={cur}
          onNext={() => setCur((s) => Math.min(s + 1, steps.length - 1))}
          onPrev={() => setCur((s) => Math.max(s - 1, 0))}
          onJumpTo={(idx) => setCur(idx)}
          expanded={logExp}
          onToggleExpand={() => setLogExp((x) => !x)}
          sidebarWidth={logSidebarWidth}
          onSidebarWidthChange={handleSidebarWidthChange}
        />
      )}

      {showTweaks && (
        <TweaksPanel
          rules={rules}
          selectedRules={selectedRules}
          onToggleRule={toggleRule}
          consensusMode={consensusMode}
          onConsensusModeChange={setConsensusMode}
          consensusLocked={agents.length < 2}
          topology={topology}
          onTopologyChange={setTopology}
          fanout={fanout}
          onFanoutChange={setFanout}
          simRunning={simMode}
          onClose={() => setShowTweaks(false)}
          appMode={appMode}
        />
      )}

      {swarmConfigOpen && (
        <SwarmConfigModal
          onCancel={() => setSwarmConfigOpen(false)}
          onConfirm={handleSwarmConfigConfirm}
        />
      )}

      {panel?.type === "agent" && (
        <AgentPanel
          key={panel.id ?? "new-agent"}
          agent={panelAgent}
          agents={agents}
          sources={sources}
          edges={edges}
          overlayWidth={sourceOverlay ? overlayWidth : 0}
          onSave={async (data) => {
            await saveAgent(data);
            setPanel(null);
            setSourceOverlay(null);
          }}
          onDelete={async (id) => {
            await deleteAgent(id);
            setPanel(null);
            setSourceOverlay(null);
            setSelNode(null);
            setCtx(null);
          }}
          onClose={() => {
            setPanel(null);
            setSourceOverlay(null);
          }}
          onEditSource={(sourceId) => setSourceOverlay({ id: sourceId })}
          onDetachSource={(sourceId) => {
            if (!panelAgent) return;
            const edge = edges.find(
              (e) =>
                (e.from === panelAgent.id && e.to === sourceId) ||
                (e.to === panelAgent.id && e.from === sourceId),
            );
            if (edge) deleteEdge(edge.id);
          }}
          onAddFile={() =>
            setSourceOverlay({
              id: null,
              sourceType: "text",
              presetAgentId: panelAgent?.id,
            })
          }
          onAddDataset={() =>
            setSourceOverlay({
              id: null,
              sourceType: "dataset",
              presetAgentId: panelAgent?.id,
            })
          }
        />
      )}
      {sourceOverlay && (
        <SourcePanel
          key={sourceOverlay.id ?? "new-source-overlay"}
          source={overlaySource}
          initialType={sourceOverlay.sourceType}
          agents={agents}
          presetAgentId={sourceOverlay.presetAgentId}
          onSave={(data) => {
            saveSource(data);
            setSourceOverlay(null);
          }}
          onDelete={(id) => {
            deleteSource(id);
            setSourceOverlay(null);
          }}
          onClose={() => setSourceOverlay(null)}
          onWidthChange={setOverlayWidth}
        />
      )}
      {panel?.type === "source" && (
        <SourcePanel
          key={panel.id ?? "new-source"}
          source={panelSource}
          initialType={panel.sourceType}
          agents={agents}
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

      {showHistory &&
        createPortal(
          <div
            style={{
              position: "fixed",
              inset: 0,
              zIndex: 300,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              backdropFilter: "blur(4px)",
              background: dark ? "rgba(6,5,12,0.65)" : "rgba(240,238,248,0.65)",
            }}
            onClick={() => setShowHistory(false)}
          >
            <div
              style={{
                width: "min(1100px, 92vw)",
                height: "min(820px, 88vh)",
                borderRadius: 16,
                overflow: "hidden",
                boxShadow: dark
                  ? "0 24px 72px rgba(0,0,0,0.65)"
                  : "0 16px 48px rgba(0,0,0,0.18)",
                border: `1px solid ${t.borderHi}`,
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <HistoryPage onBack={() => setShowHistory(false)} />
            </div>
          </div>,
          document.body,
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
