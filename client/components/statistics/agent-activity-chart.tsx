"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ChartLegend,
  StatCard,
  chartTooltipProps,
} from "@/components/statistics/primitives";
import { getTheme } from "@/lib/theme";
import type { AgentStat } from "@/lib/types";

const SERIES = [
  { key: "Sent", color: "#8b1a2f" },
  { key: "Received", color: "#5a8bce" },
  { key: "Tools", color: "#d8b15a" },
];

export function AgentActivityChart({
  agents,
  dark,
  delay = 0,
}: {
  agents: AgentStat[];
  dark: boolean;
  delay?: number;
}) {
  const t = getTheme(dark);
  const tt = chartTooltipProps(dark);
  const chartHeight = Math.max(260, agents.length * 46 + 40);
  const yAxisWidth = Math.min(
    220,
    Math.max(96, ...agents.map((a) => a.agentName.length * 7)),
  );
  const data = agents.map((a) => ({
    name: a.agentName,
    Sent: a.messagesSent,
    Received: a.messagesReceived,
    Tools: a.toolInvocations,
  }));

  return (
    <StatCard
      title="Per-agent activity"
      icon="Users"
      dark={dark}
      delay={delay}
      minHeight={300}
      meta={
        <ChartLegend
          items={SERIES.map((s) => ({ label: s.key, color: s.color }))}
          dark={dark}
        />
      }
    >
      <ResponsiveContainer width="100%" height={chartHeight}>
        <BarChart
          data={data}
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
            width={yAxisWidth}
            interval={0}
          />
          <Tooltip
            contentStyle={tt.contentStyle}
            labelStyle={tt.labelStyle}
            itemStyle={tt.itemStyle}
            cursor={{ fill: t.hover }}
          />
          {SERIES.map((s) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              fill={s.color}
              radius={[0, 4, 4, 0]}
              maxBarSize={10}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </StatCard>
  );
}
