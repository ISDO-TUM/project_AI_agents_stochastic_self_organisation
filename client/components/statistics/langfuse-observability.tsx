"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ChartLegend,
  EmptyState,
  Kpi,
  StatCard,
  chartTooltipProps,
} from "@/components/statistics/primitives";
import { getTheme } from "@/lib/theme";
import type { LangfuseStats } from "@/lib/types";

function formatCost(value: number) {
  return value > 0 ? `$${value.toFixed(4)}` : "$0.0000";
}

function formatMs(value: number) {
  return value > 0 ? `${Math.round(value)} ms` : "0 ms";
}

export function LlmUsageSummaryCards({
  langfuse,
  dark,
  delay = 0,
}: {
  langfuse: LangfuseStats;
  dark: boolean;
  delay?: number;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(min(160px, 100%), 1fr))",
        gap: 12,
      }}
    >
      <Kpi
        label="Traces"
        icon="ListTree"
        value={langfuse.summary.traceCount}
        dark={dark}
        delay={delay}
      />
      <Kpi
        label="Generations"
        icon="Sparkles"
        value={langfuse.summary.generationCount}
        dark={dark}
        delay={delay + 40}
      />
      <Kpi
        label="Total tokens"
        icon="Coins"
        value={langfuse.summary.totalTokens}
        dark={dark}
        delay={delay + 80}
      />
      <Kpi
        label="Estimated cost"
        icon="CircleDollarSign"
        value={formatCost(langfuse.summary.totalCost)}
        dark={dark}
        delay={delay + 120}
      />
      <Kpi
        label="Avg latency"
        icon="Timer"
        value={formatMs(langfuse.summary.averageLatencyMs)}
        dark={dark}
        delay={delay + 160}
      />
      <Kpi
        label="Slowest model"
        icon="Snail"
        value={langfuse.summary.slowestModel ?? "Unknown"}
        dark={dark}
        delay={delay + 200}
      />
    </div>
  );
}

export function TokensByModelChart({
  langfuse,
  dark,
  delay = 0,
}: {
  langfuse: LangfuseStats;
  dark: boolean;
  delay?: number;
}) {
  const t = getTheme(dark);
  const tt = chartTooltipProps(dark);
  const modelData = langfuse.models.map((model) => ({
    name: model.model,
    "Input tokens": model.inputTokens,
    "Output tokens": model.outputTokens,
  }));

  return (
    <StatCard
      title="Tokens by model"
      icon="Boxes"
      dark={dark}
      delay={delay}
      minHeight={320}
      meta={
        <ChartLegend
          items={[
            { label: "Input", color: "#5a8bce" },
            { label: "Output", color: "#8b1a2f" },
          ]}
          dark={dark}
        />
      }
    >
      <ResponsiveContainer width="100%" height={270}>
        <BarChart
          data={modelData}
          barGap={3}
          barCategoryGap="30%"
          margin={{ top: 6, right: 12, bottom: 0, left: 0 }}
        >
          <CartesianGrid
            vertical={false}
            strokeDasharray="3 3"
            stroke={t.border}
          />
          <XAxis
            dataKey="name"
            axisLine={false}
            tickLine={false}
            tick={{ fill: t.textSub, fontSize: 11 }}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{ fill: t.textSub, fontSize: 11 }}
            allowDecimals={false}
          />
          <Tooltip
            contentStyle={tt.contentStyle}
            labelStyle={tt.labelStyle}
            itemStyle={tt.itemStyle}
            cursor={{ fill: t.hover }}
          />
          <Bar
            dataKey="Input tokens"
            fill="#5a8bce"
            radius={[4, 4, 0, 0]}
            maxBarSize={26}
          />
          <Bar
            dataKey="Output tokens"
            fill="#8b1a2f"
            radius={[4, 4, 0, 0]}
            maxBarSize={26}
          />
        </BarChart>
      </ResponsiveContainer>
    </StatCard>
  );
}

export function PerAgentLlmUsageChart({
  langfuse,
  dark,
  delay = 0,
}: {
  langfuse: LangfuseStats;
  dark: boolean;
  delay?: number;
}) {
  const t = getTheme(dark);
  const tt = chartTooltipProps(dark);

  const agentData = langfuse.agents.map((agent) => ({
    name: agent.agentName,
    Tokens: agent.totalTokens,
    "Avg latency": Math.round(agent.averageLatencyMs),
  }));
  const agentChartHeight = Math.max(260, langfuse.agents.length * 46 + 40);
  const agentYAxisWidth = Math.min(
    220,
    Math.max(96, ...langfuse.agents.map((agent) => agent.agentName.length * 7)),
  );

  return (
    <StatCard
      title="Per-agent LLM usage"
      icon="Users"
      dark={dark}
      delay={delay}
      minHeight={320}
      meta={
        <ChartLegend
          items={[
            { label: "Tokens", color: "#6ec1a8" },
            { label: "Avg latency (ms)", color: "#d8b15a" },
          ]}
          dark={dark}
        />
      }
    >
      <ResponsiveContainer width="100%" height={agentChartHeight}>
        <BarChart
          data={agentData}
          layout="vertical"
          barGap={2}
          barCategoryGap="26%"
          margin={{ top: 4, right: 20, bottom: 0, left: 0 }}
        >
          <CartesianGrid
            horizontal={false}
            strokeDasharray="3 3"
            stroke={t.border}
          />
          <XAxis
            type="number"
            axisLine={false}
            tickLine={false}
            tick={{ fill: t.textSub, fontSize: 11 }}
            allowDecimals={false}
          />
          <YAxis
            type="category"
            dataKey="name"
            axisLine={false}
            tickLine={false}
            tick={{ fill: t.textSub, fontSize: 11 }}
            width={agentYAxisWidth}
            interval={0}
          />
          <Tooltip
            contentStyle={tt.contentStyle}
            labelStyle={tt.labelStyle}
            itemStyle={tt.itemStyle}
            cursor={{ fill: t.hover }}
          />
          <Bar
            dataKey="Tokens"
            fill="#6ec1a8"
            radius={[0, 4, 4, 0]}
            maxBarSize={10}
          />
          <Bar
            dataKey="Avg latency"
            fill="#d8b15a"
            radius={[0, 4, 4, 0]}
            maxBarSize={10}
          />
        </BarChart>
      </ResponsiveContainer>
    </StatCard>
  );
}

export function LlmRoundsChart({
  langfuse,
  dark,
  delay = 0,
}: {
  langfuse: LangfuseStats;
  dark: boolean;
  delay?: number;
}) {
  const t = getTheme(dark);
  const tt = chartTooltipProps(dark);
  const roundData = langfuse.rounds.map((round) => ({
    round: round.roundIndex ? `R${round.roundIndex}` : "Unknown",
    Tokens: round.totalTokens,
    Cost: round.totalCost,
    "Avg latency": Math.round(round.averageLatencyMs),
  }));

  return (
    <StatCard
      title="Cost and tokens over rounds"
      icon="TrendingUp"
      dark={dark}
      delay={delay}
      minHeight={320}
      meta={
        <ChartLegend
          items={[
            { label: "Tokens", color: "#5a8bce" },
            { label: "Cost", color: "#c4374f" },
            { label: "Avg latency (ms)", color: "#d8b15a" },
          ]}
          dark={dark}
        />
      }
    >
      <ResponsiveContainer width="100%" height={270}>
        <LineChart
          data={roundData}
          margin={{ top: 6, right: 12, bottom: 0, left: 0 }}
        >
          <CartesianGrid
            vertical={false}
            strokeDasharray="3 3"
            stroke={t.border}
          />
          <XAxis
            dataKey="round"
            axisLine={false}
            tickLine={false}
            tick={{ fill: t.textSub, fontSize: 11 }}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{ fill: t.textSub, fontSize: 11 }}
            allowDecimals={false}
          />
          <Tooltip
            contentStyle={tt.contentStyle}
            labelStyle={tt.labelStyle}
            itemStyle={tt.itemStyle}
            cursor={{ stroke: t.borderHi }}
          />
          <Line
            type="monotone"
            dataKey="Tokens"
            stroke="#5a8bce"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 0 }}
          />
          <Line
            type="monotone"
            dataKey="Cost"
            stroke="#c4374f"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 0 }}
          />
          <Line
            type="monotone"
            dataKey="Avg latency"
            stroke="#d8b15a"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 0 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </StatCard>
  );
}

export function LangfuseObservability({
  langfuse,
  dark,
}: {
  langfuse: LangfuseStats;
  dark: boolean;
}) {
  if (!langfuse.available) {
    return (
      <EmptyState
        icon="Cpu"
        title="No LLM usage data"
        sub={
          langfuse.message ??
          "No Langfuse statistics are available for this trial."
        }
        dark={dark}
      />
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <LlmUsageSummaryCards langfuse={langfuse} dark={dark} />
      <LlmRoundsChart langfuse={langfuse} dark={dark} delay={240} />
      <div
        style={{
          display: "grid",
          gridTemplateColumns:
            "repeat(auto-fit, minmax(min(420px, 100%), 1fr))",
          gap: 16,
          alignItems: "stretch",
        }}
      >
        <TokensByModelChart langfuse={langfuse} dark={dark} delay={300} />
        <PerAgentLlmUsageChart langfuse={langfuse} dark={dark} delay={360} />
      </div>
    </div>
  );
}
