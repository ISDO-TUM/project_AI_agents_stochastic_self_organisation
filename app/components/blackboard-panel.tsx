"use client";

import { useState } from "react";
import { useBlackboard } from "@/hooks/useBlackboard";
import { ConfirmedSection } from "@/components/confirmed-section";
import { DraftSection } from "@/components/draft-section";
import { useTheme } from "@/lib/theme-context";
import { getTheme } from "@/lib/theme";

interface BlackboardPanelProps {
  runId: string | null;
  onRunIdChange: (id: string | null) => void;
}

export function BlackboardPanel({ runId, onRunIdChange }: BlackboardPanelProps) {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const { state } = useBlackboard(runId);
  const [activeThreadIdx, setActiveThreadIdx] = useState(0);
  const [seeding, setSeeding] = useState(false);

  const border = (t as { border?: string }).border ?? "rgba(139,26,47,0.2)";

  const activeThread = state.threads[activeThreadIdx] ?? null;
  const filteredConfirmed = activeThread
    ? state.confirmed.filter((e) => e.thread_id === activeThread.id)
    : state.confirmed;
  const filteredDraft = activeThread
    ? state.draft.filter((e) => e.thread_id === activeThread.id)
    : state.draft;

  const handleSeed = async () => {
    setSeeding(true);
    try {
      const res = await fetch("/api/simulation/seed", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: "Test blackboard seeding", agent_ids: [] }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { run_id: string; thread_id: string };
      onRunIdChange(data.run_id);
    } catch (err) {
      console.error("Seed failed:", err);
    } finally {
      setSeeding(false);
    }
  };

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        background: t.bg,
        borderLeft: `1px solid ${border}`,
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "12px 16px",
          borderBottom: `1px solid ${border}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexShrink: 0,
        }}
      >
        <span
          style={{
            fontWeight: 700,
            fontSize: 13,
            letterSpacing: "0.05em",
            color: "#8B1A2F",
          }}
        >
          BLACKBOARD
        </span>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {runId && (
            <span
              style={{
                fontFamily: "monospace",
                fontSize: 10,
                color: dark ? "rgba(255,255,255,0.35)" : "rgba(0,0,0,0.35)",
              }}
            >
              {runId.slice(0, 8)}
            </span>
          )}
          <button
            onClick={() => onRunIdChange(null)}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: dark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.4)",
              fontSize: 16,
              lineHeight: 1,
              padding: "2px 4px",
            }}
            title="Close blackboard"
          >
            ×
          </button>
        </div>
      </div>

      {/* No run — seed prompt */}
      {!runId && (
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 12,
            padding: 24,
          }}
        >
          <div
            style={{
              fontSize: 13,
              color: dark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.4)",
              textAlign: "center",
            }}
          >
            No active run. Seed test data to preview the blackboard.
          </div>
          <button
            onClick={handleSeed}
            disabled={seeding}
            style={{
              padding: "8px 20px",
              background: "#8B1A2F",
              color: "#fff",
              border: "none",
              borderRadius: 6,
              cursor: seeding ? "not-allowed" : "pointer",
              fontSize: 13,
              fontWeight: 600,
              opacity: seeding ? 0.6 : 1,
            }}
          >
            {seeding ? "Seeding…" : "Seed test data"}
          </button>
        </div>
      )}

      {/* Loading state */}
      {runId && state.loading && (
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: dark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.4)",
            fontSize: 13,
          }}
        >
          Loading…
        </div>
      )}

      {/* Error state */}
      {runId && state.error && !state.loading && (
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 12,
            padding: 24,
          }}
        >
          <div style={{ color: "#c0392b", fontSize: 13 }}>
            Error: {state.error}
          </div>
          <button
            onClick={handleSeed}
            disabled={seeding}
            style={{
              padding: "8px 20px",
              background: "#8B1A2F",
              color: "#fff",
              border: "none",
              borderRadius: 6,
              cursor: seeding ? "not-allowed" : "pointer",
              fontSize: 13,
              fontWeight: 600,
              opacity: seeding ? 0.6 : 1,
            }}
          >
            {seeding ? "Seeding…" : "Seed test data"}
          </button>
        </div>
      )}

      {/* Thread tabs */}
      {runId && !state.loading && !state.error && state.threads.length > 0 && (
        <div
          style={{
            display: "flex",
            gap: 4,
            padding: "8px 12px 0",
            borderBottom: `1px solid ${border}`,
            flexShrink: 0,
            overflowX: "auto",
          }}
        >
          {state.threads.map((thread, idx) => (
            <button
              key={thread.id}
              onClick={() => setActiveThreadIdx(idx)}
              style={{
                padding: "5px 12px",
                borderRadius: "4px 4px 0 0",
                border: "none",
                background:
                  idx === activeThreadIdx
                    ? dark
                      ? "rgba(139,26,47,0.3)"
                      : "rgba(139,26,47,0.1)"
                    : "none",
                color:
                  idx === activeThreadIdx
                    ? "#8B1A2F"
                    : dark
                    ? "rgba(255,255,255,0.5)"
                    : "rgba(0,0,0,0.5)",
                cursor: "pointer",
                fontSize: 12,
                fontWeight: idx === activeThreadIdx ? 700 : 400,
                whiteSpace: "nowrap",
              }}
            >
              §{idx + 1} {thread.title}
            </button>
          ))}
        </div>
      )}

      {/* Blackboard content */}
      {runId && !state.loading && !state.error && (
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "12px 16px",
          }}
        >
          <ConfirmedSection entries={filteredConfirmed} />
          <DraftSection entries={filteredDraft} />
        </div>
      )}
    </div>
  );
}
