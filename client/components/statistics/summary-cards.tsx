"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { getTheme } from "@/lib/theme";
import type { TrialSummary } from "@/lib/types";

const PIE_COLORS = [
  "#8b1a2f",
  "#c2596d",
  "#5a8bce",
  "#6ec1a8",
  "#d8b15a",
  "#9b7bce",
  "#5d697c",
  "#bf6f45",
];

function formatMode(mode: string | null) {
  if (!mode) return "Unknown";
  return mode
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function Kpi({
  label,
  value,
  dark,
}: {
  label: string;
  value: number | string;
  dark: boolean;
}) {
  const t = getTheme(dark);
  return (
    <div
      style={{
        background: t.surface,
        border: `1px solid ${t.border}`,
        borderRadius: 8,
        padding: "14px 16px",
        minWidth: 130,
        flex: "1 1 130px",
      }}
    >
      <div style={{ color: t.textSub, fontSize: 11, fontWeight: 600 }}>
        {label}
      </div>
      <div
        style={{
          color: t.text,
          fontSize: 24,
          fontWeight: 700,
          overflowWrap: "anywhere",
        }}
      >
        {value}
      </div>
    </div>
  );
}

export function SummaryCards({
  summary,
  dark,
}: {
  summary: TrialSummary;
  dark: boolean;
}) {
  const t = getTheme(dark);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div
        style={{
          background: t.surface,
          border: `1px solid ${t.border}`,
          borderRadius: 8,
          padding: "14px 16px",
        }}
      >
        <div
          style={{
            color: t.textSub,
            fontSize: 11,
            fontWeight: 700,
            marginBottom: 6,
            textTransform: "uppercase",
          }}
        >
          Question
        </div>
        <div
          style={{
            color: t.text,
            fontSize: 14,
            fontWeight: 650,
            lineHeight: 1.35,
            overflowWrap: "anywhere",
          }}
        >
          {summary.userPrompt}
        </div>
        <div
          style={{
            color: t.textSub,
            fontSize: 12,
            fontWeight: 600,
            marginTop: 10,
            overflowWrap: "anywhere",
          }}
        >
          Convergence algorithm: {formatMode(summary.mode)}
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <Kpi label="Agents" value={summary.agentCount} dark={dark} />
        <Kpi label="Rounds" value={summary.roundCount} dark={dark} />
        <Kpi label="Messages" value={summary.totalMessages} dark={dark} />
        <Kpi label="Edges" value={summary.totalEdges} dark={dark} />
        <Kpi label="Status" value={summary.status} dark={dark} />
      </div>
    </div>
  );
}

export function MessageTypesChart({
  summary,
  dark,
}: {
  summary: TrialSummary;
  dark: boolean;
}) {
  const t = getTheme(dark);
  const pieData = Object.entries(summary.messageTypeCounts).map(
    ([name, value]) => ({ name, value }),
  );

  return (
    <div
      style={{
        background: t.surface,
        border: `1px solid ${t.border}`,
        borderRadius: 8,
        padding: 16,
        minHeight: 280,
      }}
    >
      <div
        style={{
          color: t.text,
          fontSize: 13,
          fontWeight: 600,
          marginBottom: 8,
        }}
      >
        Message types
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <PieChart>
          <Pie
            data={pieData}
            dataKey="value"
            nameKey="name"
            outerRadius={80}
            label
          >
            {pieData.map((entry, i) => (
              <Cell key={entry.name} fill={PIE_COLORS[i % PIE_COLORS.length]} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{
              background: t.surface,
              border: `1px solid ${t.border}`,
              color: t.text,
            }}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
