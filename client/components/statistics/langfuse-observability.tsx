"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getTheme } from "@/lib/theme";
import type { LangfuseStats } from "@/lib/types";

function formatCost(value: number) {
  return value > 0 ? `$${value.toFixed(4)}` : "$0.0000";
}

function formatMs(value: number) {
  return value > 0 ? `${Math.round(value)} ms` : "0 ms";
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
        minWidth: 150,
        flex: "1 1 150px",
      }}
    >
      <div style={{ color: t.textSub, fontSize: 11, fontWeight: 600 }}>
        {label}
      </div>
      <div
        style={{
          color: t.text,
          fontSize: 23,
          fontWeight: 700,
          overflowWrap: "anywhere",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function Panel({
  title,
  children,
  dark,
}: {
  title: string;
  children: React.ReactNode;
  dark: boolean;
}) {
  const t = getTheme(dark);
  return (
    <div
      style={{
        background: t.surface,
        border: `1px solid ${t.border}`,
        borderRadius: 8,
        padding: 16,
        minHeight: 330,
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
        {title}
      </div>
      {children}
    </div>
  );
}

export function LlmUsageSummaryCards({
  langfuse,
  dark,
}: {
  langfuse: LangfuseStats;
  dark: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        flexWrap: "wrap",
        gridColumn: "1 / -1",
      }}
    >
      <Kpi label="Traces" value={langfuse.summary.traceCount} dark={dark} />
      <Kpi
        label="Generations"
        value={langfuse.summary.generationCount}
        dark={dark}
      />
      <Kpi
        label="Total tokens"
        value={langfuse.summary.totalTokens}
        dark={dark}
      />
      <Kpi
        label="Estimated cost"
        value={formatCost(langfuse.summary.totalCost)}
        dark={dark}
      />
      <Kpi
        label="Avg latency"
        value={formatMs(langfuse.summary.averageLatencyMs)}
        dark={dark}
      />
      <Kpi
        label="Slowest model"
        value={langfuse.summary.slowestModel ?? "Unknown"}
        dark={dark}
      />
    </div>
  );
}

export function TokensByModelChart({
  langfuse,
  dark,
}: {
  langfuse: LangfuseStats;
  dark: boolean;
}) {
  const t = getTheme(dark);
  const modelData = langfuse.models.map((model) => ({
    name: model.model,
    "Input tokens": model.inputTokens,
    "Output tokens": model.outputTokens,
  }));

  return (
    <Panel title="Tokens by model" dark={dark}>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={modelData}>
          <CartesianGrid strokeDasharray="3 3" stroke={t.border} />
          <XAxis dataKey="name" stroke={t.textSub} fontSize={11} />
          <YAxis stroke={t.textSub} fontSize={11} allowDecimals={false} />
          <Tooltip
            contentStyle={{
              background: t.surface,
              border: `1px solid ${t.border}`,
              color: t.text,
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: t.textSub }} />
          <Bar dataKey="Input tokens" fill="#5a8bce" />
          <Bar dataKey="Output tokens" fill="#8b1a2f" />
        </BarChart>
      </ResponsiveContainer>
    </Panel>
  );
}

export function PerAgentLlmUsageChart({
  langfuse,
  dark,
}: {
  langfuse: LangfuseStats;
  dark: boolean;
}) {
  const t = getTheme(dark);

  const agentData = langfuse.agents.map((agent) => ({
    name: agent.agentName,
    Tokens: agent.totalTokens,
    Cost: agent.totalCost,
    "Avg latency": Math.round(agent.averageLatencyMs),
  }));
  const agentChartHeight = Math.max(280, langfuse.agents.length * 42 + 48);
  const agentYAxisWidth = Math.min(
    220,
    Math.max(96, ...langfuse.agents.map((agent) => agent.agentName.length * 7)),
  );

  return (
    <Panel title="Per-agent LLM usage" dark={dark}>
      <ResponsiveContainer width="100%" height={agentChartHeight}>
        <BarChart
          data={agentData}
          layout="vertical"
          margin={{ top: 8, right: 20, bottom: 8, left: 8 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={t.border} />
          <XAxis
            type="number"
            stroke={t.textSub}
            fontSize={11}
            allowDecimals={false}
          />
          <YAxis
            type="category"
            dataKey="name"
            stroke={t.textSub}
            fontSize={11}
            width={agentYAxisWidth}
            interval={0}
          />
          <Tooltip
            contentStyle={{
              background: t.surface,
              border: `1px solid ${t.border}`,
              color: t.text,
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: t.textSub }} />
          <Bar dataKey="Tokens" fill="#6ec1a8" />
          <Bar dataKey="Avg latency" fill="#d8b15a" />
        </BarChart>
      </ResponsiveContainer>
    </Panel>
  );
}

export function LlmRoundsChart({
  langfuse,
  dark,
}: {
  langfuse: LangfuseStats;
  dark: boolean;
}) {
  const t = getTheme(dark);
  const roundData = langfuse.rounds.map((round) => ({
    round: round.roundIndex ? `R${round.roundIndex}` : "Unknown",
    Tokens: round.totalTokens,
    Cost: round.totalCost,
    "Avg latency": Math.round(round.averageLatencyMs),
  }));

  return (
    <Panel title="Cost and tokens over rounds" dark={dark}>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={roundData}>
          <CartesianGrid strokeDasharray="3 3" stroke={t.border} />
          <XAxis dataKey="round" stroke={t.textSub} fontSize={11} />
          <YAxis stroke={t.textSub} fontSize={11} allowDecimals={false} />
          <Tooltip
            contentStyle={{
              background: t.surface,
              border: `1px solid ${t.border}`,
              color: t.text,
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: t.textSub }} />
          <Line
            type="monotone"
            dataKey="Tokens"
            stroke="#5a8bce"
            strokeWidth={2}
          />
          <Line
            type="monotone"
            dataKey="Cost"
            stroke="#8b1a2f"
            strokeWidth={2}
          />
          <Line
            type="monotone"
            dataKey="Avg latency"
            stroke="#d8b15a"
            strokeWidth={2}
          />
        </LineChart>
      </ResponsiveContainer>
    </Panel>
  );
}

export function LangfuseObservability({
  langfuse,
  dark,
}: {
  langfuse: LangfuseStats;
  dark: boolean;
}) {
  const t = getTheme(dark);

  if (!langfuse.available) {
    return (
      <div
        style={{
          background: t.surface,
          border: `1px solid ${t.border}`,
          borderRadius: 8,
          color: t.textSub,
          padding: 18,
        }}
      >
        {langfuse.message ??
          "No Langfuse statistics are available for this trial."}
      </div>
    );
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(min(360px, 100%), 1fr))",
        gap: 16,
      }}
    >
      <LlmUsageSummaryCards langfuse={langfuse} dark={dark} />
      <TokensByModelChart langfuse={langfuse} dark={dark} />
      <PerAgentLlmUsageChart langfuse={langfuse} dark={dark} />
      <div style={{ gridColumn: "1 / -1" }}>
        <LlmRoundsChart langfuse={langfuse} dark={dark} />
      </div>
    </div>
  );
}
