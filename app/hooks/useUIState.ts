"use client";

import { useState } from "react";

interface PanelState {
  type: "agent" | "source";
  id: string | null;
}

interface CtxState {
  x: number;
  y: number;
  nodeId: string | null;
}

export function useUIState() {
  const [selNode, setSelNode] = useState<string | null>(null);
  const [selEdge, setSelEdge] = useState<string | null>(null);
  const [panel, setPanel] = useState<PanelState | null>(null);
  const [ctx, setCtx] = useState<CtxState | null>(null);
  const [showTweaks, setShowTweaks] = useState(false);

  return {
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
  };
}
