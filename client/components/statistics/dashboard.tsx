"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ComparisonDashboard } from "@/components/comparison/dashboard";
import { AgentActivityChart } from "@/components/statistics/agent-activity-chart";
import { CommunicationGraph } from "@/components/statistics/communication-graph";
import { LangfuseObservability } from "@/components/statistics/langfuse-observability";
import { RoundsTimelineChart } from "@/components/statistics/rounds-timeline-chart";
import {
  MessageTypesChart,
  SummaryCards,
} from "@/components/statistics/summary-cards";
import { useStatistics } from "@/hooks/useStatistics";
import { fetchHistoryTrials } from "@/lib/api";
import { getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import type { HistoryTrial } from "@/lib/types";

function formatRunTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatTrialOption(trial: HistoryTrial) {
  return `${trial.id} - ${formatRunTimestamp(trial.createdAt)}`;
}

export function StatisticsDashboard() {
  const { dark } = useTheme();
  const t = getTheme(dark);
  const [trials, setTrials] = useState<HistoryTrial[]>([]);
  const [trialId, setTrialId] = useState<string | null>(null);
  const [trialsLoading, setTrialsLoading] = useState(true);
  const [view, setView] = useState<"collaboration" | "langfuse" | "comparison">(
    "collaboration",
  );
  const stats = useStatistics(trialId);

  useEffect(() => {
    fetchHistoryTrials()
      .then((rows) => {
        setTrials(rows);
        if (rows.length > 0) setTrialId(rows[0].id);
      })
      .catch(() => setTrials([]))
      .finally(() => setTrialsLoading(false));
  }, []);

  return (
    <main
      style={{
        background: t.bg,
        color: t.text,
        height: "100vh",
        overflowY: "auto",
        overscrollBehavior: "contain",
        padding: 24,
        paddingBottom: 48,
        scrollbarGutter: "stable",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          marginBottom: 20,
        }}
      >
        <Link
          href="/"
          style={{ color: t.textSub, fontSize: 13, textDecoration: "none" }}
        >
          Back
        </Link>
        <h1 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>Statistics</h1>
        <div
          style={{
            display: "flex",
            background: t.surface,
            border: `1px solid ${t.border}`,
            borderRadius: 8,
            padding: 3,
          }}
        >
          {[
            ["collaboration", "Collaboration"],
            ["langfuse", "LLM usage"],
            ["comparison", "Comparison"],
          ].map(([id, label]) => {
            const active = view === id;
            return (
              <button
                key={id}
                type="button"
                onClick={() =>
                  setView(id as "collaboration" | "langfuse" | "comparison")
                }
                style={{
                  background: active ? "rgba(139,26,47,0.2)" : "transparent",
                  border: "none",
                  borderRadius: 6,
                  color: active ? t.text : t.textSub,
                  cursor: "pointer",
                  fontSize: 12,
                  fontWeight: 700,
                  padding: "6px 10px",
                }}
              >
                {label}
              </button>
            );
          })}
        </div>
        {view !== "comparison" && (
          <select
            value={trialId ?? ""}
            onChange={(e) => setTrialId(e.target.value || null)}
            disabled={trials.length === 0}
            style={{
              marginLeft: "auto",
              background: t.surface,
              color: t.text,
              border: `1px solid ${t.border}`,
              borderRadius: 8,
              padding: "7px 10px",
              fontSize: 12,
              maxWidth: "min(52vw, 520px)",
            }}
          >
            {trials.length === 0 && (
              <option value="">
                {trialsLoading ? "Loading trials" : "No trials yet"}
              </option>
            )}
            {trials.map((tr) => (
              <option key={tr.id} value={tr.id}>
                {formatTrialOption(tr)}
              </option>
            ))}
          </select>
        )}
      </div>

      {view !== "comparison" && stats.loading && (
        <div style={{ color: t.textSub }}>Loading...</div>
      )}
      {view !== "comparison" && stats.error && (
        <div style={{ color: "#c2596d" }}>{stats.error}</div>
      )}

      {!stats.loading &&
        !stats.error &&
        stats.summary &&
        view === "collaboration" && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns:
                "repeat(auto-fit, minmax(min(360px, 100%), 1fr))",
              alignItems: "stretch",
              gap: 16,
            }}
          >
            <div style={{ gridColumn: "1 / -1" }}>
              <SummaryCards summary={stats.summary} dark={dark} />
            </div>
            <MessageTypesChart summary={stats.summary} dark={dark} />
            <CommunicationGraph
              agents={stats.agents}
              edges={stats.edges}
              dark={dark}
            />
            <AgentActivityChart agents={stats.agents} dark={dark} />
            <div style={{ gridColumn: "1 / -1" }}>
              <RoundsTimelineChart rounds={stats.rounds} dark={dark} />
            </div>
          </div>
        )}
      {!stats.loading &&
        !stats.error &&
        stats.langfuse &&
        view === "langfuse" && (
          <LangfuseObservability langfuse={stats.langfuse} dark={dark} />
        )}
      {view === "comparison" && <ComparisonDashboard />}
    </main>
  );
}
